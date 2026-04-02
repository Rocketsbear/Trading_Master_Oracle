# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════
  FULL PARAMETER SWEEP — 从零寻找盈利策略
  
  扫描维度:
  1. K线周期: 15m / 1h / 4h
  2. SL/TP比率: 多种组合
  3. 指标入场条件: 从松到严
  4. 方向: 做多 / 做空 / 双向
  
  目标: 找到 WR>55% 或 R:R>2 + WR>40% 的可持续盈利组合
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


# ═══════════════════════════════════════
#  Indicator Engine
# ═══════════════════════════════════════

def get_indicators(closes, highs, lows, opens, volumes, price):
    """计算所有指标的原始值"""
    if len(closes) < 60:
        return None
    
    rsi = calc_rsi(closes)
    adx = calc_adx(highs, lows, closes)
    atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd = ema12 - ema26
    
    # MACD histogram
    macd_hist = 0
    if len(closes) >= 35:
        k12, k26 = 2/13, 2/27
        e12 = sum(closes[:12])/12
        e26 = sum(closes[:26])/26
        mv = []
        for i in range(26, len(closes)):
            e12 = closes[i]*k12 + e12*(1-k12)
            e26 = closes[i]*k26 + e26*(1-k26)
            mv.append(e12-e26)
        if len(mv) >= 9:
            sig = calc_ema(mv, 9)
            macd_hist = mv[-1] - sig
    
    ema21 = calc_ema(closes[-30:], 21)
    ema50 = calc_ema(closes, 50) if len(closes) >= 50 else ema21
    
    # Trends
    t_short = trend_direction(closes, 10, 30)
    t_mid = trend_direction(closes, 20, 50)
    
    # Volume
    va = sum(volumes[-20:])/min(20,len(volumes))
    vr = volumes[-1]/va if va > 0 else 1
    obv = sum(1 if closes[i]>closes[i-1] else -1 for i in range(-10,0))
    
    # BB
    bp = min(20, len(closes))
    bc = closes[-bp:]
    bm = sum(bc)/bp
    bs = (sum((c-bm)**2 for c in bc)/bp)**0.5
    bu, bl = bm+2*bs, bm-2*bs
    bbp = (price-bl)/(bu-bl)*100 if bu!=bl else 50
    
    # Structure
    sl = min(60, len(closes))
    rh = [highs[-i] for i in range(1, sl, 4)]
    rl = [lows[-i] for i in range(1, sl, 4)]
    hh = sum(1 for i in range(1, min(5,len(rh))) if rh[i-1]>rh[i])
    ll = sum(1 for i in range(1, min(5,len(rl))) if rl[i-1]<rl[i])
    hl = sum(1 for i in range(1, min(5,len(rl))) if rl[i-1]>rl[i])
    
    # Consecutive candles
    cg = sum(1 for i in range(-3,0) if closes[i]>opens[i])
    cr = sum(1 for i in range(-3,0) if closes[i]<opens[i])
    
    # Price change
    pc1 = (closes[-1]/closes[-2]-1)*100 if len(closes)>=2 else 0
    pc4 = (closes[-1]/closes[-5]-1)*100 if len(closes)>=5 else 0
    
    return {
        "rsi": rsi, "adx": adx, "atr": atr,
        "macd": macd, "macd_hist": macd_hist,
        "ema21_dist": (price-ema21)/ema21*100,
        "ema50_dist": (price-ema50)/ema50*100,
        "t_short": t_short, "t_mid": t_mid,
        "vr": vr, "obv": obv,
        "bbp": bbp,
        "hh": hh, "ll": ll, "hl": hl,
        "cg": cg, "cr": cr,
        "pc1": pc1, "pc4": pc4,
    }


# ═══════════════════════════════════════
#  Entry Filters (从松到严)
# ═══════════════════════════════════════

