"""
Crisis Profitability Research — 寻找30天战争行情盈利策略

核心问题：当前SL太紧，暴力反弹不断扫损
解决方向：
  M: Swing Short (宽SL 3xATR, 长持有, 只做大波段)
  N: Momentum Cascade Short (连续3根阴线才开空, 等动能确认)
  O: Wide-Stop Short (和H一样只做空, 但SL放宽到4xATR)
  P: Selective Short (只在RSI>40反弹时做空, 避免追空)
  Q: Micro-Position Short (0.5%风险而不是2%, 小仓扛大波动)
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
# Modified simulate_trades with configurable risk%
# ============================================================

def simulate_trades_v2(klines, score_fn, data, start_ms, initial_balance=10000,
                       risk_pct=2.0, score_threshold=60, label="", max_hold_override=None):
    """Trade simulation with configurable risk_pct and max_hold"""
    from backend.trading.backtester_v2 import _SortedLookup
    fr_data = data["funding_rates"]
    ls_data = data["long_short_ratios"]
    oi_data = data["oi_history"]
    fng_history = data.get("fng_history", {})

    fr_lookup = _SortedLookup(fr_data)
    ls_lookup = _SortedLookup(ls_data)
    oi_lookup = _SortedLookup(oi_data)

    balance = initial_balance
    position = None
    trades = []
    equity = [initial_balance]
    last_trade_close_idx = -999
    consecutive_losses = 0
    daily_pnl = 0.0
    current_day = None

    closes, highs, lows, opens, volumes = [], [], [], [], []

    for idx, k in enumerate(klines):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])
        equity.append(round(balance, 2))

        if len(closes) < 50 or k["ts"] < start_ms:
            continue

        ts = k["ts"]
        price = k["close"]
        high = k["high"]
        low = k["low"]

        trade_day = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        if trade_day != current_day:
            daily_pnl = 0.0
            current_day = trade_day

        # Check existing position
        if position:
            sl_hit = (position["side"] == "buy" and low <= position["sl"]) or \
                     (position["side"] == "sell" and high >= position["sl"])
            tp_hit = (position["side"] == "buy" and high >= position["tp"]) or \
                     (position["side"] == "sell" and low <= position["tp"])
            bars_held = idx - position["opened_idx"]
            max_hold = max_hold_override or (36 if position.get("regime") == "trending" else 18)

            if bars_held >= max_hold and not tp_hit:
                exit_p = price
                pnl = (exit_p - position["entry"]) * position["amount"] if position["side"] == "buy" else \
                      (position["entry"] - exit_p) * position["amount"]
                balance += pnl
                trades.append({"side": position["side"], "entry": position["entry"],
                               "exit": round(exit_p, 2), "pnl": round(pnl, 2),
                               "reason": "max_hold", "bars": bars_held})
                position = None
                last_trade_close_idx = idx
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
            elif sl_hit or tp_hit:
                exit_p = position["sl"] if sl_hit else position["tp"]
                pnl = (exit_p - position["entry"]) * position["amount"] if position["side"] == "buy" else \
                      (position["entry"] - exit_p) * position["amount"]
                if tp_hit and not sl_hit:
                    # Partial TP 60%
                    partial_pnl = pnl * 0.6
                    balance += partial_pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(partial_pnl, 2),
                                   "reason": "partial_tp", "bars": bars_held})
                    position["amount"] *= 0.4
                    position["sl"] = position["entry"]  # Move SL to breakeven
                    ext = abs(position["tp"] - position["entry"]) * 0.5
                    position["tp"] = round(position["tp"] + ext if position["side"] == "buy" else position["tp"] - ext, 2)
                    consecutive_losses = 0
                else:
                    balance += pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(pnl, 2),
                                   "reason": "sl" if sl_hit else "tp_full", "bars": bars_held})
                    position = None
                    last_trade_close_idx = idx
                    consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
            else:
                # Trailing stop
                if position["side"] == "buy":
                    td = abs(position["tp"] - position["entry"])
                    if price >= position["entry"] + td * 0.4:
                        new_sl = max(position["sl"], position["entry"] + td * 0.15)
                        if new_sl > position["sl"]: position["sl"] = round(new_sl, 2)
                elif position["side"] == "sell":
                    td = abs(position["entry"] - position["tp"])
                    if price <= position["entry"] - td * 0.4:
                        new_sl = min(position["sl"], position["entry"] - td * 0.15)
                        if new_sl < position["sl"]: position["sl"] = round(new_sl, 2)

        if position:
            continue
        cooldown = 3
        if idx - last_trade_close_idx < cooldown:
            continue
        if consecutive_losses >= 3:
            if idx - last_trade_close_idx < 12:
                continue
            consecutive_losses = 0

        # Score
        fr_val = fr_lookup.find(ts)
        ls_val = ls_lookup.find(ts)
        oi_cur = oi_lookup.find(ts)
        oi_prev = oi_lookup.find(ts - 3600000)
        fng_val = 50
        ts_day = ts // 86400000
        for offset in range(3):
            if (ts_day - offset) in fng_history:
                fng_val = fng_history[ts_day - offset]
                break

        result = score_fn(
            closes[:], highs[:], lows[:], opens[:], volumes[:], price,
            funding_rate=fr_val, ls_ratio=ls_val,
            oi_current=oi_cur, oi_prev=oi_prev,
            fng_value=fng_val,
            score_threshold=score_threshold,
        )

        direction = result["direction"]
        if direction == "neutral":
            continue

        side = "buy" if direction == "bullish" else "sell"
        risk_amount = balance * risk_pct / 100
        sl_dist = abs(price - result["sl"])
        if sl_dist <= 0:
            continue
        amount = risk_amount / sl_dist
        lev = result.get("leverage", 2)
        position_value = amount * price
        margin = position_value / lev

        if margin > balance * 0.95:
            amount = balance * 0.95 * lev / price
            margin = balance * 0.95

        position = {
            "side": side, "entry": price, "amount": amount,
            "sl": result["sl"], "tp": result["tp"],
            "leverage": lev, "opened_idx": idx,
            "regime": result.get("market_regime", "transitioning"),
        }

    if position:
        price = closes[-1]
        pnl = (price - position["entry"]) * position["amount"] if position["side"] == "buy" else \
              (position["entry"] - price) * position["amount"]
        balance += pnl
        trades.append({"side": position["side"], "entry": position["entry"],
                       "exit": round(price, 2), "pnl": round(pnl, 2),
                       "reason": "end_of_backtest", "bars": len(klines) - position["opened_idx"]})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    profit_factor = abs(sum(t["pnl"] for t in wins)) / abs(sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else 999
    max_dd = 0
    peak = initial_balance
    for e in equity:
        if e > peak: peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd: max_dd = dd

    return {
        "label": label, "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_balance * 100, 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2), "max_drawdown_pct": round(max_dd, 2),
        "final_balance": round(balance, 2), "trade_details": trades,
    }


# ============================================================
# New Profitable Crisis Strategies
# ============================================================

def score_swing_short(closes, highs, lows, opens, volumes, current_price, **kw):
    """M: Swing Short — 大波段做空, 宽SL(3xATR), 长TP(6xATR), 持有72根"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    tech_score = 50

    # Must have clear downtrend on multiple timeframes
    if trend_4h < 0 and trend_1h < 0:
        tech_score -= 15

    # SMC
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            if smc["score_adjustment"] < 0:
                tech_score += smc["score_adjustment"]
        except: pass

    # Price structure
    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows))) if recent_lows[i-1] < recent_lows[i])
    if ll_count >= 3: tech_score -= 5

    tech_score = max(0, min(100, tech_score))

    # Custom direction
    threshold = kw.get("score_threshold", 60)
    if tech_score <= (100 - threshold):
        direction = "bearish"
    else:
        direction = "neutral"

    # WIDE SL/TP for swing trades
    sl = round(current_price + atr_approx * 3.5, 2)  # 3.5x ATR SL
    tp = round(current_price - atr_approx * 7.0, 2)   # 7x ATR TP (2:1 R:R)

    return {
        "score": tech_score, "direction": direction, "breakdown": [],
        "atr": atr_approx, "sl": sl, "tp": tp,
        "rr_ratio": 2.0, "leverage": 1,
        "rsi": calc_rsi(closes), "adx": adx,
        "market_regime": "trending" if adx >= 25 else "ranging",
        "trend_4h": trend_4h, "trend_1h": trend_1h,
        "price_structure": "bearish_structure" if ll_count >= 3 else "no_structure",
    }


