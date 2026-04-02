# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  DEEP BREAKOUT OPTIMIZER
  
  在S3_Breakout基础上深度微调:
  - 突破回看周期: 10/15/20/30根K线
  - 量能阈值: 1.2x/1.5x/2.0x/2.5x
  - ADX门槛: 15/20/25/30
  - SL/TP: 多种组合
  - 移动止盈激活点: 20%/30%/40%/50%
  - 加入资金费率过滤
  - 180天数据 = 更大样本
  - 分单/双向独立统计
═══════════════════════════════════════════════════════════════════
"""
import asyncio, sys, os, json, time, math, itertools
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

INIT_BAL = 1000.0
RISK_PCT = 2.0
COOLDOWN = 6
MAX_HOLD = 48
DD_PAUSE = 15


def resample_to_4h(klines_1h):
    out = []
    for i in range(0, len(klines_1h)-3, 4):
        chunk = klines_1h[i:i+4]
        out.append({
            "ts": chunk[0]["ts"], "open": chunk[0]["open"],
            "high": max(k["high"] for k in chunk),
            "low": min(k["low"] for k in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(k["volume"] for k in chunk),
        })
    return out


def get_4h_context(c4, h4, l4):
    if len(c4) < 30: return None
    trend = trend_direction(c4, 10, 25)
    adx = calc_adx(h4, l4, c4) if len(c4) >= 30 else 15
    ema10 = calc_ema(c4, 10)
    ema25 = calc_ema(c4, 25)
    return {"trend": trend, "adx": adx, "ema10": ema10, "ema25": ema25}


def run_single_config(config, klines_1h, klines_4h, fr_lookup, start_ms):
    """Run one parameter configuration — returns portfolio result"""
    lookback = config["lookback"]
    vol_thresh = config["vol_thresh"]
    adx_min = config["adx_min"]
    sl_atr = config["sl_atr"]
    tp_atr = config["tp_atr"]
    trail_act = config["trail_act"]
    require_macd = config.get("require_macd", True)
    require_ema = config.get("require_ema", True)
    use_fr = config.get("use_fr", False)
    
    balance = INIT_BAL
    peak = INIT_BAL
    pos = None
    trades = []
    last_bar = -999
    consec_loss = 0
    paused = -1
    
    closes, highs, lows, opens, volumes = [], [], [], [], []
    c4, h4, l4 = [], [], []
    _4h_i = 0
    
    for idx, k in enumerate(klines_1h):
        closes.append(k["close"])
        highs.append(k["high"])
        lows.append(k["low"])
        opens.append(k["open"])
        volumes.append(k["volume"])
        
        while _4h_i < len(klines_4h) and klines_4h[_4h_i]["ts"] <= k["ts"]:
            kk = klines_4h[_4h_i]
            c4.append(kk["close"]); h4.append(kk["high"]); l4.append(kk["low"])
            _4h_i += 1
        
        if len(closes) < 50 or len(c4) < 30 or k["ts"] < start_ms:
            continue
        
        price = k["close"]
        ts = k["ts"]
        
        # DD check
        dd = (peak - balance)/peak*100 if peak > 0 else 0
        if dd >= DD_PAUSE and not pos:
            if idx < paused: continue
            paused = idx + 24
            continue
        
        # Position mgmt
        if pos:
            bars_in = idx - pos["bar"]
            sl, tp = pos["sl"], pos["tp"]
            
            hit_sl = (pos["side"]=="buy" and k["low"]<=sl) or (pos["side"]=="sell" and k["high"]>=sl)
            hit_tp = (pos["side"]=="buy" and k["high"]>=tp) or (pos["side"]=="sell" and k["low"]<=tp)
            timeout = bars_in >= MAX_HOLD
            
            # Trailing
            if not hit_sl and not hit_tp:
                tp_dist = abs(tp - pos["entry"])
                if pos["side"] == "buy":
                    profit = (price - pos["entry"]) / pos["entry"]
                    if profit >= trail_act * (tp_dist / pos["entry"]):
                        new_sl = max(sl, pos["entry"] + (price - pos["entry"]) * 0.5)
                        if new_sl > sl: pos["sl"] = sl = round(new_sl, 6)
                else:
                    profit = (pos["entry"] - price) / pos["entry"]
                    if profit >= trail_act * (tp_dist / pos["entry"]):
                        new_sl = min(sl, pos["entry"] - (pos["entry"] - price) * 0.5)
                        if new_sl < sl: pos["sl"] = sl = round(new_sl, 6)
            
            if hit_sl or hit_tp or timeout:
                ep = sl if hit_sl else (tp if hit_tp else price)
                pnl_p = ((ep-pos["entry"])/pos["entry"]) if pos["side"]=="buy" else ((pos["entry"]-ep)/pos["entry"])
                pnl_d = pnl_p * pos["value"]
                balance += pnl_d
                peak = max(peak, balance)
                trades.append({"pnl_pct": round(pnl_p*100,3), "pnl_d": round(pnl_d,2),
                               "reason": "sl" if hit_sl else ("tp" if hit_tp else "timeout"),
                               "bars": bars_in, "side": pos["side"]})
                consec_loss = consec_loss + 1 if pnl_d <= 0 else 0
                last_bar = idx
                pos = None
            continue
        
        # Entry
        if balance <= 20 or idx - last_bar < COOLDOWN: continue
        if consec_loss >= 3:
            consec_loss = 0; last_bar = idx + 12; continue
        
        ctx = get_4h_context(c4, h4, l4)
        if not ctx: continue
        
        # Indicators
        atr = sum(highs[i]-lows[i] for i in range(-14,0)) / 14
        if atr <= 0: continue
        adx = calc_adx(highs, lows, closes) if len(closes) >= 30 else 0
        
        # MACD
        macd_hist = 0
        if require_macd and len(closes) >= 35:
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
        ema21 = calc_ema(closes[-30:], 21) if require_ema else 0
        above_ema = price > ema21 if require_ema else True
        below_ema = price < ema21 if require_ema else True
        
        # Volume
        va = sum(volumes[-20:])/min(20,len(volumes))
        vr = volumes[-1]/va if va > 0 else 1
        
        # Breakout
        lb = min(lookback, len(highs)-1)
        recent_high = max(highs[-lb-1:-1])
        recent_low = min(lows[-lb-1:-1])
        
        # Funding rate
        fr_ok = True
        if use_fr and fr_lookup:
            fr = fr_lookup.find(ts)
            if fr is not None:
                # Positive FR + short breakout = stronger (crowds are long)
                # Negative FR + long breakout = stronger (crowds are short)
                if fr > 0.0001: fr_ok = True  # overly long — short breakout better
                elif fr < -0.0001: fr_ok = True  # overly short — long breakout better
        
        side = None
        
        # Buy breakout
        buy_ok = (ctx["trend"] > 0
                  and price >= recent_high * 0.999
                  and vr > vol_thresh
                  and adx > adx_min
                  and fr_ok)
        if require_macd: buy_ok = buy_ok and macd_hist > 0
        if require_ema: buy_ok = buy_ok and above_ema
        
        # Sell breakout
        sell_ok = (ctx["trend"] < 0
                   and price <= recent_low * 1.001
                   and vr > vol_thresh
                   and adx > adx_min
                   and fr_ok)
        if require_macd: sell_ok = sell_ok and macd_hist < 0
        if require_ema: sell_ok = sell_ok and below_ema
        
        if buy_ok: side = "buy"
        elif sell_ok: side = "sell"
        
        if not side: continue
        
        # Position sizing
        sl_dist = atr * sl_atr
        tp_dist = atr * tp_atr
        risk_d = balance * RISK_PCT / 100
        pv = min(risk_d / (sl_dist / price), balance * 5)
        
        sl_p = price - sl_dist if side == "buy" else price + sl_dist
        tp_p = price + tp_dist if side == "buy" else price - tp_dist
        
        pos = {"side": side, "entry": price, "sl": round(sl_p,6), "tp": round(tp_p,6),
               "value": pv, "atr": atr, "bar": idx}
        last_bar = idx
    
    # Close remaining
    if pos:
        p = closes[-1]
        pnl_p = ((p-pos["entry"])/pos["entry"]) if pos["side"]=="buy" else ((pos["entry"]-p)/pos["entry"])
        balance += pnl_p * pos["value"]
        trades.append({"pnl_pct": round(pnl_p*100,3), "reason": "end",
                       "bars": len(klines_1h)-1-pos["bar"], "side": pos["side"]})
    
    if not trades:
        return {"trades": 0, "wr": 0, "roi": 0, "dd": 0, "pf": 0, "bal": INIT_BAL,
                "avg_pnl": 0, "avg_win": 0, "avg_loss": 0, "avg_bars": 0}
    
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    wr = len(wins)/len(trades)*100
    roi = (balance-INIT_BAL)/INIT_BAL*100
    ws = sum(t.get("pnl_d",0) for t in wins if "pnl_d" in t)
    ls = abs(sum(t.get("pnl_d",0) for t in losses if "pnl_d" in t))
    pf = ws/ls if ls > 0 else 999
    
    return {
        "trades": len(trades), "wr": round(wr,1), "roi": round(roi,1),
        "dd": round((peak-min(balance,peak))/peak*100 if peak>0 else 0, 1),
        "pf": round(pf,2), "bal": round(balance,2),
        "avg_pnl": round(sum(t["pnl_pct"] for t in trades)/len(trades), 3),
        "avg_win": round(sum(t["pnl_pct"] for t in wins)/len(wins), 3) if wins else 0,
        "avg_loss": round(sum(t["pnl_pct"] for t in losses)/len(losses), 3) if losses else 0,
        "avg_bars": round(sum(t.get("bars",0) for t in trades)/len(trades), 1),
    }


async def main():
    fetcher = HistoricalDataFetcher()
    end = datetime.utcnow()
    
    print("╔" + "═"*70 + "╗")
    print("║  DEEP BREAKOUT OPTIMIZER                                         ║")
    print("║  Fine-tuning S3_Breakout: 576 parameter combos × 3 coins         ║")
    print("║  180 days data for maximum sample size                            ║")
    print("╚" + "═"*70 + "╝")
    
    SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    days = 180
    start = end - timedelta(days=days)
    start_ms = int(start.timestamp()*1000)
    
    # Parameter grid
    LOOKBACKS = [10, 15, 20, 30]
    VOL_THRESHOLDS = [1.2, 1.5, 2.0]
    ADX_MINS = [15, 20, 25]
    SL_TP_CONFIGS = [
        (1.5, 3.0), (1.5, 4.5), (1.5, 6.0),
        (2.0, 4.0), (2.0, 5.0), (2.0, 6.0), (2.0, 8.0),
        (2.5, 5.0), (2.5, 8.0),
    ]
    TRAIL_ACTS = [0.25, 0.35]
    MACD_OPTS = [True, False]
    
    total_configs = len(LOOKBACKS) * len(VOL_THRESHOLDS) * len(ADX_MINS) * len(SL_TP_CONFIGS) * len(TRAIL_ACTS) * len(MACD_OPTS)
    print(f"  Total configs: {total_configs}")
    
    # Fetch data per symbol
    symbol_data = {}
    for symbol in SYMBOLS:
        print(f"\n  📈 {symbol}: Fetching 180d data...", end=" ", flush=True)
        lookback = start - timedelta(days=20)
        try:
            klines_1h, fr, _, _ = await asyncio.gather(
                fetcher.fetch_klines(symbol, "1h", lookback, end),
                fetcher.fetch_funding_rate(symbol, start, end),
                fetcher.fetch_long_short_ratio(symbol, start, end),
                fetcher.fetch_oi_history(symbol, start, end),
            )
            klines_4h = resample_to_4h(klines_1h)
            fr_l = _SortedLookup(fr)
            symbol_data[symbol] = (klines_1h, klines_4h, fr_l)
            print(f"{len(klines_1h)} 1H | {len(klines_4h)} 4H")
        except Exception as e:
            print(f"ERROR: {e}")
        await asyncio.sleep(0.5)
    
    # Run sweep
    all_results = []
    t0 = time.time()
    count = 0
    
    for lb, vt, adx_m, (sl, tp), ta, use_macd in itertools.product(
        LOOKBACKS, VOL_THRESHOLDS, ADX_MINS, SL_TP_CONFIGS, TRAIL_ACTS, MACD_OPTS
    ):
        config = {
            "lookback": lb, "vol_thresh": vt, "adx_min": adx_m,
            "sl_atr": sl, "tp_atr": tp, "trail_act": ta,
            "require_macd": use_macd, "require_ema": True,
        }
        
        sym_results = {}
        for symbol, (k1h, k4h, fr_l) in symbol_data.items():
            r = run_single_config(config, k1h, k4h, fr_l, start_ms)
            sym_results[symbol] = r
        
        # Aggregate
        total_trades = sum(r["trades"] for r in sym_results.values())
        if total_trades < 10: 
            count += 1
            continue
        
        profitable = sum(1 for r in sym_results.values() if r["roi"] > 0)
        avg_roi = sum(r["roi"] for r in sym_results.values()) / len(sym_results)
        avg_wr = sum(r["wr"]*r["trades"] for r in sym_results.values()) / total_trades if total_trades > 0 else 0
        avg_dd = sum(r["dd"] for r in sym_results.values()) / len(sym_results)
        avg_pf = sum(r["pf"]*r["trades"] for r in sym_results.values()) / total_trades if total_trades > 0 else 0
        
        all_results.append({
            "config": config,
            "total_trades": total_trades,
            "profitable_in": profitable,
            "avg_roi": round(avg_roi, 1),
            "avg_wr": round(avg_wr, 1),
            "avg_dd": round(avg_dd, 1),
            "avg_pf": round(avg_pf, 2),
            "per_symbol": {s: r for s, r in sym_results.items()},
        })
        
        count += 1
        if count % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{count}/{total_configs}] {elapsed:.0f}s | best so far: "
                  f"ROI={max(r['avg_roi'] for r in all_results):+.1f}% "
                  f"WR={max(r['avg_wr'] for r in all_results):.1f}%", flush=True)
    
    print(f"\n  Sweep done: {len(all_results)} valid combos in {time.time()-t0:.0f}s")
    
    # Sort by ROI
    all_results.sort(key=lambda x: x["avg_roi"], reverse=True)
    
    # Print TOP 20
    print(f"\n{'═'*130}")
    print(f"  TOP 20 BY ROI (profitable ≥2/3)")
    print(f"{'═'*130}")
    print(f"  {'#':>3s} {'LB':>3s} {'Vol':>4s} {'ADX':>4s} {'SL':>4s} {'TP':>4s} {'Trail':>5s} {'MACD':>5s} "
          f"{'Trades':>7s} {'AvgWR':>7s} {'AvgROI':>8s} {'AvgDD':>7s} {'AvgPF':>6s} {'Cons':>5s} {'Per-Symbol'}")
    print("  " + "-" * 125)
    
    shown = 0
    for r in all_results:
        if r["profitable_in"] < 2: continue
        shown += 1
        if shown > 20: break
        
        c = r["config"]
        detail = " | ".join(f"{s[:3]}:ROI{d['roi']:+.0f}%/WR{d['wr']:.0f}%/PF{d['pf']:.1f}/{d['trades']}T" 
                            for s, d in r["per_symbol"].items())
        
        icon = "🏆" if shown <= 3 else "🟢" if r["avg_roi"] > 5 else "  "
        print(f"  {icon}{shown:2d} {c['lookback']:3d} {c['vol_thresh']:4.1f} {c['adx_min']:4d} "
              f"{c['sl_atr']:4.1f} {c['tp_atr']:4.1f} {c['trail_act']:5.2f} "
              f"{'Y' if c['require_macd'] else 'N':>5s} "
              f"{r['total_trades']:7d} {r['avg_wr']:>6.1f}% {r['avg_roi']:>+7.1f}% "
              f"{r['avg_dd']:>6.1f}% {r['avg_pf']:>5.2f} {r['profitable_in']}/3   {detail}")
    
    # Also show TOP by WR (among profitable)
    wr_sorted = sorted([r for r in all_results if r["profitable_in"] >= 2], 
                       key=lambda x: x["avg_wr"], reverse=True)
    
    print(f"\n{'═'*130}")
    print(f"  TOP 10 BY WIN RATE (profitable ≥2/3, min 15 trades)")
    print(f"{'═'*130}")
    
    shown = 0
    for r in wr_sorted:
        if r["total_trades"] < 15: continue
        shown += 1
        if shown > 10: break
        c = r["config"]
        detail = " | ".join(f"{s[:3]}:WR{d['wr']:.0f}%/ROI{d['roi']:+.0f}%/{d['trades']}T" 
                            for s, d in r["per_symbol"].items())
        print(f"  🏆{shown:2d} LB={c['lookback']} Vol>{c['vol_thresh']} ADX>{c['adx_min']} "
              f"SL={c['sl_atr']}×TP={c['tp_atr']}× Trail={c['trail_act']} MACD={'Y' if c['require_macd'] else 'N'} | "
              f"WR={r['avg_wr']:.1f}% ROI={r['avg_roi']:+.1f}% PF={r['avg_pf']:.2f} "
              f"DD={r['avg_dd']:.1f}% [{r['profitable_in']}/3] {r['total_trades']}T | {detail}")
    
    # Best balanced (WR>50, ROI>5, PF>1.5, profitable 3/3)
    balanced = [r for r in all_results 
                if r["profitable_in"] >= 3 and r["avg_wr"] > 50 and r["avg_roi"] > 5 and r["avg_pf"] > 1.5]
    
    if balanced:
        balanced.sort(key=lambda x: x["avg_roi"], reverse=True)
        print(f"\n{'═'*130}")
        print(f"  ⭐ BEST BALANCED: WR>50% + ROI>5% + PF>1.5 + 3/3 profitable")
        print(f"{'═'*130}")
        for i, r in enumerate(balanced[:10], 1):
            c = r["config"]
            detail = " | ".join(f"{s[:3]}:WR{d['wr']:.0f}%/ROI{d['roi']:+.0f}%/PF{d['pf']:.1f}" 
                                for s, d in r["per_symbol"].items())
            print(f"  ⭐{i:2d} LB={c['lookback']} Vol>{c['vol_thresh']} ADX>{c['adx_min']} "
                  f"SL={c['sl_atr']}×TP={c['tp_atr']}× MACD={'Y' if c['require_macd'] else 'N'} | "
                  f"WR={r['avg_wr']:.1f}% ROI={r['avg_roi']:+.1f}% PF={r['avg_pf']:.2f} "
                  f"{r['total_trades']}T | {detail}")
    
    # Save
    os.makedirs(r"D:\All_in_AI\Trading_system\data", exist_ok=True)
    save_path = r"D:\All_in_AI\Trading_system\data\deep_breakout_results.json"
    top_results = all_results[:50]  # Save top 50
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump({
            "config": {"days": days, "total_configs": total_configs, "valid_combos": len(all_results)},
            "top_by_roi": top_results[:20],
            "top_by_wr": wr_sorted[:10] if wr_sorted else [],
            "best_balanced": balanced[:10] if balanced else [],
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  💾 {save_path}")
    print(f"\n{'═'*70}\n  DEEP OPTIMIZATION COMPLETE\n{'═'*70}")


if __name__ == "__main__":
    asyncio.run(main())
