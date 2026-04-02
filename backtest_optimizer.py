# -*- coding: utf-8 -*-
"""
Strategy Optimizer — Diagnostic + Multi-variant Backtest
Step 1: Run diagnostic to find winning indicator patterns
Step 2: Test multiple parameter combos to find optimal
"""
import asyncio, sys, os, json, time, math
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field

sys.path.insert(0, r"D:\All_in_AI\Trading_system")

from backend.archive.trading.backtester_v2 import (
    HistoricalDataFetcher, score_bar, _SortedLookup,
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

INITIAL_BALANCE = 1000.0

# ═══════════════════════════════════════════════════
#  Optimized Strategy Variants to Test
# ═══════════════════════════════════════════════════

VARIANTS = {
    "Original": {
        "threshold": 62,
        "max_leverage": 5,
        "cooldown_bars": 12,       # 3h on 15m
        "max_hold": 144,           # 36h
        "risk_pct": 2.0,
        "trailing_stop": True,
        "portfolio_dd_limit": 100, # no limit
        "require_4h_align": False,
        "adx_min": 0,             # no filter 
        "min_rr": 0,              # handled inside score_bar
        "eval_interval": 4,       # every hour
    },
    "V2_Conservative": {
        "threshold": 70,           # 更高阈值,只在强信号入场
        "max_leverage": 2,         # 降杠杆
        "cooldown_bars": 32,       # 8h冷却
        "max_hold": 96,            # 24h最长持仓
        "risk_pct": 1.5,           # 降风险
        "trailing_stop": True,
        "portfolio_dd_limit": 20,  # 回撤>20%暂停
        "require_4h_align": True,  # 必须4H方向一致
        "adx_min": 20,            # ADX>20才交易（有趋势）
        "min_rr": 1.8,            # 盈亏比>1.8
        "eval_interval": 8,       # 每2h评估
    },
    "V3_TrendFollow": {
        "threshold": 65,
        "max_leverage": 2,
        "cooldown_bars": 24,       # 6h
        "max_hold": 192,           # 48h (let winners run)
        "risk_pct": 1.0,           # 更低风险
        "trailing_stop": True,
        "portfolio_dd_limit": 15,  # 严格回撤控制
        "require_4h_align": True,
        "adx_min": 25,            # 强趋势
        "min_rr": 2.0,
        "eval_interval": 8,
    },
    "V4_HighWinRate": {
        "threshold": 75,           # 极高阈值
        "max_leverage": 1,         # 1x不加杠杆
        "cooldown_bars": 48,       # 12h
        "max_hold": 72,            # 18h
        "risk_pct": 2.0,
        "trailing_stop": True,
        "portfolio_dd_limit": 10,  # 超严格：10%停
        "require_4h_align": True,
        "adx_min": 25,
        "min_rr": 2.5,
        "eval_interval": 16,      # 每4h
    },
    "V5_Adaptive": {
        "threshold": 68,
        "max_leverage": 3,         # dynamic
        "cooldown_bars": 16,       # 4h
        "max_hold": 144,
        "risk_pct": 1.5,
        "trailing_stop": True,
        "portfolio_dd_limit": 25,
        "require_4h_align": False, # allow but penalize
        "adx_min": 15,
        "min_rr": 1.5,
        "eval_interval": 4,
        # Special: adaptive leverage based on recent performance
        "adaptive_leverage": True,
    },
}


def calc_pnl(side, entry, exit_price, amount, leverage=1):
    if side == "buy":
        return (exit_price - entry) / entry * amount * leverage
    else:
        return (entry - exit_price) / entry * amount * leverage


async def run_variant(
    variant_name, params, symbol, klines,
    fr_lookup, ls_lookup, oi_lookup,
    ca_liq_lookup, ca_oi_mc_lookup, ca_net_lookup,
    fng_history, start_ms, period_days,
):
    balance = INITIAL_BALANCE
    peak_balance = INITIAL_BALANCE
    position = None
    trades = []
    last_trade_idx = -999
    consecutive_losses = 0
    recent_pnls = []  # for adaptive leverage
    paused_until_idx = -1

    closes, highs, lows, opens, volumes = [], [], [], [], []

    threshold = params["threshold"]
    max_lev = params["max_leverage"]
    cooldown = params["cooldown_bars"]
    max_hold = params["max_hold"]
    risk_pct = params["risk_pct"]
    trailing = params["trailing_stop"]
    dd_limit = params["portfolio_dd_limit"]
    require_4h = params["require_4h_align"]
    adx_min = params["adx_min"]
    min_rr = params["min_rr"]
    eval_interval = params["eval_interval"]
    adaptive = params.get("adaptive_leverage", False)

    for idx, k in enumerate(klines):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])

        if len(closes) < 100 or k["ts"] < start_ms:
            continue

        ts = k["ts"]
        price = k["close"]
        high = k["high"]
        low = k["low"]

        # --- Portfolio drawdown check ---
        current_dd = (peak_balance - balance) / peak_balance * 100 if peak_balance > 0 else 0
        if current_dd >= dd_limit and not position:
            if idx < paused_until_idx:
                continue
            # Pause for 96 bars after hitting DD limit (24h)
            paused_until_idx = idx + 96
            continue

        # --- Check position ---
        if position:
            sl_hit = (position["side"] == "buy" and low <= position["sl"]) or \
                     (position["side"] == "sell" and high >= position["sl"])
            tp_hit = (position["side"] == "buy" and high >= position["tp"]) or \
                     (position["side"] == "sell" and low <= position["tp"])
            bars_held = idx - position["opened_idx"]

            if bars_held >= max_hold and not tp_hit:
                pnl = calc_pnl(position["side"], position["entry"], price,
                               position["amount"], position["leverage"])
                balance += pnl
                trades.append({"pnl": pnl, "reason": "timeout", "score": position.get("score",0),
                               "leverage": position["leverage"], "bars": bars_held})
                position = None
                last_trade_idx = idx
                recent_pnls.append(pnl)
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0

            elif sl_hit or tp_hit:
                exit_p = position["sl"] if sl_hit else position["tp"]
                pnl = calc_pnl(position["side"], position["entry"], exit_p,
                               position["amount"], position["leverage"])
                balance += pnl
                trades.append({"pnl": pnl, "reason": "sl" if sl_hit else "tp",
                               "score": position.get("score",0),
                               "leverage": position["leverage"], "bars": bars_held})
                position = None
                last_trade_idx = idx
                recent_pnls.append(pnl)
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
            else:
                # Trailing stop
                if trailing:
                    if position["side"] == "buy":
                        dist = abs(position["tp"] - position["entry"])
                        if price >= position["entry"] + dist * 0.4:
                            new_sl = max(position["sl"], position["entry"] + dist * 0.15)
                            position["sl"] = round(new_sl, 2)
                    else:
                        dist = abs(position["entry"] - position["tp"])
                        if price <= position["entry"] - dist * 0.4:
                            new_sl = min(position["sl"], position["entry"] - dist * 0.15)
                            position["sl"] = round(new_sl, 2)

        peak_balance = max(peak_balance, balance)

        # Eval interval
        if idx % eval_interval != 0:
            continue
        if idx - last_trade_idx < cooldown:
            continue
        if consecutive_losses >= 3:
            consecutive_losses = 0
            continue
        if position:
            continue
        if balance <= 10:  # Bankrupt
            continue

        # Score
        fr_val = fr_lookup.find(ts)
        ls_val = ls_lookup.find(ts)
        oi_curr = oi_lookup.find(ts)
        oi_prev = oi_lookup.find(ts - 3600000)

        fng_value = 50
        if fng_history:
            day_key = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            fng_value = fng_history.get(day_key, 50)

        ca_liq_long, ca_liq_short = 0, 0
        ca_oi_mc_val, ca_net_val = None, None
        if ca_liq_lookup:
            liq = ca_liq_lookup.find(ts)
            if liq and isinstance(liq, dict):
                ca_liq_long = liq.get("longTurnover", 0)
                ca_liq_short = liq.get("shortTurnover", 0)
        if ca_oi_mc_lookup:
            ca_oi_mc_val = ca_oi_mc_lookup.find(ts)
        if ca_net_lookup:
            ca_net_val = ca_net_lookup.find(ts)

        sig = score_bar(
            closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
            current_price=price,
            funding_rate=fr_val, ls_ratio=ls_val,
            oi_current=oi_curr, oi_prev=oi_prev,
            fng_value=fng_value,
            score_threshold=threshold,
            ca_liq_long=ca_liq_long, ca_liq_short=ca_liq_short,
            ca_oi_mc=ca_oi_mc_val, ca_net=ca_net_val,
        )

        direction = sig.get("direction", "neutral")
        score = sig.get("score", 50)
        adx = sig.get("adx", 20)
        rr = sig.get("rr_ratio", 0)
        trend_4h = sig.get("trend_4h", 0)

        if direction == "neutral":
            continue

        # --- Extra filters ---
        # ADX filter
        if adx < adx_min:
            continue

        # 4H alignment filter 
        if require_4h:
            if direction == "bullish" and trend_4h < 0:
                continue
            if direction == "bearish" and trend_4h > 0:
                continue

        # R:R filter
        if min_rr > 0 and rr < min_rr:
            continue

        # --- Position sizing ---
        trade_side = "buy" if direction == "bullish" else "sell"
        lev = min(sig.get("leverage", 2), max_lev)

        # Adaptive leverage: reduce after recent losses
        if adaptive and len(recent_pnls) >= 3:
            recent_3 = recent_pnls[-3:]
            losses_in_3 = sum(1 for p in recent_3 if p <= 0)
            if losses_in_3 >= 2:
                lev = max(1, lev - 1)

        sl_price = sig.get("sl", price * (0.97 if trade_side == "buy" else 1.03))
        tp_price = sig.get("tp", price * (1.06 if trade_side == "buy" else 0.94))

        risk_amount = balance * risk_pct / 100
        sl_dist = abs(price - sl_price)
        if sl_dist <= 0:
            continue
        pos_value = risk_amount / (sl_dist / price) * lev
        pos_amount = min(pos_value, balance * lev)

        position = {
            "side": trade_side, "entry": price,
            "amount": pos_amount, "sl": sl_price, "tp": tp_price,
            "leverage": lev, "opened_idx": idx, "score": score,
        }
        last_trade_idx = idx

    # Close remaining
    if position:
        pnl = calc_pnl(position["side"], position["entry"], closes[-1],
                        position["amount"], position["leverage"])
        balance += pnl
        trades.append({"pnl": pnl, "reason": "end", "score": position.get("score",0),
                       "leverage": position["leverage"],
                       "bars": len(klines)-1-position["opened_idx"]})

    # Stats
    wins = [t for t in trades if t["pnl"] > 0]
    losses_list = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / len(trades) * 100 if trades else 0
    pf = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses_list)) if losses_list and sum(t["pnl"] for t in losses_list) != 0 else 999
    max_dd = (peak_balance - min(balance, peak_balance)) / peak_balance * 100 if peak_balance > 0 else 0

    # Sharpe
    sharpe = 0
    if len(trades) >= 3:
        rets = [t["pnl"] / INITIAL_BALANCE * 100 for t in trades]
        mean_r = sum(rets) / len(rets)
        std_r = (sum((r - mean_r) ** 2 for r in rets) / len(rets)) ** 0.5
        if std_r > 0:
            tpy = 365 / period_days * len(trades)
            sharpe = round(mean_r / std_r * math.sqrt(tpy), 2)

    return {
        "variant": variant_name,
        "symbol": symbol,
        "days": period_days,
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": round(wr, 1),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(total_pnl / INITIAL_BALANCE * 100, 1),
        "max_dd": round(max_dd, 1),
        "profit_factor": round(pf, 2),
        "sharpe": sharpe,
        "final_balance": round(balance, 2),
        "avg_lev": round(sum(t["leverage"] for t in trades) / len(trades), 1) if trades else 0,
        "avg_bars": round(sum(t["bars"] for t in trades) / len(trades), 1) if trades else 0,
    }


