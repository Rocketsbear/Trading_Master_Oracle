"""
Indicator Subset Backtest — 指标子集回测对比

对 BTC 90天数据跑5组不同的指标组合，找出最优胜率/盈亏比组合。
每组使用相同的交易模拟引擎（TP分级/Trailing/门控），只改变评分层。

Groups:
  A: Pure Trend    (趋势+价格结构+EMA)
  B: Trend+Momentum (A + RSI + MACD + StochRSI)
  C: Trend+SMC      (A + 聪明钱BOS/CHoCH/OB)
  D: Trend+Sentiment (A + 恐贪+多空比+资金费率)
  E: Full 18-Layer   (当前完整系统，对照组)

Usage:
  python -m backend.trading.indicator_subset_backtest
"""
import asyncio
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

# Reuse existing modules
from backend.trading.backtester_v2 import (
    HistoricalDataFetcher, _SortedLookup,
    calc_ema, calc_rsi, calc_adx, trend_direction,
    score_bar as full_score_bar,
)

try:
    from backend.analysis.smart_money import analyze_smc as _analyze_smc
except Exception:
    _analyze_smc = None


# ============================================================
# Subset Scoring Functions
# ============================================================

def score_group_a(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group A: Pure Trend — 趋势 + 价格结构 + EMA交叉"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    # Trend (4H dominant)
    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    trends_agree = (trend_15m == trend_1h == trend_4h) and trend_15m != 0
    if trends_agree:
        trend_score = int(trend_score * 1.2)
    if not trends_agree and abs(trend_score) > 8:
        trend_score -= int(trend_score * 0.5)
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score
    if trend_score != 0:
        breakdown.append(f"趋势{'+' if trend_score > 0 else ''}{trend_score}")

    # Price structure (HH/HL/LL/LH)
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count, ll_count = 0, 0
    for i in range(1, min(5, len(recent_highs))):
        if recent_highs[i - 1] > recent_highs[i]:
            hh_count += 1
        if recent_lows[i - 1] < recent_lows[i]:
            ll_count += 1
    price_structure = "no_structure"
    if hh_count >= 3:
        tech_score += 5
        price_structure = "bullish_structure"
        breakdown.append(f"价格结构+5(HH={hh_count})")
    elif ll_count >= 3:
        tech_score -= 5
        price_structure = "bearish_structure"
        breakdown.append(f"价格结构-5(LL={ll_count})")

    # EMA 8/21 cross
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        ema8_prev = calc_ema(closes[-31:-1], 8) if len(closes) >= 31 else ema8
        ema21_prev = calc_ema(closes[-31:-1], 21) if len(closes) >= 31 else ema21
        if ema8 > ema21 and ema8_prev <= ema21_prev:
            tech_score += 5
            breakdown.append("EMA8/21金叉+5")
        elif ema8 < ema21 and ema8_prev >= ema21_prev:
            tech_score -= 5
            breakdown.append("EMA8/21死叉-5")

    tech_score = max(0, min(100, tech_score))
    return _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                     atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)


