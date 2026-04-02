"""
News-Integrated Crisis Strategy — 新闻+技术指标组合

在冠军策略(Combined SL3 TP8 L2 R2% H72)基础上加入情绪指标:
  S1: +FNG动态仓位 (越恐惧→越大仓位做空)
  S2: +FNG动态杠杆 (FNG<15→3x杠杆, FNG<10→4x)
  S3: +资金费率确认 (负FR=空头已拥挤，减仓; 正FR=多头拥挤，加仓)
  S4: +多空比逆向 (LS>1.5=多头过多→强化做空)
  S5: 全组合 (FNG+FR+LS全部纳入)
  S6: FNG极端过滤 (FNG>30就不交易)
  S7: FNG分级+FR+LS完整版
"""
import asyncio, json, os
from datetime import datetime, timedelta, timezone
from loguru import logger

from backend.trading.indicator_subset_backtest import (
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from backend.trading.indicator_subset_backtest_v2 import OKXDataFetcher
from backend.trading.backtester_v2 import _SortedLookup

try:
    from backend.analysis.smart_money import analyze_smc as _analyze_smc
except Exception:
    _analyze_smc = None


def simulate_news_trades(klines, score_fn, data, start_ms, initial_balance=10000,
                         base_risk_pct=2.0, label="", max_hold=72):
    """Enhanced simulation with dynamic risk/leverage from scoring function"""
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

        # Check position
        if position:
            sl_hit = (position["side"] == "sell" and high >= position["sl"])
            tp_hit = (position["side"] == "sell" and low <= position["tp"])
            bars_held = idx - position["opened_idx"]

            if bars_held >= max_hold and not tp_hit:
                pnl = (position["entry"] - price) * position["amount"]
                balance += pnl
                trades.append({"side": "sell", "entry": position["entry"],
                               "exit": round(price, 2), "pnl": round(pnl, 2),
                               "reason": "max_hold", "bars": bars_held})
                position = None
                last_trade_close_idx = idx
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
            elif sl_hit or tp_hit:
                exit_p = position["sl"] if sl_hit else position["tp"]
                pnl = (position["entry"] - exit_p) * position["amount"]
                if tp_hit and not sl_hit:
                    partial = pnl * 0.6
                    balance += partial
                    trades.append({"side": "sell", "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(partial, 2),
                                   "reason": "partial_tp", "bars": bars_held})
                    position["amount"] *= 0.4
                    position["sl"] = position["entry"]
                    ext = abs(position["entry"] - position["tp"]) * 0.5
                    position["tp"] = round(position["tp"] - ext, 2)
                    consecutive_losses = 0
                else:
                    balance += pnl
                    trades.append({"side": "sell", "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(pnl, 2),
                                   "reason": "sl" if sl_hit else "tp_full", "bars": bars_held})
                    position = None
                    last_trade_close_idx = idx
                    consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
            else:
                # Trailing
                td = abs(position["entry"] - position["tp"])
                if price <= position["entry"] - td * 0.4:
                    new_sl = min(position["sl"], position["entry"] - td * 0.15)
                    if new_sl < position["sl"]:
                        position["sl"] = round(new_sl, 2)

        if position:
            continue
        if idx - last_trade_close_idx < 3:
            continue
        if consecutive_losses >= 3:
            if idx - last_trade_close_idx < 12:
                continue
            consecutive_losses = 0

        # Gather sentiment data
        fr_val = fr_lookup.find(ts)
        ls_val = ls_lookup.find(ts)
        fng_val = 50
        ts_day = ts // 86400000
        for offset in range(3):
            if (ts_day - offset) in fng_history:
                fng_val = fng_history[ts_day - offset]
                break

        result = score_fn(
            closes[:], highs[:], lows[:], opens[:], volumes[:], price,
            funding_rate=fr_val, ls_ratio=ls_val, fng_value=fng_val,
        )

        if result["direction"] != "bearish":
            continue

        # Dynamic risk and leverage from score_fn result
        risk_pct = result.get("risk_pct", base_risk_pct)
        lev = result.get("leverage", 2)

        sl_dist = abs(result["sl"] - price)
        if sl_dist <= 0:
            continue
        risk_amount = balance * risk_pct / 100
        amount = risk_amount / sl_dist
        margin = amount * price / lev

        if margin > balance * 0.95:
            amount = balance * 0.95 * lev / price

        position = {
            "side": "sell", "entry": price, "amount": amount,
            "sl": result["sl"], "tp": result["tp"],
            "leverage": lev, "opened_idx": idx,
        }

    if position:
        price = closes[-1]
        pnl = (position["entry"] - price) * position["amount"]
        balance += pnl
        trades.append({"side": "sell", "entry": position["entry"],
                       "exit": round(price, 2), "pnl": round(pnl, 2),
                       "reason": "end_of_backtest", "bars": len(klines) - position["opened_idx"]})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    wr = len(wins)/len(trades)*100 if trades else 0
    pf = abs(sum(t["pnl"] for t in wins)) / abs(sum(t["pnl"] for t in losses)) \
         if losses and sum(t["pnl"] for t in losses) != 0 else 999
    max_dd = 0
    peak = initial_balance
    for e in equity:
        if e > peak: peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd: max_dd = dd

    return {
        "label": label, "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr, 1), "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_balance * 100, 2),
        "profit_factor": round(pf, 2), "max_drawdown_pct": round(max_dd, 2),
        "avg_win": round(sum(t["pnl"] for t in wins)/len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pnl"] for t in losses)/len(losses), 2) if losses else 0,
    }


# ============================================================
# Strategy Variants
# ============================================================

def _base_entry(closes, highs, lows, opens, volumes, current_price):
    """Combined entry logic — shared by all variants"""
    if len(closes) < 50:
        return None

    adx = calc_adx(highs, lows, closes)
    atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_4h = trend_direction(closes_4h, 20, 50)
    trend_1h = trend_direction(closes, 20, 50)

    ema21 = calc_ema(closes[-30:], 21) if len(closes) >= 21 else current_price
    two_bears = len(closes) >= 3 and closes[-1] < opens[-1] and closes[-2] < opens[-2]
    below_ema = current_price < ema21

    if not (trend_4h < 0 and two_bears and below_ema):
        return None

    smc_adj = 0
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc["score_adjustment"]
        except: pass

    swing_lookback = min(60, len(closes))
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows)))
                   if recent_lows[i-1] < recent_lows[i])

    return {
        "atr": atr, "adx": adx, "trend_4h": trend_4h, "trend_1h": trend_1h,
        "smc_adj": smc_adj, "ll_count": ll_count,
        "rsi": calc_rsi(closes), "ema21": ema21,
    }