# CoinAnk lookup
class DictSortedLookup:
    def __init__(self, data_dict):
        import bisect
        self.keys = sorted(data_dict.keys())
        self.data = data_dict
    def find(self, target_ts, tolerance_ms=4*3600*1000):
        import bisect
        if not self.keys: return None
        idx = bisect.bisect_left(self.keys, target_ts)
        candidates = []
        if idx < len(self.keys): candidates.append(self.keys[idx])
        if idx > 0: candidates.append(self.keys[idx - 1])
        if not candidates: return None
        best = min(candidates, key=lambda t: abs(t - target_ts))
        return self.data[best] if abs(best - target_ts) <= tolerance_ms else None


async def fetch_fng_history(days):
    import httpx
    fng = {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.alternative.me/fng/?limit={days + 5}")
            if r.status_code == 200:
                for d in r.json().get("data", []):
                    ts = int(d["timestamp"])
                    fng[datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")] = int(d["value"])
    except: pass
    return fng


async def main():
    fetcher = HistoricalDataFetcher()
    end = datetime.utcnow()
    all_results = []

    print("╔" + "═" * 78 + "╗")
    print("║  STRATEGY OPTIMIZER — Testing 5 Variants × 3 Coins × 2 Periods          ║")
    print("║  Original vs Conservative vs TrendFollow vs HighWinRate vs Adaptive      ║")
    print("╚" + "═" * 78 + "╝")

    fng_history = await fetch_fng_history(95)
    print(f"  FNG: {len(fng_history)} days")

    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    PERIODS = [30, 90]

    for days in PERIODS:
        start = end - timedelta(days=days)
        print(f"\n{'━' * 78}")
        print(f"  📅 {days}d: {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")
        print(f"{'━' * 78}")

        for symbol in SYMBOLS:
            print(f"\n  📈 {symbol}")
            t0 = time.time()

            lookback_start = start - timedelta(days=15)
            start_ms = int(start.timestamp() * 1000)

            try:
                print("    ⏳ Data...", end=" ", flush=True)
                klines, fr, ls, oi = await asyncio.gather(
                    fetcher.fetch_klines(symbol, "15m", lookback_start, end),
                    fetcher.fetch_funding_rate(symbol, start, end),
                    fetcher.fetch_long_short_ratio(symbol, start, end),
                    fetcher.fetch_oi_history(symbol, start, end),
                )
                try:
                    ca_liq, ca_oi_mc, ca_net = await asyncio.gather(
                        fetcher.fetch_coinank_liq_history(symbol, start, end),
                        fetcher.fetch_coinank_oi_mc(symbol, start, end),
                        fetcher.fetch_coinank_net_positions(symbol, start, end),
                    )
                except: ca_liq, ca_oi_mc, ca_net = {}, {}, {}

                print(f"{len(klines)}K | ", end="", flush=True)

                if len(klines) < 200:
                    print("SKIP")
                    continue

                fr_l = _SortedLookup(fr)
                ls_l = _SortedLookup(ls)
                oi_l = _SortedLookup(oi)
                ca_liq_l = DictSortedLookup(ca_liq)
                ca_oi_mc_l = _SortedLookup(ca_oi_mc) if ca_oi_mc else None
                ca_net_l = _SortedLookup(ca_net) if ca_net else None

                for vname, vparams in VARIANTS.items():
                    r = await run_variant(
                        vname, vparams, symbol, klines,
                        fr_l, ls_l, oi_l,
                        ca_liq_l, ca_oi_mc_l, ca_net_l,
                        fng_history, start_ms, days,
                    )
                    all_results.append(r)
                    icon = "🟢" if r["total_pnl"] >= 0 else "🔴"
                    print(f"{icon}{vname[:6]}:{r['roi_pct']:+.0f}% ", end="", flush=True)

                elapsed = time.time() - t0
                print(f"| {elapsed:.0f}s")

            except Exception as e:
                print(f"ERROR: {e}")
                import traceback; traceback.print_exc()

            await asyncio.sleep(0.5)

    # ═══ FULL TABLE ═══
    print(f"\n\n{'═' * 110}")
    print(f"  FULL RESULTS")
    print(f"{'═' * 110}")
    print(f"{'Variant':16s} {'Sym':6s} {'D':3s} {'#T':>4s} {'WR%':>6s} {'PnL$':>9s} {'ROI%':>7s} {'DD%':>6s} {'PF':>6s} {'Sharpe':>7s} {'Lev':>5s} {'Hold':>5s}")
    print("-" * 110)

    for r in sorted(all_results, key=lambda x: (x["days"], x["symbol"], x["variant"])):
        pm = "+" if r["total_pnl"] >= 0 else ""
        print(f"{r['variant']:16s} {r['symbol']:8s} {r['days']:3d} {r['trades']:4d} "
              f"{r['win_rate']:5.1f}% {pm}{r['total_pnl']:>8.2f} "
              f"{pm}{r['roi_pct']:>6.1f}% {r['max_dd']:5.1f}% "
              f"{r['profit_factor']:6.2f} {r['sharpe']:7.2f} "
              f"{r['avg_lev']:4.1f}x {r['avg_bars']:4.0f}b")

    # ═══ AGGREGATE BY VARIANT ═══
    print(f"\n{'═' * 90}")
    print(f"  VARIANT RANKING (averaged across all coins & periods)")
    print(f"{'═' * 90}")
    print(f"{'Rank':>4s} {'Variant':16s} {'AvgROI%':>8s} {'AvgWR%':>7s} {'AvgDD%':>7s} {'AvgPF':>6s} {'AvgSharpe':>10s} {'TotalT':>7s}")
    print("-" * 90)

    agg = {}
    for r in all_results:
        v = r["variant"]
        if v not in agg:
            agg[v] = []
        agg[v].append(r)

    ranked = sorted(agg.items(), key=lambda x: sum(r["roi_pct"] for r in x[1]) / len(x[1]), reverse=True)

    for rank, (vname, runs) in enumerate(ranked, 1):
        avg_roi = sum(r["roi_pct"] for r in runs) / len(runs)
        avg_wr = sum(r["win_rate"] for r in runs) / len(runs)
        avg_dd = sum(r["max_dd"] for r in runs) / len(runs)
        avg_pf = sum(r["profit_factor"] for r in runs) / len(runs)
        avg_sharpe = sum(r["sharpe"] for r in runs) / len(runs)
        total_t = sum(r["trades"] for r in runs)
        pm = "+" if avg_roi >= 0 else ""
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "  "
        print(f"{medal}{rank:2d} {vname:16s} {pm}{avg_roi:>7.1f}% {avg_wr:>6.1f}% {avg_dd:>6.1f}% "
              f"{avg_pf:>6.2f} {avg_sharpe:>9.2f} {total_t:>7d}")

    # Save
    os.makedirs(r"D:\All_in_AI\Trading_system\data", exist_ok=True)
    save_path = r"D:\All_in_AI\Trading_system\data\optimizer_results.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({"results": all_results, "variants": {k: v for k, v in VARIANTS.items()}}, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 Saved to {save_path}")
    print(f"\n{'═' * 90}\n  OPTIMIZATION COMPLETE\n{'═' * 90}")


if __name__ == "__main__":
    asyncio.run(main())