def score_group_b(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group B: Trend + Momentum — A + RSI + MACD + StochRSI"""
    if len(closes) < 50:
        return {"score": 50, "direction": "neutral", "breakdown": [], "atr": 0}

    tech_score = 50
    breakdown = []

    rsi = calc_rsi(closes)
    adx = calc_adx(highs, lows, closes)
    atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14

    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::4] if len(closes) >= 200 else closes
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)

    # Trend
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
        if recent_highs[i - 1] > recent_highs[i]: hh_count += 1
        if recent_lows[i - 1] < recent_lows[i]: ll_count += 1
    price_structure = "no_structure"
    if hh_count >= 3:
        tech_score += 5; price_structure = "bullish_structure"
    elif ll_count >= 3:
        tech_score -= 5; price_structure = "bearish_structure"

    # EMA cross
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        ema8_prev = calc_ema(closes[-31:-1], 8) if len(closes) >= 31 else ema8
        ema21_prev = calc_ema(closes[-31:-1], 21) if len(closes) >= 31 else ema21
        if ema8 > ema21 and ema8_prev <= ema21_prev: tech_score += 5
        elif ema8 < ema21 and ema8_prev >= ema21_prev: tech_score -= 5

    # RSI
    momentum_score = 0
    if rsi < 30 and trend_15m >= 0: momentum_score += 5
    elif rsi > 70 and trend_15m <= 0: momentum_score -= 5
    elif rsi < 40 and trend_15m > 0: momentum_score += 3
    elif rsi > 60 and trend_15m < 0: momentum_score -= 3

    # MACD
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = ema12 - ema26
    if macd_line > 0 and trend_15m > 0: momentum_score += 5
    elif macd_line < 0 and trend_15m < 0: momentum_score -= 5

    # MACD histogram
    if len(closes) >= 26:
        k12, k26 = 2/13, 2/27
        e12, e26 = sum(closes[:12])/12, sum(closes[:26])/26
        macd_values = []
        for i in range(26, len(closes)):
            e12 = closes[i]*k12 + e12*(1-k12)
            e26 = closes[i]*k26 + e26*(1-k26)
            macd_values.append(e12 - e26)
        if len(macd_values) >= 2:
            if abs(macd_values[-1]) > abs(macd_values[-2]):
                macd_sig = calc_ema(macd_values, 9) if len(macd_values) >= 9 else macd_values[-1]
                hist = macd_values[-1] - macd_sig
                if hist > 0: momentum_score += 5
                elif hist < 0: momentum_score -= 5
    tech_score += momentum_score

    # StochRSI
    try:
        window = min(len(closes), 42)
        c_win = closes[-window:]
        rsi_vals = []
        for i in range(14, len(c_win)):
            g = [max(0, c_win[j]-c_win[j-1]) for j in range(i-13, i+1)]
            l = [max(0, c_win[j-1]-c_win[j]) for j in range(i-13, i+1)]
            ag, al = sum(g)/14, sum(l)/14
            rsi_vals.append(100 - 100/(1+ag/al) if al > 0 else 100)
        if len(rsi_vals) >= 14:
            rw = rsi_vals[-14:]
            rmn, rmx = min(rw), max(rw)
            srsi = ((rsi_vals[-1]-rmn)/(rmx-rmn)*100) if rmx != rmn else 50
            if srsi < 20 and trend_15m >= 0: tech_score += 5
            elif srsi > 80 and trend_15m <= 0: tech_score -= 5
    except: pass

    tech_score = max(0, min(100, tech_score))
    return _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                     atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)


def score_group_c(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group C: Trend + SMC — A + 聪明钱"""
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

    # Trend
    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    trends_agree = (trend_15m == trend_1h == trend_4h) and trend_15m != 0
    if trends_agree: trend_score = int(trend_score * 1.2)
    if not trends_agree and abs(trend_score) > 8: trend_score -= int(trend_score * 0.5)
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score

    # Price structure
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count, ll_count = 0, 0
    for i in range(1, min(5, len(recent_highs))):
        if recent_highs[i - 1] > recent_highs[i]: hh_count += 1
        if recent_lows[i - 1] < recent_lows[i]: ll_count += 1
    price_structure = "no_structure"
    if hh_count >= 3: tech_score += 5; price_structure = "bullish_structure"
    elif ll_count >= 3: tech_score -= 5; price_structure = "bearish_structure"

    # EMA cross
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        ema8_prev = calc_ema(closes[-31:-1], 8) if len(closes) >= 31 else ema8
        ema21_prev = calc_ema(closes[-31:-1], 21) if len(closes) >= 31 else ema21
        if ema8 > ema21 and ema8_prev <= ema21_prev: tech_score += 5
        elif ema8 < ema21 and ema8_prev >= ema21_prev: tech_score -= 5

    # SMC
    if _analyze_smc:
        try:
            smc = _analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc["score_adjustment"]
            tech_score += smc_adj
            if smc_adj != 0:
                breakdown.append(f"SMC{'+' if smc_adj > 0 else ''}{smc_adj}")
        except: pass

    tech_score = max(0, min(100, tech_score))
    return _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                     atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)


