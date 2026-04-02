"""
Crisis-Mode Strategy Backtest — 30天战争行情专用

Strategies designed for geopolitical crisis / extreme fear markets:
  H: Short-Only Trend+SMC (只做空, 趋势向下时使用SMC)
  I: Mean Reversion (极端波动后反转, 暴跌做多/暴涨做空)
  J: ATR-Adaptive Trend+SMC (Trend+SMC + 高波动自动缩仓)
  K: Short the Rally (等反弹到EMA21再做空)
  L: Hybrid Crisis (综合: 大趋势做空反弹 + 暴跌后短线做多)

Baselines (from v1):
  C: Trend+SMC @60 (之前的冠军)
  G: Full 18-Layer @70

Data: OKX + CoinAnk (same as v2)
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from loguru import logger

from backend.trading.indicator_subset_backtest import (
    score_group_c, score_group_e, simulate_trades, _finalize,
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from backend.trading.indicator_subset_backtest_v2 import OKXDataFetcher

try:
    from backend.analysis.smart_money import analyze_smc as _analyze_smc
except Exception:
    _analyze_smc = None


# ============================================================
# Crisis Scoring Functions
# ============================================================

def score_crisis_h(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group H: Short-Only Trend+SMC — 只在趋势向下时做空, 永不做多"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    # Trend scoring (same as group A)
    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    trends_agree = (trend_15m == trend_1h == trend_4h) and trend_15m != 0
    if trends_agree:
        trend_score = int(trend_score * 1.2)
    if not trends_agree and abs(trend_score) > 8:
        trend_score -= int(trend_score * 0.5)
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score

    # Price structure
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count, ll_count = 0, 0
    for i in range(1, min(5, len(recent_highs))):
        if recent_highs[i-1] > recent_highs[i]: hh_count += 1
        if recent_lows[i-1] < recent_lows[i]: ll_count += 1
    price_structure = "no_structure"
    if hh_count >= 3: tech_score += 5; price_structure = "bullish_structure"
    elif ll_count >= 3: tech_score -= 5; price_structure = "bearish_structure"

    # EMA cross
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        ema8_prev = calc_ema(closes[-31:-1], 8) if len(closes) >= 31 else ema8
        ema21_prev = calc_ema(closes[-31:-1], 21) if len(closes) >= 31 else ema21
        if ema8 < ema21 and ema8_prev >= ema21_prev: tech_score -= 5  # Only bearish cross

    # SMC
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc["score_adjustment"]
            if smc_adj < 0:  # Only bearish SMC signals
                tech_score += smc_adj
                breakdown.append(f"SMC{smc_adj}")
        except: pass

    tech_score = max(0, min(100, tech_score))

    # FORCE short-only: if score > 50 (bullish), force neutral
    result = _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                       atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)
    if result["direction"] == "bullish":
        result["direction"] = "neutral"  # Never go long in crisis
    return result


def score_crisis_i(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group I: Mean Reversion — 暴跌后做多(短线), 暴涨后做空(短线)"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    atr_pct = atr_approx / current_price * 100 if current_price > 0 else 1

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    # Calculate recent price change (last 3 bars)
    if len(closes) >= 4:
        pct_3bar = (closes[-1] / closes[-4] - 1) * 100
    else:
        pct_3bar = 0

    # Calculate recent price change (last 6 bars)
    if len(closes) >= 7:
        pct_6bar = (closes[-1] / closes[-7] - 1) * 100
    else:
        pct_6bar = 0

    # RSI for oversold/overbought
    rsi = calc_rsi(closes)

    # Mean reversion signals
    # Extreme drop = buy signal (bounce)
    extreme_drop_thresh = -atr_pct * 1.5  # ~3-5% depending on ATR
    extreme_pump_thresh = atr_pct * 1.5

    if pct_3bar < extreme_drop_thresh and rsi < 30:
        tech_score += 20  # Strong bounce signal
        breakdown.append(f"暴跌反弹+20(3bar={pct_3bar:.1f}%,RSI={rsi:.0f})")
    elif pct_6bar < extreme_drop_thresh * 1.5 and rsi < 25:
        tech_score += 15
        breakdown.append(f"持续暴跌反弹+15(6bar={pct_6bar:.1f}%)")
    elif pct_3bar > extreme_pump_thresh and rsi > 70:
        tech_score -= 20  # Overbought after pump = short
        breakdown.append(f"暴涨回调-20(3bar={pct_3bar:.1f}%,RSI={rsi:.0f})")
    elif pct_6bar > extreme_pump_thresh * 1.5 and rsi > 75:
        tech_score -= 15
        breakdown.append(f"持续暴涨回调-15(6bar={pct_6bar:.1f}%)")

    tech_score = max(0, min(100, tech_score))

    # Use tighter TP/SL for mean reversion (shorter holds)
    price_structure = "no_structure"
    result = _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                       atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)

    # Override SL/TP for mean reversion: tighter targets
    if result["direction"] != "neutral":
        if result["direction"] == "bullish":
            result["sl"] = round(current_price - atr_approx * 1.5, 2)  # Tighter SL
            result["tp"] = round(current_price + atr_approx * 2.5, 2)  # Tighter TP
        else:
            result["sl"] = round(current_price + atr_approx * 1.5, 2)
            result["tp"] = round(current_price - atr_approx * 2.5, 2)

    return result


def score_crisis_j(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group J: ATR-Adaptive Trend+SMC — Trend+SMC but 高波动时仓位自动缩小"""
    # Use the same scoring as Group C (Trend+SMC)
    result = score_group_c(closes, highs, lows, opens, volumes, current_price, **kw)

    # Calculate ATR-based volatility multiplier
    atr = result.get("atr", 0)
    atr_pct = atr / current_price * 100 if current_price > 0 else 1

    # Widen SL/TP when volatility is high
    if atr_pct > 3.0:       # Very high vol (crisis level)
        vol_mult = 2.0       # 2x wider SL/TP
        result["leverage"] = 1  # Force min leverage
    elif atr_pct > 2.0:     # High vol
        vol_mult = 1.5
        result["leverage"] = max(1, result.get("leverage", 2) - 1)
    elif atr_pct > 1.5:     # Elevated vol
        vol_mult = 1.2
    else:
        vol_mult = 1.0

    if result["direction"] != "neutral":
        entry = current_price
        old_sl = result["sl"]
        old_tp = result["tp"]

        if result["direction"] == "bullish":
            sl_dist = abs(entry - old_sl) * vol_mult
            tp_dist = abs(old_tp - entry) * vol_mult
            result["sl"] = round(entry - sl_dist, 2)
            result["tp"] = round(entry + tp_dist, 2)
        else:
            sl_dist = abs(old_sl - entry) * vol_mult
            tp_dist = abs(entry - old_tp) * vol_mult
            result["sl"] = round(entry + sl_dist, 2)
            result["tp"] = round(entry - tp_dist, 2)

    return result