def score_momentum_cascade(closes, highs, lows, opens, volumes, current_price, **kw):
    """N: Momentum Cascade — 连续3根阴线+价格在EMA下方才做空"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    tech_score = 50

    # Check for 3 consecutive bearish candles
    if len(closes) >= 4:
        candle1_bearish = closes[-1] < opens[-1]
        candle2_bearish = closes[-2] < opens[-2]
        candle3_bearish = closes[-3] < opens[-3]
        three_bears = candle1_bearish and candle2_bearish and candle3_bearish

        # Momentum: each candle body is significant (>0.5% of price)
        body1 = abs(closes[-1] - opens[-1]) / current_price * 100
        body2 = abs(closes[-2] - opens[-2]) / current_price * 100
        body3 = abs(closes[-3] - opens[-3]) / current_price * 100
        strong_bodies = body1 > 0.3 and body2 > 0.3 and body3 > 0.3
    else:
        three_bears = False
        strong_bodies = False

    ema21 = calc_ema(closes[-30:], 21) if len(closes) >= 21 else current_price

    if three_bears and strong_bodies and current_price < ema21:
        tech_score -= 15
        # SMC confirmation
        if _analyze_smc:
            try:
                smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
                if smc["score_adjustment"] < 0:
                    tech_score += smc["score_adjustment"]
            except: pass

    # Force short-only
    tech_score = max(0, min(100, tech_score))
    threshold = kw.get("score_threshold", 60)
    if tech_score <= (100 - threshold):
        direction = "bearish"
    else:
        direction = "neutral"

    # Moderate SL/TP
    sl = round(current_price + atr_approx * 2.5, 2)
    tp = round(current_price - atr_approx * 5.0, 2)

    return {
        "score": tech_score, "direction": direction, "breakdown": [],
        "atr": atr_approx, "sl": sl, "tp": tp,
        "rr_ratio": 2.0, "leverage": 1,
        "rsi": calc_rsi(closes), "adx": adx,
        "market_regime": "trending" if adx >= 25 else "ranging",
        "trend_4h": trend_4h, "trend_1h": trend_1h,
        "price_structure": "no_structure",
    }


def score_wide_stop_short(closes, highs, lows, opens, volumes, current_price, **kw):
    """O: Wide-Stop Short — Short-only with 4x ATR SL to survive bounces"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    tech_score = 50

    # Trend
    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    if (trend_15m == trend_1h == trend_4h) and trend_15m != 0:
        trend_score = int(trend_score * 1.2)
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score

    # Price structure
    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows))) if recent_lows[i-1] < recent_lows[i])
    if ll_count >= 3: tech_score -= 5

    # EMA bearish cross
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        if ema8 < ema21: tech_score -= 3

    # SMC
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            if smc["score_adjustment"] < 0:
                tech_score += smc["score_adjustment"]
        except: pass

    tech_score = max(0, min(100, tech_score))

    threshold = kw.get("score_threshold", 60)
    if tech_score <= (100 - threshold):
        direction = "bearish"
    else:
        direction = "neutral"

    # Key: Very wide SL (4x ATR) and moderate TP (5x ATR)
    sl = round(current_price + atr_approx * 4.0, 2)
    tp = round(current_price - atr_approx * 5.0, 2)

    return {
        "score": tech_score, "direction": direction, "breakdown": [],
        "atr": atr_approx, "sl": sl, "tp": tp,
        "rr_ratio": 1.25, "leverage": 1,
        "rsi": calc_rsi(closes), "adx": adx,
        "market_regime": "trending" if adx >= 25 else "ranging",
        "trend_4h": trend_4h, "trend_1h": trend_1h,
        "price_structure": "bearish_structure" if ll_count >= 3 else "no_structure",
    }