def score_group_d(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group D: Trend + Sentiment — A + 恐贪 + 多空比 + 资金费率"""
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

    # Trend
    trend_score = trend_15m * 4 + trend_1h * 6 + trend_4h * 10
    trends_agree = (trend_15m == trend_1h == trend_4h) and trend_15m != 0
    if trends_agree: trend_score = int(trend_score * 1.2)
    if not trends_agree and abs(trend_score) > 8: trend_score -= int(trend_score * 0.5)
    trend_score = max(-20, min(20, trend_score))
    tech_score += trend_score

    # Price structure
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count, ll_count = 0, 0
    for i in range(1, min(5, len(recent_highs))):
        if recent_highs[i - 1] > recent_highs[i]: hh_count += 1
        if recent_lows[i - 1] < recent_lows[i]: ll_count += 1
    price_structure = "no_structure"
    if hh_count >= 3: tech_score += 5; price_structure = "bullish_structure"
    elif ll_count >= 3: tech_score -= 5; price_structure = "bearish_structure"

    # EMA cross
    if len(closes) >= 21:
        ema8 = calc_ema(closes[-30:], 8)
        ema21 = calc_ema(closes[-30:], 21)
        ema8_prev = calc_ema(closes[-31:-1], 8) if len(closes) >= 31 else ema8
        ema21_prev = calc_ema(closes[-31:-1], 21) if len(closes) >= 31 else ema21
        if ema8 > ema21 and ema8_prev <= ema21_prev: tech_score += 5
        elif ema8 < ema21 and ema8_prev >= ema21_prev: tech_score -= 5

    # Fear & Greed
    fng = kw.get("fng_value", 50)
    if fng <= 10: tech_score += 10
    elif fng <= 25: tech_score += 5
    elif fng >= 90: tech_score -= 10
    elif fng >= 75: tech_score -= 5

    # Funding rate
    fr = kw.get("funding_rate")
    if fr is not None:
        if fr > 0.05 and tech_score >= 60: tech_score -= 5
        elif fr < -0.05 and tech_score <= 40: tech_score -= 5
        elif abs(fr) > 0.1: tech_score -= 3

    # L/S ratio (simplified)
    ls = kw.get("ls_ratio")
    if ls is not None:
        if ls > 2.0: tech_score -= 5  # Too many longs → contrarian bearish
        elif ls < 0.5: tech_score += 5  # Too many shorts → contrarian bullish
        elif ls > 1.5: tech_score -= 3
        elif ls < 0.7: tech_score += 3

    tech_score = max(0, min(100, tech_score))
    return _finalize(tech_score, breakdown, closes, highs, lows, current_price,
                     atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw)


def score_group_e(closes, highs, lows, opens, volumes, current_price, **kw):
    """Group E: Full 18-Layer — 对照组（使用现有 score_bar）"""
    return full_score_bar(closes, highs, lows, opens, volumes, current_price, **kw)


def _finalize(tech_score, breakdown, closes, highs, lows, current_price,
              atr_approx, adx, trend_4h, trend_1h, trend_15m, price_structure, kw):
    """Shared: direction + ADX gate + SL/TP + R:R filter"""
    market_regime = "trending" if adx >= 25 else "ranging" if adx < 20 else "transitioning"

    # ADX dampen
    if adx < 20 and abs(tech_score - 50) > 10:
        tech_score = 50 + int((tech_score - 50) * 0.5)
    tech_score = max(0, min(100, tech_score))

    # Direction (using configurable threshold)
    threshold = kw.get("score_threshold", 60)  # Default 60 for subsets
    if tech_score >= threshold:
        direction = "bullish"
    elif tech_score <= (100 - threshold):
        direction = "bearish"
    else:
        direction = "neutral"

    # 4H Trend Guard
    if direction == "bullish" and trend_4h < 0 and trend_1h < 0:
        tech_score -= 5; direction = "neutral"
    elif direction == "bearish" and trend_4h > 0 and trend_1h > 0:
        tech_score += 5; direction = "neutral"

    # ADX gate
    if adx < 15 and direction != "neutral":
        direction = "neutral"

    # SL/TP
    atr_pct = atr_approx / current_price * 100 if current_price > 0 else 1
    if market_regime == "trending":
        sl_mult, tp_mult = 2.0, 4.5
    elif market_regime == "ranging":
        sl_mult, tp_mult = 1.8, 2.5
    else:
        sl_mult, tp_mult = 2.0, 3.5

    if direction == "bullish":
        sl = current_price - atr_approx * sl_mult
        tp = current_price + atr_approx * tp_mult
    elif direction == "bearish":
        sl = current_price + atr_approx * sl_mult
        tp = current_price - atr_approx * tp_mult
    else:
        sl = current_price - atr_approx * sl_mult
        tp = current_price + atr_approx * tp_mult

    # R:R filter
    min_rr = 1.8 if market_regime == "trending" else 1.3
    rr = 0.0
    if direction != "neutral":
        risk_d = abs(current_price - sl)
        reward_d = abs(tp - current_price)
        rr = round(reward_d / risk_d, 2) if risk_d > 0 else 0
        if rr < min_rr:
            direction = "neutral"

    # Leverage
    conf = abs(tech_score - 50) / 50
    if tech_score >= 80 or tech_score <= 20: base_lev = 5
    elif tech_score >= 70 or tech_score <= 30: base_lev = 3
    elif tech_score >= 60 or tech_score <= 40: base_lev = 2
    else: base_lev = 1
    if atr_pct > 3.0: vol_f = 0.5
    elif atr_pct > 2.0: vol_f = 0.7
    elif atr_pct > 1.0: vol_f = 0.85
    else: vol_f = 1.0
    rec_lev = max(1, min(5, int(base_lev * vol_f)))
    if market_regime == "ranging": rec_lev = max(1, rec_lev - 1)

    return {
        "score": tech_score, "direction": direction, "breakdown": breakdown,
        "atr": atr_approx, "sl": round(sl, 2), "tp": round(tp, 2),
        "rr_ratio": rr, "leverage": rec_lev, "rsi": calc_rsi(closes),
        "adx": adx, "market_regime": market_regime,
        "trend_4h": trend_4h, "trend_1h": trend_1h,
        "price_structure": price_structure,
    }


# ============================================================
# Trade Simulation Engine (identical for all groups)
# ============================================================

def simulate_trades(klines, score_fn, data, start_ms, initial_balance=10000,
                    risk_pct=2.0, score_threshold=60, label=""):
    """Run trade simulation using a given scoring function."""
    import bisect

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
            max_hold = 36 if position.get("regime") == "trending" else 18

            if bars_held >= max_hold and not tp_hit:
                exit_p = price
                pnl = (exit_p - position["entry"]) * position["amount"] if position["side"] == "buy" else \
                      (position["entry"] - exit_p) * position["amount"]
                balance += pnl
                daily_pnl += pnl
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
                    partial_pnl = pnl * 0.6
                    balance += partial_pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(partial_pnl, 2),
                                   "reason": "partial_tp_60%", "bars": bars_held})
                    position["amount"] *= 0.4
                    position["sl"] = position["entry"]
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

        # Skip if has position or in cooldown
        if position:
            continue
        cooldown = 3
        if idx - last_trade_close_idx < cooldown:
            continue
        # Circuit breaker
        if consecutive_losses >= 3:
            if idx - last_trade_close_idx < 12:
                continue
            consecutive_losses = 0

        # Score
        fr_val = fr_lookup.find(ts)
        ls_val = ls_lookup.find(ts)
        oi_cur = oi_lookup.find(ts)
        oi_prev = oi_lookup.find(ts - 3600000)

        # FNG: find closest daily value
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
        score = result["score"]

        if direction == "neutral":
            continue

        # Open position
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

    # Close any remaining position at last price
    if position:
        price = closes[-1]
        pnl = (price - position["entry"]) * position["amount"] if position["side"] == "buy" else \
              (position["entry"] - price) * position["amount"]
        balance += pnl
        trades.append({"side": position["side"], "entry": position["entry"],
                       "exit": round(price, 2), "pnl": round(pnl, 2),
                       "reason": "end_of_backtest", "bars": len(klines) - position["opened_idx"]})

    # Calculate stats
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
        "label": label,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_balance * 100, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "final_balance": round(balance, 2),
        "trade_details": trades,
    }


# ============================================================
# Main: Fetch once, run 5 groups
# ============================================================

async def run_comparison():
    symbol = "BTCUSDT"
    days = 90
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    logger.info(f"\n{'='*70}")
    logger.info(f"📊 INDICATOR SUBSET BACKTEST — {symbol} {days}天")
    logger.info(f"   {start_str} → {end_str}")
    logger.info(f"{'='*70}")

    # Fetch data ONCE
    fetcher = HistoricalDataFetcher()
    data = await fetcher.fetch_all(symbol, start, end)

    # Fetch FNG history
    fng_history = {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.alternative.me/fng/?limit={days+10}&format=json")
            if r.status_code == 200:
                for item in r.json().get("data", []):
                    ts_day = int(item["timestamp"]) * 1000 // 86400000
                    fng_history[ts_day] = int(item["value"])
    except: pass
    data["fng_history"] = fng_history

    klines = data["klines"]
    start_ms = int(start.timestamp() * 1000)

    if len(klines) < 100:
        logger.error(f"K线不足: {len(klines)}")
        return

    logger.info(f"\n📈 数据: {len(klines)} K线, {len(data['funding_rates'])} FR, "
                f"{len(data['long_short_ratios'])} LS, {len(data['oi_history'])} OI, "
                f"{len(fng_history)} FNG")

    # Define groups
    groups = [
        ("A: Pure Trend (趋势+结构+EMA)", score_group_a, 60),
        ("B: Trend+Momentum (+RSI+MACD+StochRSI)", score_group_b, 60),
        ("C: Trend+SMC (+聪明钱)", score_group_c, 60),
        ("D: Trend+Sentiment (+恐贪+多空比+FR)", score_group_d, 60),
        ("E: Full 18-Layer (当前系统@60)", score_group_e, 60),
        ("F: Full 18-Layer (当前系统@65)", score_group_e, 65),
        ("G: Full 18-Layer (当前系统@70)", score_group_e, 70),
    ]

    results = []
    for label, score_fn, threshold in groups:
        logger.info(f"\n🔬 Running: {label} (threshold={threshold})")
        r = simulate_trades(klines, score_fn, data, start_ms,
                           score_threshold=threshold, label=label)
        results.append(r)
        logger.info(f"   → {r['trades']}笔 | 胜率{r['win_rate']}% | "
                    f"PnL ${r['total_pnl']} ({r['total_pnl_pct']}%) | "
                    f"PF {r['profit_factor']} | MaxDD {r['max_drawdown_pct']}%")

    # Print comparison table
    print("\n" + "="*100)
    print(f"{'GROUP':<45} {'TRADES':>6} {'WIN%':>6} {'PnL$':>10} {'PnL%':>7} {'PF':>6} {'MaxDD%':>7} {'AvgWin':>8} {'AvgLoss':>8}")
    print("="*100)
    for r in results:
        print(f"{r['label']:<45} {r['trades']:>6} {r['win_rate']:>5.1f}% "
              f"{r['total_pnl']:>+9.2f} {r['total_pnl_pct']:>+6.2f}% "
              f"{r['profit_factor']:>5.2f} {r['max_drawdown_pct']:>6.2f}% "
              f"{r['avg_win']:>+7.2f} {r['avg_loss']:>+7.2f}")
    print("="*100)

    # Save to file
    output = {
        "symbol": symbol,
        "period": f"{start_str} → {end_str}",
        "days": days,
        "klines_count": len(klines),
        "results": [{k: v for k, v in r.items() if k != "trade_details"} for r in results],
        "trade_details": {r["label"]: r["trade_details"] for r in results},
    }
    out_path = "data/backtest_indicator_comparison.json"
    import os
    os.makedirs("data", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"\n💾 详细结果已保存: {out_path}")

    return results


if __name__ == "__main__":
    asyncio.run(run_comparison())