def score_crisis_k(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group K: Short the Rally — 等价格反弹到EMA21再做空"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    # Must be in downtrend on 4H
    if trend_4h >= 0:
        return {"score": 50, "direction": "neutral", "breakdown": ["4H非下跌趋势"], "atr": atr_approx,
                "sl": current_price, "tp": current_price, "rr_ratio": 0, "leverage": 1,
                "rsi": calc_rsi(closes), "adx": adx, "market_regime": "ranging",
                "trend_4h": trend_4h, "trend_1h": trend_1h, "price_structure": "no_structure"}

    # Check if price has bounced to EMA21
    ema21 = calc_ema(closes[-30:], 21)
    ema50 = calc_ema(closes[-60:], 50) if len(closes) >= 60 else ema21

    # Price near or above EMA21 = short entry
    distance_to_ema21 = (current_price - ema21) / ema21 * 100

    if distance_to_ema21 > 0 and distance_to_ema21 < 3.0:
        # Price bounced to EMA21 — prime short entry
        tech_score -= 15
        breakdown.append(f"反弹至EMA21-15(距离{distance_to_ema21:.1f}%)")
    elif distance_to_ema21 >= 3.0 and distance_to_ema21 < 5.0:
        # Price above EMA21 but in downtrend — strong short
        tech_score -= 20
        breakdown.append(f"超越EMA21-20(距离{distance_to_ema21:.1f}%)")
    elif distance_to_ema21 < -3.0:
        # Price way below EMA21 — don't chase shorts
        tech_score = 50  # neutral
        breakdown.append(f"已远离EMA21,不追空(距离{distance_to_ema21:.1f}%)")

    # SMC confirmation
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc["score_adjustment"]
            if smc_adj < 0:  # Bearish SMC confirms
                tech_score += smc_adj
                breakdown.append(f"SMC确认{smc_adj}")
        except: pass

    # Price structure (LL/LH = bearish)
    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    ll_count = 0
    for i in range(1, min(5, len(recent_lows))):
        if recent_lows[i-1] < recent_lows[i]: ll_count += 1
    price_structure = "no_structure"
    if ll_count >= 3: tech_score -= 5; price_structure = "bearish_structure"

    tech_score = max(0, min(100, tech_score))
    result = _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                       atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)

    # Force short-only
    if result["direction"] == "bullish":
        result["direction"] = "neutral"
    return result