FILTERS = {
    # --- 单因子 ---
    "Trend_Mid": {
        "buy": lambda i: i["t_mid"] > 0,
        "sell": lambda i: i["t_mid"] < 0,
    },
    "MACD_Dir": {
        "buy": lambda i: i["macd_hist"] > 0,
        "sell": lambda i: i["macd_hist"] < 0,
    },
    "EMA_Above": {
        "buy": lambda i: i["ema21_dist"] > 0.3 and i["ema50_dist"] > 0,
        "sell": lambda i: i["ema21_dist"] < -0.3 and i["ema50_dist"] < 0,
    },
    "Vol_Spike": {
        "buy": lambda i: i["vr"] > 1.5 and i["obv"] > 3,
        "sell": lambda i: i["vr"] > 1.5 and i["obv"] < -3,
    },
    "Structure": {
        "buy": lambda i: i["hh"] >= 3 and i["hl"] >= 2,
        "sell": lambda i: i["ll"] >= 3,
    },
    "Pullback_Buy": {
        "buy": lambda i: i["t_mid"] > 0 and i["rsi"] < 45 and i["ema21_dist"] > 0,
        "sell": lambda i: i["t_mid"] < 0 and i["rsi"] > 55 and i["ema21_dist"] < 0,
    },
    
    # --- 双因子 ---
    "Trend+MACD": {
        "buy": lambda i: i["t_mid"] > 0 and i["macd_hist"] > 0,
        "sell": lambda i: i["t_mid"] < 0 and i["macd_hist"] < 0,
    },
    "Trend+Vol": {
        "buy": lambda i: i["t_mid"] > 0 and i["vr"] > 1.2 and i["obv"] > 2,
        "sell": lambda i: i["t_mid"] < 0 and i["vr"] > 1.2 and i["obv"] < -2,
    },
    "Trend+Structure": {
        "buy": lambda i: i["t_mid"] > 0 and i["hh"] >= 2 and i["hl"] >= 1,
        "sell": lambda i: i["t_mid"] < 0 and i["ll"] >= 2,
    },
    "MACD+Vol": {
        "buy": lambda i: i["macd_hist"] > 0 and i["vr"] > 1.3 and i["obv"] > 2,
        "sell": lambda i: i["macd_hist"] < 0 and i["vr"] > 1.3 and i["obv"] < -2,
    },
    "EMA+Structure": {
        "buy": lambda i: i["ema21_dist"] > 0 and i["hh"] >= 2,
        "sell": lambda i: i["ema21_dist"] < 0 and i["ll"] >= 2,
    },
    "Pullback_EMA": {
        "buy": lambda i: i["t_mid"] > 0 and i["bbp"] < 40 and i["ema21_dist"] > -0.5 and i["ema21_dist"] < 0.5,
        "sell": lambda i: i["t_mid"] < 0 and i["bbp"] > 60 and i["ema21_dist"] > -0.5 and i["ema21_dist"] < 0.5,
    },
    
    # --- 三因子 ---
    "Tri_TrendMacdVol": {
        "buy": lambda i: i["t_mid"] > 0 and i["macd_hist"] > 0 and i["vr"] > 1.2,
        "sell": lambda i: i["t_mid"] < 0 and i["macd_hist"] < 0 and i["vr"] > 1.2,
    },
    "Tri_TrendStructVol": {
        "buy": lambda i: i["t_mid"] > 0 and i["hh"] >= 2 and i["obv"] > 2,
        "sell": lambda i: i["t_mid"] < 0 and i["ll"] >= 2 and i["obv"] < -2,
    },
    "Tri_MacdEmaAdx": {
        "buy": lambda i: i["macd_hist"] > 0 and i["ema21_dist"] > 0 and i["adx"] > 20,
        "sell": lambda i: i["macd_hist"] < 0 and i["ema21_dist"] < 0 and i["adx"] > 20,
    },
    "Tri_PullbackConfirm": {
        "buy": lambda i: i["t_mid"] > 0 and i["rsi"] < 50 and i["macd_hist"] > 0 and i["ema21_dist"] > -0.3,
        "sell": lambda i: i["t_mid"] < 0 and i["rsi"] > 50 and i["macd_hist"] < 0 and i["ema21_dist"] < 0.3,
    },
    
    # --- 四因子+ (严格) ---
    "Quad_Full": {
        "buy": lambda i: (i["t_mid"] > 0 and i["macd_hist"] > 0 
                         and i["ema21_dist"] > 0 and i["obv"] > 2 and i["adx"] > 20),
        "sell": lambda i: (i["t_mid"] < 0 and i["macd_hist"] < 0 
                         and i["ema21_dist"] < 0 and i["obv"] < -2 and i["adx"] > 20),
    },
    "Quad_Strict": {
        "buy": lambda i: (i["t_mid"] > 0 and i["t_short"] > 0 and i["macd_hist"] > 0 
                         and i["hh"] >= 2 and i["ema21_dist"] > 0),
        "sell": lambda i: (i["t_mid"] < 0 and i["t_short"] < 0 and i["macd_hist"] < 0 
                         and i["ll"] >= 2 and i["ema21_dist"] < 0),
    },
    "Quad_VolConfirm": {
        "buy": lambda i: (i["t_mid"] > 0 and i["macd_hist"] > 0 
                         and i["vr"] > 1.3 and i["obv"] > 3 and i["hh"] >= 2),
        "sell": lambda i: (i["t_mid"] < 0 and i["macd_hist"] < 0 
                         and i["vr"] > 1.3 and i["obv"] < -3 and i["ll"] >= 2),
    },
    "Penta_Ultimate": {
        "buy": lambda i: (i["t_mid"] > 0 and i["t_short"] > 0 and i["macd_hist"] > 0 
                         and i["ema21_dist"] > 0 and i["vr"] > 1.0 and i["obv"] > 1
                         and i["hh"] >= 2 and i["adx"] > 18 and i["rsi"] < 70 and i["rsi"] > 35),
        "sell": lambda i: (i["t_mid"] < 0 and i["t_short"] < 0 and i["macd_hist"] < 0 
                         and i["ema21_dist"] < 0 and i["vr"] > 1.0 and i["obv"] < -1
                         and i["ll"] >= 2 and i["adx"] > 18 and i["rsi"] > 30 and i["rsi"] < 65),
    },
}

