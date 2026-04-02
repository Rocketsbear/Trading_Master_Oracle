"""
Crisis Strategy Parameter Optimization — 暴力参数搜索

基于 N (Momentum Cascade) 和 M (Swing Short) 的优化:
- SL: 2x, 3x, 4x, 5x ATR
- TP: 5x, 7x, 10x, 15x ATR  
- risk: 1%, 1.5%, 2%, 3%
- leverage: 1x, 2x
- max_hold: 48, 72, 120 bars
- 增加额外过滤器组合
"""
import asyncio, json, os, itertools
from datetime import datetime, timedelta, timezone
from loguru import logger

from backend.trading.indicator_subset_backtest import (
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from backend.trading.indicator_subset_backtest_v2 import OKXDataFetcher
from backend.trading.crisis_profit_research import simulate_trades_v2
from backend.trading.backtester_v2 import _SortedLookup

try:
    from backend.analysis.smart_money import analyze_smc as _analyze_smc
except Exception:
    _analyze_smc = None


def make_crisis_scorer(sl_mult, tp_mult, lev, entry_mode="cascade", require_ema50=False):
    """Factory: create a scoring function with given SL/TP/Lev params"""

    def score_fn(closes, highs, lows, opens, volumes, current_price, **kw):
        if len(closes) < 50:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        adx = calc_adx(highs, lows, closes)
        atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

        trend_15m = trend_direction(closes, 20, 50)
        closes_4h = closes[::4] if len(closes) >= 200 else closes
        trend_1h = trend_direction(closes, 20, 50)
        trend_4h = trend_direction(closes_4h, 20, 50)

        tech_score = 50
        direction = "neutral"

        # ========== ENTRY MODE ==========
        if entry_mode == "cascade":
            # N-style: 3 consecutive bearish candles + below EMA21
            if len(closes) >= 4:
                c1 = closes[-1] < opens[-1]
                c2 = closes[-2] < opens[-2]
                c3 = closes[-3] < opens[-3]
                b1 = abs(closes[-1] - opens[-1]) / current_price * 100
                b2 = abs(closes[-2] - opens[-2]) / current_price * 100
                b3 = abs(closes[-3] - opens[-3]) / current_price * 100
                three_bears = c1 and c2 and c3 and b1 > 0.3 and b2 > 0.3 and b3 > 0.3
            else:
                three_bears = False

            ema21 = calc_ema(closes[-30:], 21) if len(closes) >= 21 else current_price

            if three_bears and current_price < ema21:
                tech_score -= 15

                # Optional EMA50 filter
                if require_ema50 and len(closes) >= 60:
                    ema50 = calc_ema(closes[-60:], 50)
                    if current_price >= ema50:
                        tech_score = 50  # Cancel — price above EMA50

                # SMC
                if _analyze_smc and tech_score < 50:
                    try:
                        smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
                        if smc["score_adjustment"] < 0:
                            tech_score += smc["score_adjustment"]
                    except:
                        pass

        elif entry_mode == "swing":
            # M-style: clear 4H downtrend + SMC
            if trend_4h < 0 and trend_1h < 0:
                tech_score -= 15

            swing_lookback = min(60, len(closes))
            recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
            ll_count = sum(1 for i in range(1, min(5, len(recent_lows)))
                          if recent_lows[i - 1] < recent_lows[i])
            if ll_count >= 3:
                tech_score -= 5

            if _analyze_smc and tech_score < 50:
                try:
                    smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
                    if smc["score_adjustment"] < 0:
                        tech_score += smc["score_adjustment"]
                except:
                    pass

        elif entry_mode == "combined":
            # Combined: trend + cascade + SMC
            ema21 = calc_ema(closes[-30:], 21) if len(closes) >= 21 else current_price

            # Condition 1: 4H downtrend
            is_downtrend = trend_4h < 0

            # Condition 2: 2+ consecutive bearish candles
            if len(closes) >= 3:
                two_bears = closes[-1] < opens[-1] and closes[-2] < opens[-2]
            else:
                two_bears = False

            # Condition 3: price below EMA21
            below_ema = current_price < ema21

            if is_downtrend and two_bears and below_ema:
                tech_score -= 15

                # SMC boost
                if _analyze_smc:
                    try:
                        smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
                        if smc["score_adjustment"] < 0:
                            tech_score += smc["score_adjustment"]
                    except:
                        pass

                # LL structure boost
                swing_lookback = min(60, len(closes))
                recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
                ll_count = sum(1 for i in range(1, min(5, len(recent_lows)))
                              if recent_lows[i - 1] < recent_lows[i])
                if ll_count >= 3:
                    tech_score -= 5

        tech_score = max(0, min(100, tech_score))

        threshold = kw.get("score_threshold", 60)
        if tech_score <= (100 - threshold):
            direction = "bearish"
        else:
            direction = "neutral"

        # Custom SL/TP
        sl = round(current_price + atr_approx * sl_mult, 2)
        tp = round(current_price - atr_approx * tp_mult, 2)

        return {
            "score": tech_score, "direction": direction, "breakdown": [],
            "atr": atr_approx, "sl": sl, "tp": tp,
            "rr_ratio": round(tp_mult / sl_mult, 2), "leverage": lev,
            "rsi": calc_rsi(closes), "adx": adx,
            "market_regime": "trending" if adx >= 25 else "ranging",
            "trend_4h": trend_4h, "trend_1h": trend_1h,
            "price_structure": "no_structure",
        }

    return score_fn


async def run_optimization():
    fetcher = OKXDataFetcher()
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    days = 30

    # Fetch data once for all symbols
    all_data = {}
    for symbol in symbols:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        data = await fetcher.fetch_all(symbol, start, end, days)
        all_data[symbol] = (data, int(start.timestamp() * 1000))
        await asyncio.sleep(0.5)

    # Parameter grid
    configs = [
        # entry_mode, sl_mult, tp_mult, lev, risk_pct, max_hold, require_ema50
        # --- Cascade variants ---
        ("cascade", 2.5, 5.0, 1, 1.5, 48, False),     # N baseline
        ("cascade", 3.0, 8.0, 1, 1.5, 72, False),      # Wider TP
        ("cascade", 3.0, 10.0, 1, 1.5, 96, False),     # Very wide TP, long hold
        ("cascade", 3.0, 8.0, 2, 1.5, 72, False),      # 2x lev
        ("cascade", 3.0, 8.0, 2, 2.0, 72, False),      # 2x lev + 2% risk
        ("cascade", 3.5, 10.0, 2, 2.0, 96, False),     # Aggressive
        ("cascade", 4.0, 12.0, 2, 2.0, 120, False),    # Very aggressive
        ("cascade", 3.0, 8.0, 1, 2.0, 72, True),       # With EMA50 filter
        ("cascade", 3.0, 10.0, 2, 2.5, 96, False),     # High risk
        # --- Swing variants ---
        ("swing", 3.5, 7.0, 1, 1.5, 72, False),        # M baseline
        ("swing", 4.0, 10.0, 1, 1.5, 96, False),       # Wider
        ("swing", 4.0, 10.0, 2, 2.0, 96, False),       # 2x lev
        ("swing", 5.0, 12.0, 2, 2.0, 120, False),      # Very wide
        ("swing", 4.0, 10.0, 2, 2.5, 120, False),      # High risk + long hold
        # --- Combined (new) ---
        ("combined", 3.0, 8.0, 1, 1.5, 72, False),
        ("combined", 3.0, 8.0, 2, 2.0, 72, False),
        ("combined", 3.5, 10.0, 2, 2.0, 96, False),
        ("combined", 4.0, 12.0, 2, 2.5, 120, False),
        ("combined", 3.0, 10.0, 2, 3.0, 96, False),    # Very high risk
    ]

    results_all = []

    for i, (entry_mode, sl_m, tp_m, lev, risk, max_hold, ema50) in enumerate(configs):
        label = f"{entry_mode[0].upper()}{i:02d} SL{sl_m}x TP{tp_m}x L{lev} R{risk}% H{max_hold}"
        if ema50:
            label += " +EMA50"
        score_fn = make_crisis_scorer(sl_m, tp_m, lev, entry_mode, ema50)

        pnl_pcts = []
        per_symbol = {}
        for symbol in symbols:
            data, start_ms = all_data[symbol]
            klines = data["klines"]
            r = simulate_trades_v2(klines, score_fn, data, start_ms,
                                   risk_pct=risk, score_threshold=60,
                                   label=label, max_hold_override=max_hold)
            pnl_pcts.append(r["total_pnl_pct"])
            per_symbol[symbol] = {
                "trades": r["trades"], "wr": r["win_rate"],
                "pnl_pct": r["total_pnl_pct"], "pf": r["profit_factor"],
                "dd": r["max_drawdown_pct"],
            }

        avg_pnl = sum(pnl_pcts) / len(pnl_pcts)
        all_profit = all(p > 0 for p in pnl_pcts)
        results_all.append({
            "label": label, "avg_pnl_pct": round(avg_pnl, 2),
            "all_profit": all_profit, "per_symbol": per_symbol,
            "config": {"entry_mode": entry_mode, "sl": sl_m, "tp": tp_m,
                       "lev": lev, "risk": risk, "max_hold": max_hold, "ema50": ema50},
        })

    # Sort by avg PnL
    results_all.sort(key=lambda x: -x["avg_pnl_pct"])

    # Print
    lines = []
    lines.append("=" * 130)
    lines.append("CRISIS PARAMETER OPTIMIZATION — Top Results (sorted by avg PnL%)")
    lines.append("=" * 130)
    lines.append(f"  {'#':>2} {'Config':<45} {'Avg%':>6} {'BTC%':>6} {'BTC_WR':>6} {'ETH%':>6} {'ETH_WR':>6} {'SOL%':>6} {'SOL_WR':>6} {'AllP':>4}")
    lines.append(f"  {'-'*125}")

    for i, r in enumerate(results_all[:25]):  # Top 25
        btc = r["per_symbol"].get("BTCUSDT", {})
        eth = r["per_symbol"].get("ETHUSDT", {})
        sol = r["per_symbol"].get("SOLUSDT", {})
        marker = " ✅" if r["all_profit"] else (" ★" if r["avg_pnl_pct"] > 0 else "")
        lines.append(
            f"  {i + 1:>2} {r['label']:<45} {r['avg_pnl_pct']:>+5.1f}% "
            f"{btc.get('pnl_pct', 0):>+5.1f}% {btc.get('wr', 0):>5.1f}% "
            f"{eth.get('pnl_pct', 0):>+5.1f}% {eth.get('wr', 0):>5.1f}% "
            f"{sol.get('pnl_pct', 0):>+5.1f}% {sol.get('wr', 0):>5.1f}%{marker}")

    report = "\n".join(lines)
    print(report)

    os.makedirs("data", exist_ok=True)
    with open("data/crisis_optimization.json", "w", encoding="utf-8") as f:
        json.dump({"results": results_all}, f, ensure_ascii=False, indent=2)
    with open("data/crisis_optimization_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"\n💾 data/crisis_optimization.json + report.txt")
    logger.info(f"Top config: {results_all[0]['label']} → avg {results_all[0]['avg_pnl_pct']}%")


if __name__ == "__main__":
    asyncio.run(run_optimization())