def score_crisis_l(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group L: Hybrid Crisis — 组合策略:
    - 大趋势下行 + 反弹到EMA → 做空
    - 暴跌后RSI<20 → 短线做多反弹 (紧TP)
    - 高波动时降杠杆/缩仓
    """
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    atr_pct = atr_approx / current_price * 100 if current_price > 0 else 1

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    rsi = calc_rsi(closes)

    # Recent price change
    pct_3bar = (closes[-1] / closes[-4] - 1) * 100 if len(closes) >= 4 else 0

    # EMA21
    ema21 = calc_ema(closes[-30:], 21) if len(closes) >= 21 else current_price
    distance_to_ema21 = (current_price - ema21) / ema21 * 100

    # SMC
    smc_adj = 0
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc["score_adjustment"]
        except: pass

    # ===== STRATEGY SELECTION =====

    # Strategy 1: Crash bounce (RSI extreme + big recent drop)
    if rsi < 22 and pct_3bar < -3.0:
        tech_score += 15  # Bullish (bounce)
        breakdown.append(f"暴跌反弹+15(RSI={rsi:.0f},3bar={pct_3bar:.1f}%)")
        # This trade uses TIGHT TP
        is_bounce = True
    # Strategy 2: Short the rally (downtrend + bounce to EMA21)
    elif trend_4h < 0 and distance_to_ema21 > 0 and distance_to_ema21 < 5.0:
        tech_score -= 15
        breakdown.append(f"做空反弹-15(EMA21距离={distance_to_ema21:.1f}%)")
        if smc_adj < 0:
            tech_score += smc_adj  # SMC confirms bearish
            breakdown.append(f"SMC确认{smc_adj}")
        is_bounce = False
    # Strategy 3: Strong bearish trend continuation
    elif trend_4h < 0 and trend_1h < 0 and trend_15m < 0:
        tech_score -= 10
        breakdown.append("三重下跌趋势-10")
        if smc_adj < 0:
            tech_score += smc_adj
        is_bounce = False
    else:
        is_bounce = False

    # Price structure
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count, ll_count = 0, 0
    for i in range(1, min(5, len(recent_highs))):
        if recent_highs[i-1] > recent_highs[i]: hh_count += 1
        if recent_lows[i-1] < recent_lows[i]: ll_count += 1
    price_structure = "no_structure"
    if hh_count >= 3: price_structure = "bullish_structure"
    elif ll_count >= 3: tech_score -= 3; price_structure = "bearish_structure"

    # FNG extreme fear bonus for bounce trades
    fng = kw.get("fng_value", 50)
    if fng <= 10 and is_bounce:
        tech_score += 5
        breakdown.append(f"极度恐惧+5(FNG={fng})")

    tech_score = max(0, min(100, tech_score))
    result = _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                       atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)

    # Bounce trades: tighter SL/TP
    if is_bounce and result["direction"] == "bullish":
        result["sl"] = round(current_price - atr_approx * 1.2, 2)
        result["tp"] = round(current_price + atr_approx * 2.0, 2)
        result["leverage"] = 1  # Low leverage for bounce

    # Crisis vol adjustment: force lower leverage
    if atr_pct > 3.0:
        result["leverage"] = 1
    elif atr_pct > 2.0:
        result["leverage"] = max(1, result.get("leverage", 2) - 1)

    return result


# ============================================================
# Main Runner
# ============================================================

CRISIS_GROUPS = [
    # Baselines
    ("C: Trend+SMC @60 (baseline)", score_group_c, 60),
    ("G: Full@70 (baseline)", score_group_e, 70),
    # Crisis strategies
    ("H: Short-Only Trend+SMC", score_crisis_h, 60),
    ("I: Mean Reversion", score_crisis_i, 55),
    ("J: ATR-Adaptive Trend+SMC", score_crisis_j, 60),
    ("K: Short the Rally (EMA21)", score_crisis_k, 60),
    ("L: Hybrid Crisis", score_crisis_l, 55),
]


async def run_crisis_backtest():
    fetcher = OKXDataFetcher()
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    days = 30

    all_results = {}
    lines = []
    lines.append("=" * 100)
    lines.append("CRISIS MODE STRATEGY BACKTEST — 30天战争行情 (OKX+CoinAnk)")
    lines.append("=" * 100)

    for symbol in symbols:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        start_ms = int(start.timestamp() * 1000)

        logger.info(f"\n{'='*60}")
        logger.info(f"🔬 {symbol} — 30天危机回测")
        logger.info(f"{'='*60}")

        data = await fetcher.fetch_all(symbol, start, end, days)
        klines = data["klines"]

        if len(klines) < 100:
            logger.error(f"K线不足: {len(klines)}")
            continue

        logger.info(f"  数据: {len(klines)} K线")

        results = []
        for label, score_fn, threshold in CRISIS_GROUPS:
            r = simulate_trades(klines, score_fn, data, start_ms,
                               score_threshold=threshold, label=label)
            results.append(r)
            logger.info(f"    {label}: {r['trades']}T {r['win_rate']}%WR "
                       f"${r['total_pnl']:+.0f} PF={r['profit_factor']:.2f}")

        all_results[symbol] = results

        lines.append(f"\n{'='*80}")
        lines.append(f"  {symbol} (30d)")
        lines.append(f"{'='*80}")
        lines.append(f"  {'Group':<35} {'T':>4} {'WR%':>6} {'PnL$':>10} {'PnL%':>7} {'PF':>6} {'DD%':>6}")
        lines.append(f"  {'-'*80}")
        for r in results:
            marker = " ★" if r["total_pnl"] > 0 else ""
            lines.append(f"  {r['label']:<35} {r['trades']:>4} {r['win_rate']:>5.1f}% "
                        f"{r['total_pnl']:>+9.0f} {r['total_pnl_pct']:>+6.1f}% "
                        f"{r['profit_factor']:>5.2f} {r['max_drawdown_pct']:>5.1f}%{marker}")

        await asyncio.sleep(1)

    # Cross-symbol summary
    lines.append(f"\n{'='*80}")
    lines.append("CROSS-SYMBOL CRISIS RANKING (avg PnL% across BTC/ETH/SOL 30d)")
    lines.append(f"{'='*80}")
    group_totals = {}
    for label, _, _ in CRISIS_GROUPS:
        pnl_pcts = []
        for symbol in symbols:
            for r in all_results.get(symbol, []):
                if r["label"] == label:
                    pnl_pcts.append(r["total_pnl_pct"])
        if pnl_pcts:
            group_totals[label] = sum(pnl_pcts) / len(pnl_pcts)
    for label, avg_pnl in sorted(group_totals.items(), key=lambda x: -x[1]):
        marker = " ✅ PROFIT" if avg_pnl > 0 else ""
        lines.append(f"  {label:<35} avg PnL%: {avg_pnl:>+6.2f}%{marker}")

    report = "\n".join(lines)
    print(report)

    # Save
    os.makedirs("data", exist_ok=True)
    save_data = {
        "timestamp": datetime.now().isoformat(),
        "type": "crisis_mode_30d_backtest",
        "data_source": "OKX + CoinAnk",
        "symbols": symbols,
        "period_days": days,
        "results": {},
    }
    for symbol in symbols:
        save_data["results"][symbol] = [
            {k: v for k, v in r.items() if k != "trade_details"} for r in all_results.get(symbol, [])
        ]

    with open("data/backtest_crisis_30d.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    with open("data/backtest_crisis_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"\n💾 Results: data/backtest_crisis_30d.json")
    logger.info(f"💾 Report:  data/backtest_crisis_report.txt")


if __name__ == "__main__":
    asyncio.run(run_crisis_backtest())