# SL/TP sweep
SL_TP_CONFIGS = {
    "tight_1x2x":   (1.0, 2.0),    # 1:2 R:R, tight
    "std_1.5x3x":   (1.5, 3.0),    # 1:2 R:R, standard
    "std_2x4x":     (2.0, 4.0),    # 1:2 R:R, wide
    "wide_2x6x":    (2.0, 6.0),    # 1:3 R:R
    "wider_2.5x8x": (2.5, 8.0),    # 1:3.2 R:R
    "tight_1x1.5x": (1.0, 1.5),    # 1:1.5 scalp
    "even_1.5x1.5x":(1.5, 1.5),    # 1:1 even
    "asym_1x3x":    (1.0, 3.0),    # 1:3 asymmetric 
}


def sim_trade(side, entry, atr, klines_after, sl_mult, tp_mult, max_bars=96):
    """Simulate a single trade"""
    sl_d = atr * sl_mult
    tp_d = atr * tp_mult
    
    for i, k in enumerate(klines_after):
        if i >= max_bars:
            ep = k["close"]
            pnl = ((ep-entry)/entry*100) if side=="buy" else ((entry-ep)/entry*100)
            return round(pnl,3), i, "timeout"
        
        h, l = k["high"], k["low"]
        if side == "buy":
            if l <= entry - sl_d:
                return round(-sl_d/entry*100, 3), i, "sl"
            if h >= entry + tp_d:
                return round(tp_d/entry*100, 3), i, "tp"
        else:
            if h >= entry + sl_d:
                return round(-sl_d/entry*100, 3), i, "sl"
            if l <= entry - tp_d:
                return round(tp_d/entry*100, 3), i, "tp"
    
    if not klines_after:
        return 0, 0, "nodata"
    ep = klines_after[-1]["close"]
    pnl = ((ep-entry)/entry*100) if side=="buy" else ((entry-ep)/entry*100)
    return round(pnl,3), len(klines_after), "end"


