# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  ADVANCED STRATEGY LAB V2
  
  根本改进:
  1. 多时间框架: 4H构建趋势上下文 → 1H精确入场
  2. 动态出场: 移动止盈(锁住利润) + 反向信号出场
  3. 真实资金曲线: 复利模拟, 追踪每一笔交易
  4. 多种入场模式: 趋势延续/回调入场/突破入场
  5. 更极端组合: 强趋势+大量+结构+动量 全部汇合
═══════════════════════════════════════════════════════════════════
"""
import asyncio, sys, os, json, time, math
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, r"D:\All_in_AI\Trading_system")

from backend.archive.trading.backtester_v2 import (
    HistoricalDataFetcher, _SortedLookup,
    calc_ema, calc_rsi, calc_adx, trend_direction,
)
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")


def resample_to_4h(klines_1h):
    """把1H K线合并为4H"""
    out = []
    for i in range(0, len(klines_1h)-3, 4):
        chunk = klines_1h[i:i+4]
        out.append({
            "ts": chunk[0]["ts"],
            "open": chunk[0]["open"],
            "high": max(k["high"] for k in chunk),
            "low": min(k["low"] for k in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(k["volume"] for k in chunk),
        })
    return out


def get_4h_context(closes_4h, highs_4h, lows_4h, volumes_4h):
    """4H时间框架的趋势上下文"""
    if len(closes_4h) < 30:
        return None
    trend = trend_direction(closes_4h, 10, 25)
    adx = calc_adx(highs_4h, lows_4h, closes_4h) if len(closes_4h) >= 30 else 15
    rsi = calc_rsi(closes_4h)
    ema10 = calc_ema(closes_4h, 10)
    ema25 = calc_ema(closes_4h, 25)
    strong_bull = trend > 0 and ema10 > ema25 and adx > 20
    strong_bear = trend < 0 and ema10 < ema25 and adx > 20
    return {
        "trend": trend, "adx": adx, "rsi": rsi,
        "strong_bull": strong_bull, "strong_bear": strong_bear,
        "ema10": ema10, "ema25": ema25,
    }


def get_1h_signals(closes, highs, lows, opens, volumes, price):
    """1H时间框架的精确入场信号"""
    if len(closes) < 50:
        return None
    
    rsi = calc_rsi(closes)
    adx = calc_adx(highs, lows, closes)
    atr = sum(highs[i]-lows[i] for i in range(-14,0)) / 14
    
    # MACD
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd = ema12 - ema26
    macd_hist = 0
    if len(closes) >= 35:
        k12, k26 = 2/13, 2/27
        e12, e26 = sum(closes[:12])/12, sum(closes[:26])/26
        mv = []
        for i in range(26, len(closes)):
            e12 = closes[i]*k12+e12*(1-k12)
            e26 = closes[i]*k26+e26*(1-k26)
            mv.append(e12-e26)
        if len(mv) >= 9:
            macd_hist = mv[-1] - calc_ema(mv, 9)
    
    # EMAs
    ema21 = calc_ema(closes[-30:], 21)
    ema50 = calc_ema(closes, 50) if len(closes)>=50 else ema21
    above_ema21 = price > ema21
    above_ema50 = price > ema50
    
    # Volume
    va = sum(volumes[-20:])/min(20,len(volumes))
    vr = volumes[-1]/va if va>0 else 1
    obv = sum(1 if closes[i]>closes[i-1] else -1 for i in range(-10,0))
    
    # BB
    bp = min(20,len(closes))
    bc = closes[-bp:]
    bm = sum(bc)/bp
    bs = (sum((c-bm)**2 for c in bc)/bp)**0.5
    bu, bl = bm+2*bs, bm-2*bs
    bbp = (price-bl)/(bu-bl)*100 if bu!=bl else 50
    
    # Structure
    sl = min(60, len(closes))
    rh = [highs[-i] for i in range(1, sl, 3)]
    rl = [lows[-i] for i in range(1, sl, 3)]
    hh = sum(1 for i in range(1,min(6,len(rh))) if rh[i-1]>rh[i])
    ll = sum(1 for i in range(1,min(6,len(rl))) if rl[i-1]<rl[i])
    hl = sum(1 for i in range(1,min(6,len(rl))) if rl[i-1]>rl[i])
    
    # Candle pattern
    cg = sum(1 for i in range(-3,0) if closes[i]>opens[i])
    cr = sum(1 for i in range(-3,0) if closes[i]<opens[i])
    
    # Pullback detection: price crossed below then back above EMA21
    pullback_buy = (closes[-3] < ema21 or closes[-2] < ema21) and price > ema21 and price < ema21 * 1.005
    pullback_sell = (closes[-3] > ema21 or closes[-2] > ema21) and price < ema21 and price > ema21 * 0.995
    
    # Breakout: price above recent high with volume
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    breakout_buy = price >= recent_high * 0.999 and vr > 1.5
    breakout_sell = price <= recent_low * 1.001 and vr > 1.5
    
    return {
        "rsi": rsi, "adx": adx, "atr": atr,
        "macd_hist": macd_hist,
        "above_ema21": above_ema21, "above_ema50": above_ema50,
        "ema21": ema21,
        "vr": vr, "obv": obv, "bbp": bbp,
        "hh": hh, "ll": ll, "hl": hl,
        "cg": cg, "cr": cr,
        "pullback_buy": pullback_buy, "pullback_sell": pullback_sell,
        "breakout_buy": breakout_buy, "breakout_sell": breakout_sell,
    }


# ═══════════════════════════════════════
#  Strategy Definitions
# ═══════════════════════════════════════

STRATEGIES = {
    "S1_TrendContinuation": {
        "desc": "4H强趋势+1H MACD同向+量能确认+结构完整",
        "entry_buy": lambda ctx, sig: (
            ctx["strong_bull"] and sig["macd_hist"] > 0 
            and sig["above_ema21"] and sig["obv"] > 2 
            and sig["hh"] >= 2 and sig["adx"] > 18
            and 35 < sig["rsi"] < 70
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["strong_bear"] and sig["macd_hist"] < 0
            and not sig["above_ema21"] and sig["obv"] < -2
            and sig["ll"] >= 2 and sig["adx"] > 18
            and 30 < sig["rsi"] < 65
        ),
        "sl_atr": 2.0, "tp_atr": 6.0, "trailing": True, "trail_activation": 0.3,
    },
    "S2_Pullback": {
        "desc": "4H趋势+1H回调到EMA21后反弹入场",
        "entry_buy": lambda ctx, sig: (
            ctx["strong_bull"] and sig["pullback_buy"]
            and sig["macd_hist"] > 0 and sig["rsi"] < 55
            and sig["vr"] > 0.8
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["strong_bear"] and sig["pullback_sell"]
            and sig["macd_hist"] < 0 and sig["rsi"] > 45
            and sig["vr"] > 0.8
        ),
        "sl_atr": 1.5, "tp_atr": 4.0, "trailing": True, "trail_activation": 0.4,
    },
    "S3_Breakout": {
        "desc": "4H趋势+1H突破近期高低点+放量",
        "entry_buy": lambda ctx, sig: (
            ctx["trend"] > 0 and sig["breakout_buy"]
            and sig["macd_hist"] > 0 and sig["adx"] > 22
            and sig["above_ema21"]
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["trend"] < 0 and sig["breakout_sell"]
            and sig["macd_hist"] < 0 and sig["adx"] > 22
            and not sig["above_ema21"]
        ),
        "sl_atr": 2.0, "tp_atr": 5.0, "trailing": True, "trail_activation": 0.3,
    },
    "S4_VolumeSurge": {
        "desc": "4H趋势+爆量(2x)+动量+结构",
        "entry_buy": lambda ctx, sig: (
            ctx["strong_bull"] and sig["vr"] > 2.0 and sig["obv"] > 4
            and sig["macd_hist"] > 0 and sig["hh"] >= 2
            and sig["above_ema21"] and sig["rsi"] < 70
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["strong_bear"] and sig["vr"] > 2.0 and sig["obv"] < -4
            and sig["macd_hist"] < 0 and sig["ll"] >= 2
            and not sig["above_ema21"] and sig["rsi"] > 30
        ),
        "sl_atr": 1.5, "tp_atr": 4.5, "trailing": True, "trail_activation": 0.35,
    },
    "S5_UltraStrict": {
        "desc": "极端严格: 全部8个条件同向+4H强趋势+爆量",
        "entry_buy": lambda ctx, sig: (
            ctx["strong_bull"] and ctx["adx"] > 25
            and sig["macd_hist"] > 0 and sig["adx"] > 22
            and sig["above_ema21"] and sig["above_ema50"]
            and sig["vr"] > 1.5 and sig["obv"] > 3
            and sig["hh"] >= 3 and sig["hl"] >= 2
            and sig["cg"] >= 2 and 40 < sig["rsi"] < 65
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["strong_bear"] and ctx["adx"] > 25
            and sig["macd_hist"] < 0 and sig["adx"] > 22
            and not sig["above_ema21"] and not sig["above_ema50"]
            and sig["vr"] > 1.5 and sig["obv"] < -3
            and sig["ll"] >= 3 
            and sig["cr"] >= 2 and 35 < sig["rsi"] < 60
        ),
        "sl_atr": 2.0, "tp_atr": 8.0, "trailing": True, "trail_activation": 0.25,
    },
    "S6_AntiTrend_MeanRevert": {
        "desc": "4H趋势+1H超卖反弹(非逆势,是回调后的顺势)",
        "entry_buy": lambda ctx, sig: (
            ctx["strong_bull"] and sig["bbp"] < 25
            and sig["rsi"] < 35 and sig["macd_hist"] > -0.001
            and sig["above_ema50"]
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["strong_bear"] and sig["bbp"] > 75
            and sig["rsi"] > 65 and sig["macd_hist"] < 0.001
            and not sig["above_ema50"]
        ),
        "sl_atr": 1.0, "tp_atr": 2.0, "trailing": True, "trail_activation": 0.5,
    },
    "S7_Momentum_Burst": {
        "desc": "连续阳/阴线+放量+MACD加速+结构突破",
        "entry_buy": lambda ctx, sig: (
            ctx["trend"] >= 0 and sig["cg"] >= 3  # 3连阳
            and sig["vr"] > 1.5 and sig["macd_hist"] > 0
            and sig["hh"] >= 2 and sig["above_ema21"]
            and sig["adx"] > 20
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["trend"] <= 0 and sig["cr"] >= 3  # 3连阴
            and sig["vr"] > 1.5 and sig["macd_hist"] < 0
            and sig["ll"] >= 2 and not sig["above_ema21"]
            and sig["adx"] > 20
        ),
        "sl_atr": 1.5, "tp_atr": 5.0, "trailing": True, "trail_activation": 0.3,
    },
    "S8_Hybrid_Best": {
        "desc": "结合前面数据:中期趋势+MACD+量+结构(前面验证最优)",
        "entry_buy": lambda ctx, sig: (
            ctx["trend"] > 0 and ctx["adx"] > 18
            and sig["macd_hist"] > 0
            and sig["vr"] > 1.2 and sig["obv"] > 2
            and sig["hh"] >= 2 and sig["above_ema21"]
        ),
        "entry_sell": lambda ctx, sig: (
            ctx["trend"] < 0 and ctx["adx"] > 18
            and sig["macd_hist"] < 0
            and sig["vr"] > 1.2 and sig["obv"] < -2
            and sig["ll"] >= 2 and not sig["above_ema21"]
        ),
        "sl_atr": 2.0, "tp_atr": 6.0, "trailing": True, "trail_activation": 0.3,
    },
}


async def run_portfolio_sim(strategy_name, strat, symbol, klines_1h, klines_4h, 
                            fr_l, start_ms, period_days):
    """真实资金曲线模拟"""
    INIT_BAL = 1000.0
    RISK_PCT = 2.0
    COOLDOWN = 6  # 6h cooldown (6 bars on 1h)
    MAX_HOLD = 48  # 48h max
    MAX_DD_PAUSE = 15  # 15% DD pause trading for 24h
    
    balance = INIT_BAL
    peak_balance = INIT_BAL
    position = None
    trades = []
    last_trade_bar = -999
    consecutive_losses = 0
    paused_until = -1
    equity_curve = []
    
    # Build 1h arrays
    closes, highs, lows, opens, volumes = [], [], [], [], []
    
    # Build 4h arrays
    c4, h4, l4, v4 = [], [], [], []
    
    # Map 4h candles by timestamp for context
    _4h_idx = 0
    
    for idx, k in enumerate(klines_1h):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])
        
        # Update 4h context when a new 4h candle closes
        while _4h_idx < len(klines_4h) and klines_4h[_4h_idx]["ts"] <= k["ts"]:
            kk = klines_4h[_4h_idx]
            c4.append(kk["close"])
            h4.append(kk["high"])
            l4.append(kk["low"])
            v4.append(kk["volume"])
            _4h_idx += 1
        
        if len(closes) < 50 or len(c4) < 30 or k["ts"] < start_ms:
            continue
        
        price = k["close"]
        ts = k["ts"]
        
        # Record equity
        unrealized = 0
        if position:
            if position["side"] == "buy":
                unrealized = (price - position["entry"])/position["entry"] * position["value"]
            else:
                unrealized = (position["entry"] - price)/position["entry"] * position["value"]
        equity_curve.append({"ts": ts, "equity": round(balance + unrealized, 2)})
        
        # DD check
        current_dd = (peak_balance - balance)/peak_balance*100 if peak_balance > 0 else 0
        if current_dd >= MAX_DD_PAUSE and not position:
            if idx < paused_until:
                continue
            paused_until = idx + 24  # pause 24h
            continue
        
        # --- Position management ---
        if position:
            bars_in = idx - position["bar"]
            atr = position["atr"]
            sl, tp = position["sl"], position["tp"]
            
            hit_sl = (position["side"]=="buy" and k["low"]<=sl) or \
                     (position["side"]=="sell" and k["high"]>=sl)
            hit_tp = (position["side"]=="buy" and k["high"]>=tp) or \
                     (position["side"]=="sell" and k["low"]<=tp)
            timeout = bars_in >= MAX_HOLD
            
            # Trailing stop
            if strat.get("trailing") and not hit_sl and not hit_tp:
                act = strat.get("trail_activation", 0.3)
                tp_dist = abs(tp - position["entry"])
                
                if position["side"] == "buy":
                    profit_pct = (price - position["entry"]) / position["entry"]
                    if profit_pct >= act * (tp_dist / position["entry"]):
                        new_sl = max(sl, position["entry"] + (price - position["entry"]) * 0.5)
                        if new_sl > sl:
                            position["sl"] = round(new_sl, 6)
                            sl = position["sl"]
                else:
                    profit_pct = (position["entry"] - price) / position["entry"]
                    if profit_pct >= act * (tp_dist / position["entry"]):
                        new_sl = min(sl, position["entry"] - (position["entry"] - price) * 0.5)
                        if new_sl < sl:
                            position["sl"] = round(new_sl, 6)
                            sl = position["sl"]
            
            # Check exits
            if hit_sl or hit_tp or timeout:
                if hit_sl:
                    ep = sl
                    reason = "sl"
                elif hit_tp:
                    ep = tp
                    reason = "tp"
                else:
                    ep = price
                    reason = "timeout"
                
                if position["side"] == "buy":
                    pnl_pct = (ep - position["entry"]) / position["entry"]
                else:
                    pnl_pct = (position["entry"] - ep) / position["entry"]
                
                pnl_dollar = pnl_pct * position["value"]
                balance += pnl_dollar
                peak_balance = max(peak_balance, balance)
                
                trades.append({
                    "side": position["side"],
                    "entry": position["entry"],
                    "exit": round(ep, 2),
                    "pnl_pct": round(pnl_pct * 100, 3),
                    "pnl_dollar": round(pnl_dollar, 2),
                    "bars": bars_in,
                    "reason": reason,
                    "balance_after": round(balance, 2),
                })
                
                consecutive_losses = consecutive_losses + 1 if pnl_dollar <= 0 else 0
                last_trade_bar = idx
                position = None
            
            continue
        
        # --- Entry logic ---
        if balance <= 20:
            continue
        if idx - last_trade_bar < COOLDOWN:
            continue
        if consecutive_losses >= 3:
            consecutive_losses = 0
            last_trade_bar = idx + 12  # extra cooldown
            continue
        
        # Get contexts
        ctx = get_4h_context(c4, h4, l4, v4)
        if not ctx:
            continue
        sig = get_1h_signals(closes, highs, lows, opens, volumes, price)
        if not sig:
            continue
        
        atr = sig["atr"]
        if atr <= 0:
            continue
        
        # Check entry
        side = None
        if strat["entry_buy"](ctx, sig):
            side = "buy"
        elif strat["entry_sell"](ctx, sig):
            side = "sell"
        
        if not side:
            continue
        
        # Position sizing
        sl_dist = atr * strat["sl_atr"]
        tp_dist = atr * strat["tp_atr"]
        risk_dollar = balance * RISK_PCT / 100
        pos_value = risk_dollar / (sl_dist / price)
        pos_value = min(pos_value, balance * 5)  # Max 5x
        
        if side == "buy":
            sl_price = price - sl_dist
            tp_price = price + tp_dist
        else:
            sl_price = price + sl_dist
            tp_price = price - tp_dist
        
        position = {
            "side": side, "entry": price,
            "sl": round(sl_price, 6), "tp": round(tp_price, 6),
            "value": pos_value, "atr": atr, "bar": idx,
        }
        last_trade_bar = idx
    
    # Close remaining
    if position:
        price = closes[-1]
        if position["side"]=="buy":
            pnl_pct = (price-position["entry"])/position["entry"]
        else:
            pnl_pct = (position["entry"]-price)/position["entry"]
        pnl_d = pnl_pct * position["value"]
        balance += pnl_d
        trades.append({
            "side": position["side"], "pnl_pct": round(pnl_pct*100,3),
            "pnl_dollar": round(pnl_d,2), "reason": "end",
            "bars": len(klines_1h)-1-position["bar"],
            "balance_after": round(balance, 2),
        })
    
    # Stats
    if not trades:
        return {
            "strategy": strategy_name, "symbol": symbol,
            "trades": 0, "win_rate": 0, "roi_pct": 0,
            "max_dd": 0, "pf": 0, "sharpe": 0,
            "final_balance": INIT_BAL, "avg_pnl_pct": 0, "avg_bars": 0,
            "wins": 0, "avg_win": 0, "avg_loss": 0,
        }
    
    wins = [t for t in trades if t["pnl_dollar"] > 0]
    losses_l = [t for t in trades if t["pnl_dollar"] <= 0]
    wr = len(wins)/len(trades)*100
    roi = (balance - INIT_BAL)/INIT_BAL*100
    
    win_sum = sum(t["pnl_dollar"] for t in wins) if wins else 0
    loss_sum = abs(sum(t["pnl_dollar"] for t in losses_l)) if losses_l else 0
    pf = win_sum/loss_sum if loss_sum > 0 else 999
    
    avg_pnl = sum(t["pnl_pct"] for t in trades)/len(trades)
    
    # Max drawdown from equity curve
    max_dd = 0
    if equity_curve:
        peak_eq = equity_curve[0]["equity"]
        for e in equity_curve:
            peak_eq = max(peak_eq, e["equity"])
            dd = (peak_eq - e["equity"])/peak_eq*100 if peak_eq > 0 else 0
            max_dd = max(max_dd, dd)
    
    # Sharpe
    sharpe = 0
    if len(trades) >= 5:
        rets = [t["pnl_pct"] for t in trades]
        mr = sum(rets)/len(rets)
        sr = (sum((r-mr)**2 for r in rets)/len(rets))**0.5
        if sr > 0:
            ann = (365/period_days) * len(trades)
            sharpe = round(mr/sr * math.sqrt(ann), 2)
    
    avg_bars = sum(t.get("bars",0) for t in trades)/len(trades)
    
    return {
        "strategy": strategy_name,
        "symbol": symbol,
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": round(wr, 1),
        "roi_pct": round(roi, 1),
        "max_dd": round(max_dd, 1),
        "pf": round(pf, 2),
        "sharpe": sharpe,
        "final_balance": round(balance, 2),
        "avg_pnl_pct": round(avg_pnl, 3),
        "avg_bars": round(avg_bars, 1),
        "avg_win": round(sum(t["pnl_pct"] for t in wins)/len(wins), 3) if wins else 0,
        "avg_loss": round(sum(t["pnl_pct"] for t in losses_l)/len(losses_l), 3) if losses_l else 0,
    }


async def main():
    fetcher = HistoricalDataFetcher()
    end = datetime.utcnow()
    
    print("╔" + "═"*70 + "╗")
    print("║  ADVANCED STRATEGY LAB V2                                        ║")
    print("║  Multi-TF | Dynamic Trailing | Real Portfolio Simulation          ║")
    print("║  8 Strategies × 3 Coins × 90 days                                ║")
    print("╚" + "═"*70 + "╝")
    
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    days = 90
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp()*1000)
    
    all_results = []
    
    for symbol in SYMBOLS:
        print(f"\n  📈 {symbol}")
        t0 = time.time()
        
        lookback = start - timedelta(days=20)
        
        try:
            print("    ⏳ Data...", end=" ", flush=True)
            klines_1h, fr, _, _ = await asyncio.gather(
                fetcher.fetch_klines(symbol, "1h", lookback, end),
                fetcher.fetch_funding_rate(symbol, start, end),
                fetcher.fetch_long_short_ratio(symbol, start, end),
                fetcher.fetch_oi_history(symbol, start, end),
            )
            print(f"{len(klines_1h)} 1H candles", end=" ", flush=True)
            
            # Build 4H from 1H
            klines_4h = resample_to_4h(klines_1h)
            print(f"| {len(klines_4h)} 4H candles")
            
            fr_l = _SortedLookup(fr)
            
            for sname, strat in STRATEGIES.items():
                r = await run_portfolio_sim(
                    sname, strat, symbol, klines_1h, klines_4h, fr_l, start_ms, days,
                )
                all_results.append(r)
                icon = "🟢" if r["roi_pct"] > 0 else "🔴" if r["roi_pct"] < -5 else "⚪"
                print(f"    {icon} {sname:25s} | {r['trades']:3d}T WR={r['win_rate']:5.1f}% "
                      f"ROI={r['roi_pct']:>+7.1f}% DD={r['max_dd']:5.1f}% "
                      f"PF={r['pf']:5.2f} ${r['final_balance']:>8.2f}")
            
            print(f"    ✅ {time.time()-t0:.1f}s")
            
        except Exception as e:
            print(f"    ❌ {e}")
            import traceback; traceback.print_exc()
        
        await asyncio.sleep(0.5)
    
    # Aggregate
    print(f"\n{'═'*110}")
    print(f"  AGGREGATED RESULTS (averaged across 3 symbols)")
    print(f"{'═'*110}")
    print(f"  {'Rank':>4s} {'Strategy':25s} {'AvgROI':>8s} {'AvgWR':>7s} {'AvgDD':>7s} {'AvgPF':>6s} {'Sharpe':>7s} {'Trades':>7s} {'AvgPnl%':>8s}")
    print(f"  {'-'*95}")
    
    agg = defaultdict(list)
    for r in all_results:
        agg[r["strategy"]].append(r)
    
    ranked = sorted(agg.items(), 
                    key=lambda x: sum(r["roi_pct"] for r in x[1])/len(x[1]), reverse=True)
    
    for i, (sname, runs) in enumerate(ranked, 1):
        n = len(runs)
        avg_roi = sum(r["roi_pct"] for r in runs)/n
        avg_wr = sum(r["win_rate"] for r in runs)/n
        avg_dd = sum(r["max_dd"] for r in runs)/n
        avg_pf = sum(r["pf"] for r in runs)/n
        avg_sh = sum(r["sharpe"] for r in runs)/n
        total_t = sum(r["trades"] for r in runs)
        avg_pnl = sum(r["avg_pnl_pct"] for r in runs)/n
        profitable = sum(1 for r in runs if r["roi_pct"] > 0)
        
        icon = "🏆" if i <= 3 and avg_roi > 0 else "  "
        cons = f"[{profitable}/{n}]"
        pm = "+" if avg_roi >= 0 else ""
        
        detail = " | ".join(f"{r['symbol'][:3]}:{r['roi_pct']:+.0f}%/WR{r['win_rate']:.0f}%" for r in runs)
        
        print(f"  {icon}{i:2d} {sname:25s} {pm}{avg_roi:>7.1f}% {avg_wr:>6.1f}% "
              f"{avg_dd:>6.1f}% {avg_pf:>5.2f} {avg_sh:>6.2f} {total_t:>7d} "
              f"{avg_pnl:>+7.3f}% {cons} {detail}")
    
    # Save
    os.makedirs(r"D:\All_in_AI\Trading_system\data", exist_ok=True)
    save_path = r"D:\All_in_AI\Trading_system\data\advanced_results.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": {"days": days, "init_bal": 1000, "risk_pct": 2.0},
            "results": all_results,
            "ranking": [{"strategy": sname, 
                         "avg_roi": round(sum(r["roi_pct"] for r in runs)/len(runs), 1),
                         "avg_wr": round(sum(r["win_rate"] for r in runs)/len(runs), 1),
                         "avg_pf": round(sum(r["pf"] for r in runs)/len(runs), 2),
                         "profitable_in": sum(1 for r in runs if r["roi_pct"]>0),
                         "per_symbol": runs,
                        } for sname, runs in ranked],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 {save_path}")
    print(f"\n{'═'*70}\n  ADVANCED LAB COMPLETE\n{'═'*70}")


if __name__ == "__main__":
    asyncio.run(main())
