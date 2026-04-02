# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════
  INDICATOR LABORATORY
  从零分析: 哪些指标组合能预测赢/输?
  
  Step 1: 记录每笔交易的所有指标值 (不做任何过滤,全部入场)
  Step 2: 统计分析每个指标在赢/输中的分布
  Step 3: 测试不同指标子集的组合效果
═══════════════════════════════════════════════════════════════
"""
import asyncio, sys, os, json, time, math, statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

sys.path.insert(0, r"D:\All_in_AI\Trading_system")

from backend.archive.trading.backtester_v2 import (
    HistoricalDataFetcher, _SortedLookup,
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

INITIAL_BALANCE = 1000.0
INTERVAL = "15m"

# ═══════════════════════════════════════════════════
#  Raw Indicator Calculator (独立于评分,只采集原始值)
# ═══════════════════════════════════════════════════

def compute_all_indicators(closes, highs, lows, opens, volumes, current_price,
                           funding_rate=None, ls_ratio=None,
                           oi_current=None, oi_prev=None, fng_value=50):
    """
    计算所有指标的原始值(不加权、不评分),用于后续统计分析。
    返回 dict: 指标名 -> 原始数值
    """
    if len(closes) < 100:
        return None

    # --- Technical Indicators ---
    rsi = calc_rsi(closes)
    
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = ema12 - ema26
    
    # MACD histogram
    if len(closes) >= 26:
        k12, k26 = 2/13, 2/27
        ema12_run = sum(closes[:12]) / 12
        ema26_run = sum(closes[:26]) / 26
        macd_values = []
        for i in range(26, len(closes)):
            ema12_run = closes[i] * k12 + ema12_run * (1 - k12)
            ema26_run = closes[i] * k26 + ema26_run * (1 - k26)
            macd_values.append(ema12_run - ema26_run)
        macd_signal = calc_ema(macd_values, 9) if len(macd_values) >= 9 else 0
        macd_histogram = macd_values[-1] - macd_signal if macd_values else 0
        macd_hist_growing = 1 if len(macd_values) >= 2 and abs(macd_values[-1]) > abs(macd_values[-2]) else 0
        macd_cross_bull = 1 if len(macd_values) >= 2 and macd_values[-1] > macd_signal and macd_values[-2] <= calc_ema(macd_values[:-1], 9) else 0
    else:
        macd_histogram = 0
        macd_hist_growing = 0
        macd_cross_bull = 0

    adx = calc_adx(highs, lows, closes)
    
    # ATR
    atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    atr_pct = atr / current_price * 100
    
    # Bollinger Bands
    bb_period = min(20, len(closes))
    bb_c = closes[-bb_period:]
    bb_sma = sum(bb_c) / bb_period
    bb_std = (sum((c - bb_sma) ** 2 for c in bb_c) / bb_period) ** 0.5
    bb_upper = bb_sma + 2 * bb_std
    bb_lower = bb_sma - 2 * bb_std
    bb_position = round((current_price - bb_lower) / (bb_upper - bb_lower) * 100, 1) if bb_upper != bb_lower else 50
    bb_width = round((bb_upper - bb_lower) / bb_sma * 100, 2)
    
    # Trend (multi-timeframe)
    trend_15m = trend_direction(closes, 20, 50)
    closes_4h = closes[::16] if len(closes) >= 200 else closes[::4]
    trend_1h = trend_direction(closes, 20, 50)
    trend_4h = trend_direction(closes_4h, 20, 50)
    trends_agree = 1 if (trend_15m == trend_1h == trend_4h) and trend_15m != 0 else 0
    
    # Volume
    vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
    vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 1
    obv_trend = sum(1 if closes[i] > closes[i-1] else -1 for i in range(-10, 0))
    
    # Price change
    price_change_1h = round((closes[-1] / closes[-5] - 1) * 100, 2) if len(closes) >= 5 else 0
    price_change_4h = round((closes[-1] / closes[-17] - 1) * 100, 2) if len(closes) >= 17 else 0
    price_change_24h = round((closes[-1] / closes[-97] - 1) * 100, 2) if len(closes) >= 97 else 0
    
    # EMA position
    ema21 = calc_ema(closes[-30:], 21)
    ema50 = calc_ema(closes[-60:], 50) if len(closes) >= 60 else ema21
    ema_dist_21 = round((current_price - ema21) / ema21 * 100, 2)
    ema_dist_50 = round((current_price - ema50) / ema50 * 100, 2)
    
    # StochRSI
    stoch_rsi_k = 50
    try:
        window = min(len(closes), 42)
        c_win = closes[-window:]
        rsi_values = []
        for i in range(14, len(c_win)):
            gains = [max(0, c_win[j] - c_win[j-1]) for j in range(i-13, i+1)]
            losses_arr = [max(0, c_win[j-1] - c_win[j]) for j in range(i-13, i+1)]
            avg_g = sum(gains) / 14
            avg_l = sum(losses_arr) / 14
            rsi_values.append(100 - 100/(1+avg_g/avg_l) if avg_l > 0 else 100)
        if len(rsi_values) >= 14:
            rsi_window = rsi_values[-14:]
            rsi_min, rsi_max = min(rsi_window), max(rsi_window)
            stoch_rsi_k = ((rsi_values[-1] - rsi_min) / (rsi_max - rsi_min) * 100) if rsi_max != rsi_min else 50
    except: pass
    
    # Price structure (HH/HL/LH/LL)
    swing_lookback = min(60, len(closes))
    recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
    recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
    hh_count = sum(1 for i in range(1, min(5, len(recent_highs))) if recent_highs[i-1] > recent_highs[i])
    ll_count = sum(1 for i in range(1, min(5, len(recent_lows))) if recent_lows[i-1] < recent_lows[i])
    hl_count = sum(1 for i in range(1, min(5, len(recent_lows))) if recent_lows[i-1] > recent_lows[i])  # Higher lows
    
    # Candle patterns (last 3)
    body_ratio_1 = abs(closes[-1] - opens[-1]) / max(highs[-1] - lows[-1], 0.001)
    body_ratio_2 = abs(closes[-2] - opens[-2]) / max(highs[-2] - lows[-2], 0.001)
    consecutive_green = sum(1 for i in range(-3, 0) if closes[i] > opens[i])
    consecutive_red = sum(1 for i in range(-3, 0) if closes[i] < opens[i])
    
    # OI change
    oi_change_pct = 0
    if oi_current and oi_prev and oi_prev > 0:
        oi_change_pct = round((oi_current - oi_prev) / oi_prev * 100, 2)
    
    # Market regime
    regime = "trending" if adx >= 25 else "ranging" if adx < 20 else "transitioning"
    
    return {
        "rsi": round(rsi, 1),
        "macd_line": round(macd_line, 4),
        "macd_histogram": round(macd_histogram, 4),
        "macd_hist_growing": macd_hist_growing,
        "adx": round(adx, 1),
        "atr_pct": round(atr_pct, 2),
        "bb_position": bb_position,
        "bb_width": bb_width,
        "trend_15m": trend_15m,
        "trend_1h": trend_1h,
        "trend_4h": trend_4h,
        "trends_agree": trends_agree,
        "vol_ratio": vol_ratio,
        "obv_trend": obv_trend,
        "price_chg_1h": price_change_1h,
        "price_chg_4h": price_change_4h,
        "price_chg_24h": price_change_24h,
        "ema_dist_21": ema_dist_21,
        "ema_dist_50": ema_dist_50,
        "stoch_rsi_k": round(stoch_rsi_k, 1),
        "hh_count": hh_count,
        "ll_count": ll_count,
        "hl_count": hl_count,
        "body_ratio": round(body_ratio_1, 2),
        "consecutive_green": consecutive_green,
        "consecutive_red": consecutive_red,
        "funding_rate": round(funding_rate * 100, 4) if funding_rate is not None else None,
        "ls_ratio": round(ls_ratio, 2) if ls_ratio is not None else None,
        "oi_change_pct": oi_change_pct,
        "fng": fng_value,
        "regime": regime,
    }


# ═══════════════════════════════════════════════════
#  Phase 1: 无过滤回测, 每根K线都评估, 记录全部
# ═══════════════════════════════════════════════════

def calc_trade_result(side, entry, klines_after, atr, max_bars=96):
    """
    模拟交易结果: 固定 SL=2×ATR, TP=4×ATR 
    返回 (pnl_pct, bars_held, exit_reason)
    """
    sl_dist = atr * 2.0
    tp_dist = atr * 4.0
    
    for i, k in enumerate(klines_after):
        if i >= max_bars:
            # Timeout
            exit_price = k["close"]
            if side == "buy":
                return round((exit_price - entry) / entry * 100, 2), i, "timeout"
            else:
                return round((entry - exit_price) / entry * 100, 2), i, "timeout"
        
        high, low = k["high"], k["low"]
        
        if side == "buy":
            if low <= entry - sl_dist:
                return round(-sl_dist / entry * 100, 2), i, "sl"
            if high >= entry + tp_dist:
                return round(tp_dist / entry * 100, 2), i, "tp"
        else:
            if high >= entry + sl_dist:
                return round(-sl_dist / entry * 100, 2), i, "sl"
            if low <= entry - tp_dist:
                return round(tp_dist / entry * 100, 2), i, "tp"
    
    # End of data
    last = klines_after[-1]["close"] if klines_after else entry
    if side == "buy":
        return round((last - entry) / entry * 100, 2), len(klines_after), "end"
    else:
        return round((entry - last) / entry * 100, 2), len(klines_after), "end"


async def collect_trade_data(symbol, klines, fr_lookup, ls_lookup, oi_lookup, fng_history, start_ms):
    """
    每4根K线评估一次指标,每次都记录:
    - 如果做多,结果如何 (pnl%)
    - 如果做空,结果如何 (pnl%)
    - 此时所有指标值
    """
    closes, highs, lows, opens, volumes = [], [], [], [], []
    records = []
    
    for idx, k in enumerate(klines):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])
        
        if len(closes) < 100 or k["ts"] < start_ms:
            continue
        
        # 每8根K线(2小时)评估一次
        if idx % 8 != 0:
            continue
        
        ts = k["ts"]
        price = k["close"]
        
        fr_val = fr_lookup.find(ts)
        ls_val = ls_lookup.find(ts)
        oi_curr = oi_lookup.find(ts)
        oi_prev = oi_lookup.find(ts - 3600000)
        
        fng_value = 50
        if fng_history:
            day_key = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            fng_value = fng_history.get(day_key, 50)
        
        indicators = compute_all_indicators(
            closes, highs, lows, opens, volumes, price,
            funding_rate=fr_val, ls_ratio=ls_val,
            oi_current=oi_curr, oi_prev=oi_prev, fng_value=fng_value,
        )
        if not indicators:
            continue
        
        # ATR for SL/TP
        atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
        
        # 模拟做多和做空的结果
        future_klines = klines[idx+1:idx+97]  # 最多看后面96根(24h)
        if len(future_klines) < 10:
            continue
        
        buy_pnl, buy_bars, buy_reason = calc_trade_result("buy", price, future_klines, atr)
        sell_pnl, sell_bars, sell_reason = calc_trade_result("sell", price, future_klines, atr)
        
        records.append({
            **indicators,
            "buy_pnl_pct": buy_pnl,
            "sell_pnl_pct": sell_pnl,
            "buy_reason": buy_reason,
            "sell_reason": sell_reason,
            "buy_bars": buy_bars,
            "sell_bars": sell_bars,
            "best_side": "buy" if buy_pnl > sell_pnl else "sell",
            "best_pnl": max(buy_pnl, sell_pnl),
        })
    
    return records


# ═══════════════════════════════════════════════════
#  Phase 2: 统计分析
# ═══════════════════════════════════════════════════

def analyze_indicators(records):
    """分析哪些指标条件下胜率更高"""
    
    numeric_indicators = [
        "rsi", "adx", "atr_pct", "bb_position", "bb_width",
        "vol_ratio", "obv_trend", "stoch_rsi_k",
        "price_chg_1h", "price_chg_4h", "price_chg_24h",
        "ema_dist_21", "ema_dist_50",
        "hh_count", "ll_count", "hl_count",
        "body_ratio", "consecutive_green", "consecutive_red",
    ]
    
    categorical_indicators = [
        "trend_15m", "trend_1h", "trend_4h", "trends_agree",
        "macd_hist_growing", "regime",
    ]
    
    results = {}
    
    # --- Per-indicator analysis: buy side ---
    print("\n  ══════════════════════════════════════════════════════════")
    print("  PHASE 2: INDICATOR EFFECTIVENESS ANALYSIS (BUY SIDE)")
    print("  ══════════════════════════════════════════════════════════")
    
    for ind in numeric_indicators:
        vals = [r[ind] for r in records if r.get(ind) is not None]
        if not vals:
            continue
        median = statistics.median(vals)
        
        # Split by above/below median
        above = [r for r in records if r.get(ind) is not None and r[ind] > median]
        below = [r for r in records if r.get(ind) is not None and r[ind] <= median]
        
        if not above or not below:
            continue
        
        above_wr = sum(1 for r in above if r["buy_pnl_pct"] > 0) / len(above) * 100
        below_wr = sum(1 for r in below if r["buy_pnl_pct"] > 0) / len(below) * 100
        above_avg = sum(r["buy_pnl_pct"] for r in above) / len(above)
        below_avg = sum(r["buy_pnl_pct"] for r in below) / len(below)
        
        # Predictive power = absolute difference in win rate
        pred_power = abs(above_wr - below_wr)
        
        results[f"buy_{ind}"] = {
            "indicator": ind,
            "side": "buy",
            "median": round(median, 2),
            "above_wr": round(above_wr, 1),
            "below_wr": round(below_wr, 1),
            "above_avg_pnl": round(above_avg, 2),
            "below_avg_pnl": round(below_avg, 2),
            "pred_power": round(pred_power, 1),
            "n_above": len(above),
            "n_below": len(below),
            "better_when": f">{median:.1f}" if above_wr > below_wr else f"<={median:.1f}",
        }
    
    # --- Same for sell side ---
    for ind in numeric_indicators:
        vals = [r[ind] for r in records if r.get(ind) is not None]
        if not vals:
            continue
        median = statistics.median(vals)
        
        above = [r for r in records if r.get(ind) is not None and r[ind] > median]
        below = [r for r in records if r.get(ind) is not None and r[ind] <= median]
        
        if not above or not below:
            continue
        
        above_wr = sum(1 for r in above if r["sell_pnl_pct"] > 0) / len(above) * 100
        below_wr = sum(1 for r in below if r["sell_pnl_pct"] > 0) / len(below) * 100
        above_avg = sum(r["sell_pnl_pct"] for r in above) / len(above)
        below_avg = sum(r["sell_pnl_pct"] for r in below) / len(below)
        
        pred_power = abs(above_wr - below_wr)
        
        results[f"sell_{ind}"] = {
            "indicator": ind,
            "side": "sell",
            "median": round(median, 2),
            "above_wr": round(above_wr, 1),
            "below_wr": round(below_wr, 1),
            "above_avg_pnl": round(above_avg, 2),
            "below_avg_pnl": round(below_avg, 2),
            "pred_power": round(pred_power, 1),
            "n_above": len(above),
            "n_below": len(below),
            "better_when": f">{median:.1f}" if above_wr > below_wr else f"<={median:.1f}",
        }
    
    # --- Categorical indicators ---
    for ind in categorical_indicators:
        for side in ["buy", "sell"]:
            pnl_key = f"{side}_pnl_pct"
            groups = defaultdict(list)
            for r in records:
                if r.get(ind) is not None:
                    groups[r[ind]].append(r[pnl_key])
            
            for val, pnls in groups.items():
                if len(pnls) < 10:
                    continue
                wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
                avg = sum(pnls) / len(pnls)
                results[f"{side}_{ind}_{val}"] = {
                    "indicator": f"{ind}={val}",
                    "side": side,
                    "win_rate": round(wr, 1),
                    "avg_pnl": round(avg, 2),
                    "n": len(pnls),
                    "pred_power": round(abs(wr - 50), 1),  # deviation from 50%
                }
    
    # Print top predictors
    sorted_results = sorted(results.items(), key=lambda x: x[1].get("pred_power", 0), reverse=True)
    
    print(f"\n  {'Rank':>4s} {'Indicator':24s} {'Side':6s} {'Pred.Power':>10s} {'BetterWhen':>12s} {'WR+':>6s} {'WR-':>6s} {'AvgPnl+':>8s} {'AvgPnl-':>8s}")
    print("  " + "-" * 95)
    
    for rank, (key, data) in enumerate(sorted_results[:30], 1):
        if "better_when" in data:
            print(f"  {rank:4d} {data['indicator']:24s} {data['side']:6s} {data['pred_power']:>9.1f}% "
                  f"{data['better_when']:>12s} {data['above_wr']:>5.1f}% {data['below_wr']:>5.1f}% "
                  f"{data['above_avg_pnl']:>+7.2f}% {data['below_avg_pnl']:>+7.2f}%")
        else:
            print(f"  {rank:4d} {data['indicator']:24s} {data['side']:6s} {data['pred_power']:>9.1f}% "
                  f"{'':>12s} {data['win_rate']:>5.1f}% {'':>6s} "
                  f"{data['avg_pnl']:>+7.2f}% {'':>8s} n={data['n']}")
    
    return results, sorted_results


# ═══════════════════════════════════════════════════
#  Phase 3: 组合测试
# ═══════════════════════════════════════════════════

def test_indicator_combos(records, top_indicators):
    """
    测试不同指标组合的交易效果
    """
    print("\n  ══════════════════════════════════════════════════════════")
    print("  PHASE 3: INDICATOR COMBINATION TEST")
    print("  ══════════════════════════════════════════════════════════")
    
    combos = {
        "Baseline_NoFilter": {
            "buy": lambda r: True,
            "sell": lambda r: True,
        },
        "Trend4H_Only": {
            "buy": lambda r: r["trend_4h"] > 0,
            "sell": lambda r: r["trend_4h"] < 0,
        },
        "RSI_Classic": {
            "buy": lambda r: r["rsi"] < 40,
            "sell": lambda r: r["rsi"] > 60,
        },
        "ADX_Trend": {
            "buy": lambda r: r["adx"] > 25 and r["trend_4h"] > 0,
            "sell": lambda r: r["adx"] > 25 and r["trend_4h"] < 0,
        },
        "MACD_Cross": {
            "buy": lambda r: r["macd_histogram"] > 0 and r["macd_hist_growing"] == 1,
            "sell": lambda r: r["macd_histogram"] < 0 and r["macd_hist_growing"] == 1,
        },
        "EMA_Position": {
            "buy": lambda r: r["ema_dist_21"] > 0 and r["ema_dist_50"] > 0,
            "sell": lambda r: r["ema_dist_21"] < 0 and r["ema_dist_50"] < 0,
        },
        "Volume_Confirm": {
            "buy": lambda r: r["vol_ratio"] > 1.5 and r["obv_trend"] > 3,
            "sell": lambda r: r["vol_ratio"] > 1.5 and r["obv_trend"] < -3,
        },
        "BB_Reversal": {
            "buy": lambda r: r["bb_position"] < 20,
            "sell": lambda r: r["bb_position"] > 80,
        },
        "Structure_HH": {
            "buy": lambda r: r["hh_count"] >= 3 and r["hl_count"] >= 2,
            "sell": lambda r: r["ll_count"] >= 3,
        },
        "PriceChg_Momentum": {
            "buy": lambda r: r["price_chg_4h"] > 0.5 and r["price_chg_1h"] > 0,
            "sell": lambda r: r["price_chg_4h"] < -0.5 and r["price_chg_1h"] < 0,
        },
        
        # ═══ COMBINATIONS ═══
        "Combo_TrendMacdVol": {
            "buy": lambda r: r["trend_4h"] > 0 and r["macd_histogram"] > 0 and r["vol_ratio"] > 1.2,
            "sell": lambda r: r["trend_4h"] < 0 and r["macd_histogram"] < 0 and r["vol_ratio"] > 1.2,
        },
        "Combo_TrendRsiEma": {
            "buy": lambda r: r["trend_4h"] > 0 and r["rsi"] > 40 and r["rsi"] < 65 and r["ema_dist_21"] > 0,
            "sell": lambda r: r["trend_4h"] < 0 and r["rsi"] < 60 and r["rsi"] > 35 and r["ema_dist_21"] < 0,
        },
        "Combo_AdxMacdStructure": {
            "buy": lambda r: r["adx"] > 20 and r["macd_histogram"] > 0 and r["hh_count"] >= 2,
            "sell": lambda r: r["adx"] > 20 and r["macd_histogram"] < 0 and r["ll_count"] >= 2,
        },
        "Combo_Full5": {
            "buy": lambda r: (r["trend_4h"] > 0 and r["adx"] > 20 and r["macd_histogram"] > 0
                             and r["rsi"] > 40 and r["rsi"] < 70 and r["ema_dist_21"] > 0),
            "sell": lambda r: (r["trend_4h"] < 0 and r["adx"] > 20 and r["macd_histogram"] < 0
                             and r["rsi"] < 60 and r["rsi"] > 30 and r["ema_dist_21"] < 0),
        },
        "Combo_TrendStructureVol": {
            "buy": lambda r: (r["trend_4h"] > 0 and r["hh_count"] >= 2
                             and r["vol_ratio"] > 1.0 and r["obv_trend"] > 0),
            "sell": lambda r: (r["trend_4h"] < 0 and r["ll_count"] >= 2
                             and r["vol_ratio"] > 1.0 and r["obv_trend"] < 0),
        },
        "Combo_MomentumConfluence": {
            "buy": lambda r: (r["rsi"] > 45 and r["rsi"] < 65 and r["macd_hist_growing"] == 1
                             and r["macd_histogram"] > 0 and r["price_chg_1h"] > 0),
            "sell": lambda r: (r["rsi"] < 55 and r["rsi"] > 35 and r["macd_hist_growing"] == 1
                             and r["macd_histogram"] < 0 and r["price_chg_1h"] < 0),
        },
        "Combo_TrendMomentumEma": {
            "buy": lambda r: (r["trend_4h"] >= 0 and r["trend_1h"] > 0
                             and r["macd_histogram"] > 0 and r["ema_dist_21"] > 0
                             and r["rsi"] < 70),
            "sell": lambda r: (r["trend_4h"] <= 0 and r["trend_1h"] < 0
                             and r["macd_histogram"] < 0 and r["ema_dist_21"] < 0
                             and r["rsi"] > 30),
        },
        "Combo_VolStructureMacd": {
            "buy": lambda r: (r["vol_ratio"] > 1.3 and r["hh_count"] >= 2
                             and r["macd_histogram"] > 0 and r["obv_trend"] > 2),
            "sell": lambda r: (r["vol_ratio"] > 1.3 and r["ll_count"] >= 2
                             and r["macd_histogram"] < 0 and r["obv_trend"] < -2),
        },
    }
    
    combo_results = []
    
    print(f"\n  {'Combo':30s} {'Buys':>5s} {'BuyWR':>6s} {'BuyPnl':>8s} {'Sells':>5s} {'SellWR':>7s} {'SellPnl':>8s} {'TotalWR':>8s} {'AvgPnl':>8s} {'Score':>6s}")
    print("  " + "-" * 105)
    
    for name, filters in combos.items():
        buys = [r for r in records if filters["buy"](r)]
        sells = [r for r in records if filters["sell"](r)]
        
        buy_wins = sum(1 for r in buys if r["buy_pnl_pct"] > 0)
        sell_wins = sum(1 for r in sells if r["sell_pnl_pct"] > 0)
        buy_wr = buy_wins / len(buys) * 100 if buys else 0
        sell_wr = sell_wins / len(sells) * 100 if sells else 0
        buy_avg = sum(r["buy_pnl_pct"] for r in buys) / len(buys) if buys else 0
        sell_avg = sum(r["sell_pnl_pct"] for r in sells) / len(sells) if sells else 0
        
        total_trades = len(buys) + len(sells)
        total_wins = buy_wins + sell_wins
        total_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
        avg_pnl = (sum(r["buy_pnl_pct"] for r in buys) + sum(r["sell_pnl_pct"] for r in sells)) / total_trades if total_trades > 0 else 0
        
        # Score = WR * avg_pnl (positive = profitable)
        score = round(total_wr * avg_pnl / 100, 2) if total_trades >= 5 else 0
        
        combo_results.append({
            "name": name, "buys": len(buys), "sells": len(sells),
            "buy_wr": round(buy_wr, 1), "sell_wr": round(sell_wr, 1),
            "buy_avg_pnl": round(buy_avg, 2), "sell_avg_pnl": round(sell_avg, 2),
            "total_wr": round(total_wr, 1), "avg_pnl": round(avg_pnl, 2),
            "score": score, "total_trades": total_trades,
        })
        
        print(f"  {name:30s} {len(buys):5d} {buy_wr:5.1f}% {buy_avg:>+7.2f}% "
              f"{len(sells):5d} {sell_wr:>6.1f}% {sell_avg:>+7.2f}% "
              f"{total_wr:>7.1f}% {avg_pnl:>+7.2f}% {score:>+5.2f}")
    
    # Sort by score
    combo_results.sort(key=lambda x: x["score"], reverse=True)
    
    print(f"\n  ═══ RANKING BY PROFITABILITY SCORE (WR × AvgPnl) ═══")
    print(f"  {'Rank':>4s} {'Combo':30s} {'Trades':>7s} {'WinRate':>8s} {'AvgPnl':>8s} {'Score':>7s}")
    print("  " + "-" * 70)
    for rank, cr in enumerate(combo_results, 1):
        icon = "🏆" if rank <= 3 else "  "
        print(f"  {icon}{rank:2d} {cr['name']:30s} {cr['total_trades']:7d} "
              f"{cr['total_wr']:>7.1f}% {cr['avg_pnl']:>+7.2f}% {cr['score']:>+6.2f}")
    
    return combo_results


# ═══════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════

async def main():
    fetcher = HistoricalDataFetcher()
    end = datetime.utcnow()
    
    print("╔" + "═" * 70 + "╗")
    print("║  INDICATOR LABORATORY — Data-Driven Strategy Optimization         ║")
    print("║  Collecting ALL indicator values at EVERY evaluation point         ║")
    print("║  Then: statistical analysis → optimal combination discovery       ║")
    print("╚" + "═" * 70 + "╝")
    
    # FNG history
    import httpx
    fng_history = {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.alternative.me/fng/?limit=95")
            if r.status_code == 200:
                for d in r.json().get("data", []):
                    ts = int(d["timestamp"])
                    fng_history[datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")] = int(d["value"])
    except: pass
    print(f"  FNG: {len(fng_history)} days")
    
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    all_records = []
    
    # 90 day data for maximum sample size
    days = 90
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp() * 1000)
    
    for symbol in SYMBOLS:
        print(f"\n  📈 {symbol} (90d)")
        t0 = time.time()
        
        lookback_start = start - timedelta(days=15)
        
        try:
            print("    ⏳ Fetching data...", end=" ", flush=True)
            klines, fr, ls, oi = await asyncio.gather(
                fetcher.fetch_klines(symbol, INTERVAL, lookback_start, end),
                fetcher.fetch_funding_rate(symbol, start, end),
                fetcher.fetch_long_short_ratio(symbol, start, end),
                fetcher.fetch_oi_history(symbol, start, end),
            )
            print(f"{len(klines)} candles")
            
            if len(klines) < 200:
                print("    SKIP")
                continue
            
            fr_l = _SortedLookup(fr)
            ls_l = _SortedLookup(ls)
            oi_l = _SortedLookup(oi)
            
            print("    ⏳ Collecting indicator data...", end=" ", flush=True)
            records = await collect_trade_data(symbol, klines, fr_l, ls_l, oi_l, fng_history, start_ms)
            print(f"{len(records)} evaluation points")
            
            for r in records:
                r["symbol"] = symbol
            all_records.extend(records)
            
            elapsed = time.time() - t0
            print(f"    ✅ Done ({elapsed:.1f}s)")
            
        except Exception as e:
            print(f"    ❌ Error: {e}")
            import traceback; traceback.print_exc()
        
        await asyncio.sleep(0.5)
    
    print(f"\n  ═══════════════════════════════════════════════")
    print(f"  Total evaluation points: {len(all_records)}")
    print(f"  ═══════════════════════════════════════════════")
    
    # Baseline stats
    buy_wr = sum(1 for r in all_records if r["buy_pnl_pct"] > 0) / len(all_records) * 100
    sell_wr = sum(1 for r in all_records if r["sell_pnl_pct"] > 0) / len(all_records) * 100
    buy_avg = sum(r["buy_pnl_pct"] for r in all_records) / len(all_records)
    sell_avg = sum(r["sell_pnl_pct"] for r in all_records) / len(all_records)
    print(f"  Baseline BUY:  WR={buy_wr:.1f}% AvgPnl={buy_avg:+.2f}%")
    print(f"  Baseline SELL: WR={sell_wr:.1f}% AvgPnl={sell_avg:+.2f}%")
    
    # Phase 2: Analysis
    indicator_results, sorted_indicators = analyze_indicators(all_records)
    
    # Phase 3: Combo testing
    combo_results = test_indicator_combos(all_records, sorted_indicators)
    
    # Save everything
    os.makedirs(r"D:\All_in_AI\Trading_system\data", exist_ok=True)
    
    # Save indicator analysis
    save_path = r"D:\All_in_AI\Trading_system\data\indicator_analysis.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_records": len(all_records),
            "baseline": {"buy_wr": round(buy_wr,1), "sell_wr": round(sell_wr,1),
                         "buy_avg_pnl": round(buy_avg,2), "sell_avg_pnl": round(sell_avg,2)},
            "indicator_ranking": [{**v, "key": k} for k, v in sorted_indicators[:30]],
            "combo_ranking": combo_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 Saved to {save_path}")
    
    print(f"\n{'═' * 70}")
    print(f"  INDICATOR LAB COMPLETE")
    print(f"{'═' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