async def run_sweep(symbol, interval, klines, fr_l, ls_l, oi_l, fng_hist, start_ms, days):
    """Run full parameter sweep on one symbol/interval"""
    
    closes, highs, lows, opens, volumes = [], [], [], [], []
    eval_points = []
    
    # Determine evaluation frequency based on interval
    if interval == "15m":
        eval_every = 8    # every 2h
        max_bars = 96     # 24h
    elif interval == "1h":
        eval_every = 2    # every 2h
        max_bars = 48     # 48h for 1h candles
    else:  # 4h
        eval_every = 1    # every 4h
        max_bars = 18     # 72h for 4h candles
    
    for idx, k in enumerate(klines):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])
        
        if len(closes) < 60 or k["ts"] < start_ms:
            continue
        if idx % eval_every != 0:
            continue
        
        inds = get_indicators(closes, highs, lows, opens, volumes, k["close"])
        if not inds:
            continue
        
        future = klines[idx+1:idx+1+max_bars]
        if len(future) < 5:
            continue
        
        eval_points.append({
            "inds": inds,
            "price": k["close"],
            "atr": inds["atr"],
            "future": future,
        })
    
    # Sweep
    results = []
    
    for fname, flt in FILTERS.items():
        for sltp_name, (sl_m, tp_m) in SL_TP_CONFIGS.items():
            buy_pnls, sell_pnls = [], []
            
            for ep in eval_points:
                inds = ep["inds"]
                
                if flt["buy"](inds):
                    pnl, bars, reason = sim_trade("buy", ep["price"], ep["atr"], 
                                                  ep["future"], sl_m, tp_m, max_bars)
                    buy_pnls.append(pnl)
                
                if flt["sell"](inds):
                    pnl, bars, reason = sim_trade("sell", ep["price"], ep["atr"],
                                                  ep["future"], sl_m, tp_m, max_bars)
                    sell_pnls.append(pnl)
            
            all_pnls = buy_pnls + sell_pnls
            if len(all_pnls) < 5:
                continue
            
            n = len(all_pnls)
            wins = sum(1 for p in all_pnls if p > 0)
            wr = wins/n*100
            avg = sum(all_pnls)/n
            total = sum(all_pnls)
            
            win_sum = sum(p for p in all_pnls if p > 0)
            loss_sum = abs(sum(p for p in all_pnls if p <= 0))
            pf = win_sum/loss_sum if loss_sum > 0 else 999
            
            # Expectancy = WR × AvgWin - (1-WR) × AvgLoss
            avg_w = sum(p for p in all_pnls if p > 0)/wins if wins > 0 else 0
            avg_l = abs(sum(p for p in all_pnls if p <= 0)/(n-wins)) if (n-wins) > 0 else 0
            expectancy = (wr/100) * avg_w - (1-wr/100) * avg_l
            
            results.append({
                "filter": fname,
                "sltp": sltp_name,
                "sl_m": sl_m, "tp_m": tp_m,
                "n_trades": n,
                "n_buys": len(buy_pnls),
                "n_sells": len(sell_pnls),
                "buy_wr": round(sum(1 for p in buy_pnls if p>0)/len(buy_pnls)*100,1) if buy_pnls else 0,
                "sell_wr": round(sum(1 for p in sell_pnls if p>0)/len(sell_pnls)*100,1) if sell_pnls else 0,
                "win_rate": round(wr, 1),
                "avg_pnl": round(avg, 3),
                "total_pnl": round(total, 1),
                "profit_factor": round(pf, 2),
                "expectancy": round(expectancy, 3),
                "avg_win": round(avg_w, 3),
                "avg_loss": round(avg_l, 3),
            })
    
    return eval_points, results