def score_selective_short(closes, highs, lows, opens, volumes, current_price, **kw):
    """P: Selective Short — 只在RSI反弹到40-60时做空(不追空), 宽SL"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    rsi = calc_rsi(closes)

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    tech_score = 50

    # Must be in 4H downtrend
    if trend_4h >= 0:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": atr_approx,
                "sl": current_price, "tp": current_price, "rr_ratio": 0, "leverage": 1,
                "rsi": rsi, "adx": adx, "market_regime": "ranging",
                "trend_4h": trend_4h, "trend_1h": trend_1h, "price_structure": "no_structure"}

    # Key condition: wait for RSI to bounce from oversold back to 40-60 range
    # This means the bounce has played out and momentum is fading
    if 35 <= rsi <= 55:
        tech_score -= 15

        # Price near or above EMA21 = even better
        ema21 = calc_ema(closes[-30:], 21) if len(closes) >= 21 else current_price
        if current_price >= ema21 * 0.98:
            tech_score -= 5

        # SMC confirmation
        if _analyze_smc:
            try:
                smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
                if smc["score_adjustment"] < 0:
                    tech_score += smc["score_adjustment"]
            except: pass
    elif rsi < 25:
        # Don't short when already oversold — wait for bounce first
        pass

    tech_score = max(0, min(100, tech_score))

    threshold = kw.get("score_threshold", 60)
    if tech_score <= (100 - threshold):
        direction = "bearish"
    else:
        direction = "neutral"

    # Wide SL to survive bounces
    sl = round(current_price + atr_approx * 3.5, 2)
    tp = round(current_price - atr_approx * 5.5, 2)

    return {
        "score": tech_score, "direction": direction, "breakdown": [],
        "atr": atr_approx, "sl": sl, "tp": tp,
        "rr_ratio": 1.57, "leverage": 1,
        "rsi": rsi, "adx": adx,
        "market_regime": "trending" if adx >= 25 else "ranging",
        "trend_4h": trend_4h, "trend_1h": trend_1h,
        "price_structure": "no_structure",
    }


def score_micro_short(closes, highs, lows, opens, volumes, current_price, **kw):
    """Q: Micro-Position Short — Trend+SMC short-only, 小仓位(0.5%风险)"""
    # Same logic as Short-Only H, but position sizing handled externally
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    tech_score = 50

    # Trend
    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    if (trend_15m == trend_1h == trend_4h) and trend_15m != 0:
        trend_score = int(trend_score * 1.2)
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score

    # Structure
    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows))) if recent_lows[i-1] < recent_lows[i])
    if ll_count >= 3: tech_score -= 5

    # EMA
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        if ema8 < ema21: tech_score -= 3

    # SMC
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            if smc["score_adjustment"] < 0:
                tech_score += smc["score_adjustment"]
        except: pass

    tech_score = max(0, min(100, tech_score))

    threshold = kw.get("score_threshold", 60)
    if tech_score <= (100 - threshold):
        direction = "bearish"
    else:
        direction = "neutral"

    # Force no bullish
    if tech_score >= threshold:
        direction = "neutral"

    # Standard SL/TP but small position
    sl = round(current_price + atr_approx * 2.5, 2)
    tp = round(current_price - atr_approx * 5.0, 2)

    return {
        "score": tech_score, "direction": direction, "breakdown": [],
        "atr": atr_approx, "sl": sl, "tp": tp,
        "rr_ratio": 2.0, "leverage": 1,
        "rsi": calc_rsi(closes), "adx": adx,
        "market_regime": "trending" if adx >= 25 else "ranging",
        "trend_4h": trend_4h, "trend_1h": trend_1h,
        "price_structure": "bearish_structure" if ll_count >= 3 else "no_structure",
    }


# ============================================================
# Main Runner
# ============================================================

async def run_profit_research():
    fetcher = OKXDataFetcher()
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    days = 30

    # Define all experiments with (label, score_fn, threshold, risk_pct, max_hold)
    experiments = [
        # Baselines
        ("C: Trend+SMC baseline", score_group_c, 60, 2.0, None),
        # New strategies
        ("M: Swing Short (宽SL 长持有)", score_swing_short, 60, 1.5, 72),
        ("N: Momentum Cascade", score_momentum_cascade, 60, 1.5, 48),
        ("O: Wide-Stop Short (4xATR)", score_wide_stop_short, 60, 1.5, 48),
        ("P: Selective Short (RSI等反弹)", score_selective_short, 55, 1.5, 48),
        ("Q: Micro-Position (0.5%风险)", score_micro_short, 60, 0.5, 36),
        # Variations of P with different thresholds
        ("P2: Selective @50", score_selective_short, 50, 1.5, 48),
        ("P3: Selective @55 0.8%risk", score_selective_short, 55, 0.8, 48),
    ]

    all_results = {}
    lines = []
    lines.append("=" * 110)
    lines.append("CRISIS PROFITABILITY RESEARCH — 30天 BTC/ETH/SOL (OKX)")
    lines.append("=" * 110)

    for symbol in symbols:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        start_ms = int(start.timestamp() * 1000)

        logger.info(f"\n{'='*60}")
        logger.info(f"🔬 {symbol} — 30天盈利研究")
        logger.info(f"{'='*60}")

        data = await fetcher.fetch_all(symbol, start, end, days)
        klines = data["klines"]

        if len(klines) < 100:
            logger.error(f"K线不足: {len(klines)}")
            continue

        # Price stats
        prices = [k["close"] for k in klines]
        start_price = prices[50]
        end_price = prices[-1]
        price_change = (end_price / start_price - 1) * 100
        logger.info(f"  价格: ${start_price:,.0f} → ${end_price:,.0f} ({price_change:+.1f}%)")

        results = []
        for label, score_fn, threshold, risk_pct, max_hold in experiments:
            r = simulate_trades_v2(klines, score_fn, data, start_ms,
                                   risk_pct=risk_pct, score_threshold=threshold,
                                   label=label, max_hold_override=max_hold)
            results.append(r)
            marker = " ✅" if r["total_pnl"] > 0 else ""
            logger.info(f"    {label}: {r['trades']}T {r['win_rate']}%WR "
                       f"${r['total_pnl']:+.0f} PF={r['profit_factor']:.2f}{marker}")

        all_results[symbol] = results

        lines.append(f"\n{'='*90}")
        lines.append(f"  {symbol} (30d) | Price: ${start_price:,.0f} -> ${end_price:,.0f} ({price_change:+.1f}%)")
        lines.append(f"{'='*90}")
        lines.append(f"  {'Group':<35} {'T':>3} {'WR%':>5} {'PnL$':>9} {'PnL%':>7} {'PF':>5} {'DD%':>5} {'AvgW':>7} {'AvgL':>7}")
        lines.append(f"  {'-'*90}")
        for r in results:
            marker = " ★" if r["total_pnl"] > 0 else ""
            lines.append(f"  {r['label']:<35} {r['trades']:>3} {r['win_rate']:>4.1f}% "
                        f"{r['total_pnl']:>+8.0f} {r['total_pnl_pct']:>+6.1f}% "
                        f"{r['profit_factor']:>4.2f} {r['max_drawdown_pct']:>4.1f}% "
                        f"{r['avg_win']:>+6.0f} {r['avg_loss']:>+6.0f}{marker}")

        await asyncio.sleep(1)

    # Cross-symbol ranking
    lines.append(f"\n{'='*90}")
    lines.append("CROSS-SYMBOL RANKING (avg PnL%)")
    lines.append(f"{'='*90}")
    group_totals = {}
    for label, _, _, _, _ in experiments:
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

    os.makedirs("data", exist_ok=True)
    save_data = {
        "timestamp": datetime.now().isoformat(),
        "type": "crisis_profitability_research",
        "results": {},
    }
    for symbol in symbols:
        save_data["results"][symbol] = [
            {k: v for k, v in r.items() if k != "trade_details"} for r in all_results.get(symbol, [])
        ]
    with open("data/backtest_crisis_profit.json", "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    with open("data/backtest_crisis_profit_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"\n💾 data/backtest_crisis_profit.json + report.txt")


if __name__ == "__main__":
    asyncio.run(run_profit_research())