def make_s0_baseline(**_):
    """S0: Baseline — Combined SL3 TP8 L2 R2% (no news)"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}
        return {
            "score": 30, "direction": "bearish", "breakdown": [],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": 2, "risk_pct": 2.0,
        }
    return score


def make_s1_fng_position(**_):
    """S1: FNG动态仓位 — FNG越低(越恐惧)→仓位越大做空"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        fng = kw.get("fng_value", 50)
        # FNG < 10: 3.0% risk | FNG < 20: 2.5% | FNG < 30: 2.0% | FNG >= 30: 1.0%
        if fng <= 10:
            risk = 3.0
        elif fng <= 20:
            risk = 2.5
        elif fng <= 30:
            risk = 2.0
        else:
            risk = 1.0  # Less fear = smaller position

        return {
            "score": 30, "direction": "bearish", "breakdown": [f"FNG={fng}→risk={risk}%"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": 2, "risk_pct": risk,
        }
    return score


def make_s2_fng_leverage(**_):
    """S2: FNG动态杠杆 — FNG越低→杠杆越高"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        fng = kw.get("fng_value", 50)
        if fng <= 10:
            lev = 4
        elif fng <= 15:
            lev = 3
        elif fng <= 25:
            lev = 2
        else:
            lev = 1

        return {
            "score": 30, "direction": "bearish", "breakdown": [f"FNG={fng}→lev={lev}x"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": lev, "risk_pct": 2.0,
        }
    return score


def make_s3_fr_confirm(**_):
    """S3: 资金费率确认 — 正FR(多头付费)=加仓, 负FR(空头拥挤)=减仓"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        fr = kw.get("funding_rate")
        risk = 2.0
        if fr is not None:
            if fr > 0.01:  # Positive FR = longs paying = more shorts likely right
                risk = 2.5
            elif fr < -0.01:  # Negative FR = shorts paying = crowded short, risky
                risk = 1.0
            elif fr > 0.005:
                risk = 2.2

        return {
            "score": 30, "direction": "bearish", "breakdown": [f"FR={fr}→risk={risk}%"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": 2, "risk_pct": risk,
        }
    return score


def make_s4_ls_contrarian(**_):
    """S4: 多空比逆向 — LS>1.5(多头过多)→加仓做空"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        ls = kw.get("ls_ratio")
        risk = 2.0
        if ls is not None:
            if ls > 2.0:   # Way too many longs → strong short
                risk = 3.0
            elif ls > 1.5: # Many longs → mild increase
                risk = 2.5
            elif ls < 0.7: # Many shorts already → don't add
                risk = 1.0

        return {
            "score": 30, "direction": "bearish", "breakdown": [f"LS={ls}→risk={risk}%"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": 2, "risk_pct": risk,
        }
    return score


def make_s5_full_combo(**_):
    """S5: 全组合 — FNG+FR+LS全部纳入评分"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        fng = kw.get("fng_value", 50)
        fr = kw.get("funding_rate")
        ls = kw.get("ls_ratio")

        # Base risk
        risk = 2.0

        # FNG adjustment
        if fng <= 10: risk += 1.0
        elif fng <= 20: risk += 0.5
        elif fng > 30: risk -= 1.0

        # FR adjustment
        if fr is not None:
            if fr > 0.01: risk += 0.5    # Longs paying = good for shorts
            elif fr < -0.01: risk -= 0.5  # Shorts crowded

        # LS adjustment
        if ls is not None:
            if ls > 2.0: risk += 0.5    # Too many longs
            elif ls < 0.7: risk -= 0.5  # Too many shorts

        risk = max(0.5, min(4.0, risk))

        # FNG dynamic leverage
        if fng <= 15: lev = 3
        elif fng <= 25: lev = 2
        else: lev = 1

        return {
            "score": 30, "direction": "bearish",
            "breakdown": [f"FNG={fng} FR={fr} LS={ls}→risk={risk:.1f}% lev={lev}x"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": lev, "risk_pct": risk,
        }
    return score


def make_s6_fng_gate(**_):
    """S6: FNG Gate — FNG>30就不交易(只在极度恐惧时操作)"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        fng = kw.get("fng_value", 50)
        if fng > 30:  # Not scared enough → skip
            return {"score": 50, "direction": "neutral", "breakdown": [f"FNG={fng}>30,跳过"], "atr": 0}

        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        return {
            "score": 30, "direction": "bearish", "breakdown": [f"FNG={fng}≤30,允许交易"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * 8.0, 2),
            "leverage": 2, "risk_pct": 2.0,
        }
    return score


def make_s7_full_optimized(**_):
    """S7: 终极版 — FNG分级杠杆+FR/LS仓位调节+FNG>30不交易+SMC加分"""
    def score(closes, highs, lows, opens, volumes, current_price, **kw):
        fng = kw.get("fng_value", 50)
        if fng > 30:
            return {"score": 50, "direction": "neutral", "breakdown": [f"FNG={fng}>30"], "atr": 0}

        ctx = _base_entry(closes, highs, lows, opens, volumes, current_price)
        if ctx is None:
            return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

        fr = kw.get("funding_rate")
        ls = kw.get("ls_ratio")

        # Leverage from FNG
        if fng <= 10: lev = 4
        elif fng <= 15: lev = 3
        elif fng <= 25: lev = 2
        else: lev = 1

        # Risk from FNG + FR + LS + SMC
        risk = 2.0
        if fng <= 10: risk += 0.8
        elif fng <= 20: risk += 0.3

        if fr is not None:
            if fr > 0.01: risk += 0.3
            elif fr < -0.01: risk -= 0.5

        if ls is not None:
            if ls > 1.8: risk += 0.3
            elif ls < 0.7: risk -= 0.3

        # SMC boost
        if ctx["smc_adj"] < -5: risk += 0.3
        if ctx["ll_count"] >= 3: risk += 0.2

        risk = max(0.5, min(4.0, risk))

        # TP extension when SMC strongly bearish
        tp_mult = 8.0
        if ctx["smc_adj"] < -5: tp_mult = 10.0
        if ctx["ll_count"] >= 4: tp_mult = 10.0

        return {
            "score": 30, "direction": "bearish",
            "breakdown": [f"FNG={fng} FR={fr} LS={ls} SMC={ctx['smc_adj']}→R{risk:.1f}% L{lev}x TP{tp_mult}x"],
            "atr": ctx["atr"],
            "sl": round(current_price + ctx["atr"] * 3.0, 2),
            "tp": round(current_price - ctx["atr"] * tp_mult, 2),
            "leverage": lev, "risk_pct": risk,
        }
    return score


# ============================================================
# Run
# ============================================================

async def run():
    fetcher = OKXDataFetcher()
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    days = 30

    strategies = [
        ("S0: Baseline (无新闻)", make_s0_baseline),
        ("S1: FNG动态仓位", make_s1_fng_position),
        ("S2: FNG动态杠杆", make_s2_fng_leverage),
        ("S3: 资金费率确认", make_s3_fr_confirm),
        ("S4: 多空比逆向", make_s4_ls_contrarian),
        ("S5: FNG+FR+LS全组合", make_s5_full_combo),
        ("S6: FNG≤30 Gate", make_s6_fng_gate),
        ("S7: 终极版(全指标)", make_s7_full_optimized),
    ]

    all_data = {}
    for symbol in symbols:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        data = await fetcher.fetch_all(symbol, start, end, days)
        all_data[symbol] = (data, int(start.timestamp() * 1000))
        await asyncio.sleep(0.5)

    all_results = {}
    lines = []
    lines.append("=" * 120)
    lines.append("NEWS-INTEGRATED CRISIS STRATEGY — FNG/FR/LS加入冠军策略")
    lines.append("=" * 120)

    for symbol in symbols:
        data, start_ms = all_data[symbol]
        klines = data["klines"]
        prices = [k["close"] for k in klines]
        pc = (prices[-1]/prices[50]-1)*100

        lines.append(f"\n{'='*90}")
        lines.append(f"  {symbol} (30d) | ${prices[50]:,.0f} → ${prices[-1]:,.0f} ({pc:+.1f}%)")
        lines.append(f"{'='*90}")
        lines.append(f"  {'Strategy':<35} {'T':>3} {'WR%':>5} {'PnL$':>9} {'PnL%':>7} {'PF':>5} {'DD%':>5}")
        lines.append(f"  {'-'*75}")

        results = []
        for label, factory in strategies:
            scorer = factory()
            r = simulate_news_trades(klines, scorer, data, start_ms, label=label,
                                     base_risk_pct=2.0, max_hold=72)
            results.append(r)
            marker = " ★" if r["total_pnl"] > 0 else ""
            lines.append(f"  {label:<35} {r['trades']:>3} {r['win_rate']:>4.1f}% "
                        f"{r['total_pnl']:>+8.0f} {r['total_pnl_pct']:>+6.1f}% "
                        f"{r['profit_factor']:>4.2f} {r['max_drawdown_pct']:>4.1f}%{marker}")

        all_results[symbol] = results

    # Cross-symbol ranking
    lines.append(f"\n{'='*90}")
    lines.append("CROSS-SYMBOL RANKING")
    lines.append(f"{'='*90}")
    group_totals = {}
    for label, _ in strategies:
        pnl_pcts = []
        for symbol in symbols:
            for r in all_results.get(symbol, []):
                if r["label"] == label:
                    pnl_pcts.append(r["total_pnl_pct"])
        if pnl_pcts:
            group_totals[label] = (sum(pnl_pcts)/len(pnl_pcts), all(p > 0 for p in pnl_pcts))
    for label, (avg, allp) in sorted(group_totals.items(), key=lambda x: -x[1][0]):
        marker = " ✅ ALL PROFIT" if allp else (" ★ AVG PROFIT" if avg > 0 else "")
        lines.append(f"  {label:<35} avg: {avg:>+6.2f}%{marker}")

    report = "\n".join(lines)
    print(report)

    os.makedirs("data", exist_ok=True)
    with open("data/crisis_news_integrated_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    save = {"results": {s: [{k:v for k,v in r.items()} for r in rs]
                        for s, rs in all_results.items()}}
    with open("data/crisis_news_integrated.json", "w", encoding="utf-8") as f:
        json.dump(save, f, ensure_ascii=False, indent=2)
    logger.info("💾 Saved to data/crisis_news_integrated_report.txt")


if __name__ == "__main__":
    asyncio.run(run())