async def fetch_fng(days):
    import httpx
    fng = {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.alternative.me/fng/?limit={days+5}")
            if r.status_code == 200:
                for d in r.json().get("data", []):
                    fng[datetime.utcfromtimestamp(int(d["timestamp"])).strftime("%Y-%m-%d")] = int(d["value"])
    except: pass
    return fng


async def main():
    fetcher = HistoricalDataFetcher()
    end = datetime.utcnow()
    
    print("╔" + "═"*70 + "╗")
    print("║  FULL PARAMETER SWEEP — Finding Profitable Strategy              ║")
    print("║  21 Filters × 8 SL/TP × 2 Timeframes × 3 Coins                  ║")
    print("╚" + "═"*70 + "╝")
    
    fng = await fetch_fng(95)
    
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    INTERVALS = ["1h"]  # Focus on 1h for less noise
    days = 90
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp()*1000)
    
    all_results = []
    
    for interval in INTERVALS:
        for symbol in SYMBOLS:
            print(f"\n  📈 {symbol} {interval} ({days}d)")
            t0 = time.time()
            
            lookback = start - timedelta(days=15)
            
            try:
                print("    ⏳ Data...", end=" ", flush=True)
                klines, fr, ls, oi = await asyncio.gather(
                    fetcher.fetch_klines(symbol, interval, lookback, end),
                    fetcher.fetch_funding_rate(symbol, start, end),
                    fetcher.fetch_long_short_ratio(symbol, start, end),
                    fetcher.fetch_oi_history(symbol, start, end),
                )
                print(f"{len(klines)}K", end=" ", flush=True)
                
                if len(klines) < 100:
                    print("SKIP")
                    continue
                
                fr_l = _SortedLookup(fr)
                ls_l = _SortedLookup(ls)
                oi_l = _SortedLookup(oi)
                
                evals, results = await run_sweep(
                    symbol, interval, klines, fr_l, ls_l, oi_l, fng, start_ms, days
                )
                print(f"| {len(evals)} evals | {len(results)} combos | {time.time()-t0:.0f}s")
                
                for r in results:
                    r["symbol"] = symbol
                    r["interval"] = interval
                all_results.extend(results)
                
            except Exception as e:
                print(f"ERROR: {e}")
                import traceback; traceback.print_exc()
            
            await asyncio.sleep(0.5)
    
    # ═══ ANALYSIS ═══
    print(f"\n  Total combos tested: {len(all_results)}")
    
    # Aggregate by filter+sltp across all symbols
    agg = defaultdict(list)
    for r in all_results:
        key = (r["filter"], r["sltp"])
        agg[key].append(r)
    
    agg_results = []
    for (fname, sltp), runs in agg.items():
        if len(runs) < 2:
            continue
        total_n = sum(r["n_trades"] for r in runs)
        if total_n < 15:
            continue
        
        # Weighted average by trade count
        avg_wr = sum(r["win_rate"]*r["n_trades"] for r in runs)/total_n
        avg_pnl = sum(r["avg_pnl"]*r["n_trades"] for r in runs)/total_n
        avg_exp = sum(r["expectancy"]*r["n_trades"] for r in runs)/total_n
        avg_pf = sum(r["profit_factor"]*r["n_trades"] for r in runs)/total_n
        
        # Check consistency: profitable in each symbol?
        profitable_count = sum(1 for r in runs if r["avg_pnl"] > 0)
        
        agg_results.append({
            "filter": fname,
            "sltp": sltp,
            "sl_m": runs[0]["sl_m"],
            "tp_m": runs[0]["tp_m"],
            "total_trades": total_n,
            "avg_wr": round(avg_wr, 1),
            "avg_pnl": round(avg_pnl, 3),
            "avg_expectancy": round(avg_exp, 3),
            "avg_pf": round(avg_pf, 2),
            "profitable_in": profitable_count,
            "total_symbols": len(runs),
            "per_symbol": [{
                "sym": r["symbol"],
                "wr": r["win_rate"],
                "pnl": r["avg_pnl"],
                "n": r["n_trades"],
                "pf": r["profit_factor"],
            } for r in runs],
        })
    
    # Sort by expectancy
    agg_results.sort(key=lambda x: x["avg_expectancy"], reverse=True)
    
    # Print TOP 30
    print(f"\n{'═'*120}")
    print(f"  TOP 30 PARAMETER COMBINATIONS (sorted by expectancy)")
    print(f"{'═'*120}")
    print(f"  {'Rank':>4s} {'Filter':22s} {'SL/TP':14s} {'#Trades':>7s} {'WinRate':>8s} {'AvgPnl':>8s} {'Expect':>8s} {'PF':>6s} {'Consistent':>11s} {'Per-Symbol Detail'}")
    print(f"  {'-'*115}")
    
    for i, r in enumerate(agg_results[:30], 1):
        icon = "🏆" if r["avg_expectancy"] > 0.1 else "🟢" if r["avg_expectancy"] > 0 else "🔴"
        consistency = f"{r['profitable_in']}/{r['total_symbols']}"
        detail = " | ".join(f"{s['sym'][:3]}:{s['wr']:.0f}%/{s['pnl']:+.2f}%" for s in r["per_symbol"])
        
        print(f"  {icon}{i:2d} {r['filter']:22s} {r['sltp']:14s} {r['total_trades']:7d} "
              f"{r['avg_wr']:>7.1f}% {r['avg_pnl']:>+7.3f}% {r['avg_expectancy']:>+7.3f} "
              f"{r['avg_pf']:>5.2f} {consistency:>11s}   {detail}")
    
    # Find the BEST with consistency >= 2/3
    consistent = [r for r in agg_results if r["profitable_in"] >= 2 and r["avg_expectancy"] > 0]
    
    print(f"\n{'═'*120}")
    print(f"  CONSISTENT WINNERS (profitable in ≥2/3 symbols)")
    print(f"{'═'*120}")
    
    if consistent:
        for i, r in enumerate(consistent[:15], 1):
            detail = " | ".join(f"{s['sym'][:3]}:{s['wr']:.0f}%/{s['pnl']:+.2f}%/PF{s['pf']:.1f}" for s in r["per_symbol"])
            print(f"  🏆{i:2d} {r['filter']:22s} SL={r['sl_m']}×ATR TP={r['tp_m']}×ATR | "
                  f"WR={r['avg_wr']:.1f}% PnL={r['avg_pnl']:+.3f}% E={r['avg_expectancy']:+.3f} PF={r['avg_pf']:.2f} "
                  f"[{r['profitable_in']}/{r['total_symbols']}] | {detail}")
    else:
        print("  ❌ No consistently profitable combos found")
    
    # Save
    os.makedirs(r"D:\All_in_AI\Trading_system\data", exist_ok=True)
    save_path = r"D:\All_in_AI\Trading_system\data\sweep_results.json"
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": {"days": days, "intervals": INTERVALS, "symbols": SYMBOLS,
                       "n_filters": len(FILTERS), "n_sltp": len(SL_TP_CONFIGS)},
            "top30": agg_results[:30],
            "consistent_winners": consistent[:15] if consistent else [],
            "total_combos": len(all_results),
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 {save_path}")
    print(f"\n{'═'*70}\n  SWEEP COMPLETE\n{'═'*70}")


if __name__ == "__main__":
    asyncio.run(main())
