"""
多周期 × 多币种 30天回测
BTC/ETH/SOL × 1m/5m/15m/30m/1h × 30天
复用 backtester_v2.py 的 18层评分引擎
"""
import asyncio
import sys
import os
import json
import time
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, r"D:\All_in_AI\Trading_system")

from backend.trading.backtester_v2 import (
    HistoricalDataFetcher, BacktesterV2, score_bar, _SortedLookup
)
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVALS = ["1m", "5m", "15m", "30m", "1h"]
DAYS = 30
INITIAL_BALANCE = 10000
RISK_PCT = 2.0
SCORE_THRESHOLD = 65

# Interval -> estimated candles per hour (for cooldown/max_hold scaling)
CANDLES_PER_HOUR = {"1m": 60, "5m": 12, "15m": 4, "30m": 2, "1h": 1}

class MultiTimeframeBacktester:
    def __init__(self):
        self.fetcher = HistoricalDataFetcher()
    
    async def fetch_klines_for_interval(self, symbol, interval, start, end):
        """Fetch klines with extended lookback for indicators"""
        lookback_hours = 200 * {"1m": 1/60, "5m": 5/60, "15m": 0.25, "30m": 0.5, "1h": 1}[interval]
        lookback_start = start - timedelta(hours=max(lookback_hours, 240))
        return await self.fetcher.fetch_klines(symbol, interval, lookback_start, end)
    
    async def run_single(self, symbol, interval, start, end):
        """Run backtest for one symbol × one interval"""
        t0 = time.time()
        print(f"  {symbol} {interval}...", end=" ", flush=True)
        
        # Fetch data
        klines = await self.fetch_klines_for_interval(symbol, interval, start, end)
        
        # Also fetch hourly supplementary data (FR, L/S, OI) — these are always hourly
        fr_data = await self.fetcher.fetch_funding_rate(symbol, start, end)
        ls_data = await self.fetcher.fetch_long_short_ratio(symbol, start, end)
        oi_data = await self.fetcher.fetch_oi_history(symbol, start, end)
        
        if len(klines) < 100:
            print(f"SKIP ({len(klines)} candles)")
            return None
        
        # Fetch FNG (once, reuse)
        fng_value = 50
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.alternative.me/fng/?limit=1")
                if r.status_code == 200:
                    fng_value = int(r.json()["data"][0]["value"])
        except:
            pass
        
        fr_lookup = _SortedLookup(fr_data)
        ls_lookup = _SortedLookup(ls_data)
        oi_lookup = _SortedLookup(oi_data)
        
        # Simulation
        balance = INITIAL_BALANCE
        position = None
        trades = []
        start_ms = int(start.timestamp() * 1000)
        
        closes, highs, lows, opens, volumes = [], [], [], [], []
        last_trade_idx = -999
        consecutive_losses = 0
        peak_balance = INITIAL_BALANCE
        max_drawdown = 0
        
        # Scale cooldown and max_hold based on interval
        cph = CANDLES_PER_HOUR[interval]
        cooldown = max(2, int(3 * cph))  # 3 hours cooldown
        max_hold = int(36 * cph)  # 36 hours max hold
        
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
            
            # Check existing position
            if position:
                sl_hit = (position["side"] == "buy" and low <= position["sl"]) or \
                         (position["side"] == "sell" and high >= position["sl"])
                tp_hit = (position["side"] == "buy" and high >= position["tp"]) or \
                         (position["side"] == "sell" and low <= position["tp"])
                
                bars_held = idx - position["opened_idx"]
                
                if bars_held >= max_hold and not tp_hit:
                    pnl = _calc_pnl(position, price)
                    balance += pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": price, "pnl": round(pnl, 2), "reason": "timeout"})
                    position = None
                    last_trade_idx = idx
                    consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
                elif sl_hit or tp_hit:
                    exit_p = position["sl"] if sl_hit else position["tp"]
                    pnl = _calc_pnl(position, exit_p)
                    balance += pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(pnl, 2),
                                   "reason": "sl" if sl_hit else "tp"})
                    position = None
                    last_trade_idx = idx
                    consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
                else:
                    # Trailing stop
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
            
            # Track drawdown
            peak_balance = max(peak_balance, balance)
            dd = (peak_balance - balance) / peak_balance * 100
            max_drawdown = max(max_drawdown, dd)
            
            # Only evaluate signals every N candles to avoid over-trading
            eval_interval = max(1, cph)  # At least once per hour
            if idx % eval_interval != 0:
                continue
            
            # Skip if in cooldown
            if idx - last_trade_idx < cooldown:
                continue
            
            # Skip if circuit breaker
            if consecutive_losses >= 3:
                consecutive_losses = 0  # Reset after skip
                continue
            
            # Skip if already in position
            if position:
                continue
            
            # Score
            fr_val = fr_lookup.find(ts)
            ls_val = ls_lookup.find(ts)
            oi_curr = oi_lookup.find(ts)
            oi_prev = oi_lookup.find(ts - 3600000)
            
            result = score_bar(
                closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
                current_price=price,
                funding_rate=fr_val, ls_ratio=ls_val,
                oi_current=oi_curr, oi_prev=oi_prev,
                fng_value=fng_value,
                score_threshold=SCORE_THRESHOLD,
            )
            
            direction = result["direction"]
            score = result["score"]
            
            if direction == "neutral":
                continue
            
            # Open position
            side = "buy" if direction == "bullish" else "sell"
            lev = result.get("leverage", 2)
            sl_price = result["sl"]
            tp_price = result["tp"]
            
            risk_amount = balance * RISK_PCT / 100
            sl_dist = abs(price - sl_price) * lev
            if sl_dist <= 0:
                continue
            pos_size = risk_amount / sl_dist
            
            position = {
                "side": side, "entry": price, "amount": pos_size,
                "sl": sl_price, "tp": tp_price, "leverage": lev,
                "opened_idx": idx, "regime": result.get("market_regime", "trending"),
            }
            last_trade_idx = idx
        
        # Close any remaining position
        if position:
            pnl = _calc_pnl(position, closes[-1])
            balance += pnl
            trades.append({"side": position["side"], "entry": position["entry"],
                           "exit": closes[-1], "pnl": round(pnl, 2), "reason": "end"})
        
        # Calculate stats
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        profit_factor = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if losses and sum(t["pnl"] for t in losses) != 0 else float('inf')
        
        elapsed = time.time() - t0
        print(f"{len(trades)} trades | WR {win_rate:.0f}% | PnL ${total_pnl:+.2f} ({total_pnl/INITIAL_BALANCE*100:+.1f}%) | DD {max_drawdown:.1f}% | {elapsed:.0f}s")
        
        return {
            "symbol": symbol, "interval": interval,
            "total_trades": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / INITIAL_BALANCE * 100, 1),
            "max_drawdown": round(max_drawdown, 1),
            "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999,
            "final_balance": round(balance, 2),
            "candles": len(klines),
        }


def _calc_pnl(position, exit_price):
    if position["side"] == "buy":
        return (exit_price - position["entry"]) * position["amount"]
    else:
        return (position["entry"] - exit_price) * position["amount"]


async def main():
    end = datetime.utcnow()
    start = end - timedelta(days=DAYS)
    
    print("=" * 80)
    print(f"  Trading Oracle V4 18-Layer Backtest")
    print(f"  Period: {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')} ({DAYS} days)")
    print(f"  Coins: {', '.join(SYMBOLS)}")
    print(f"  Timeframes: {', '.join(INTERVALS)}")
    print(f"  Balance: ${INITIAL_BALANCE:,} | Risk: {RISK_PCT}% | Threshold: {SCORE_THRESHOLD}")
    print("=" * 80)
    
    bt = MultiTimeframeBacktester()
    all_results = []
    
    for symbol in SYMBOLS:
        print(f"\n{'─'*60}")
        print(f"  {symbol}")
        print(f"{'─'*60}")
        for interval in INTERVALS:
            try:
                result = await bt.run_single(symbol, interval, start, end)
                if result:
                    all_results.append(result)
            except Exception as e:
                print(f"  {symbol} {interval}... ERROR: {e}")
            await asyncio.sleep(1)  # Rate limiting
    
    # Summary table
    print(f"\n{'='*80}")
    print(f"  SUMMARY — 30-DAY BACKTEST RESULTS")
    print(f"{'='*80}")
    print(f"{'Symbol':<10} {'TF':<6} {'Trades':<8} {'WinRate':<8} {'PnL($)':<10} {'PnL(%)':<8} {'MaxDD':<7} {'PF':<6} {'AvgW':<8} {'AvgL':<8}")
    print(f"{'─'*80}")
    
    for r in all_results:
        pnl_color = "+" if r["total_pnl"] >= 0 else ""
        print(f"{r['symbol']:<10} {r['interval']:<6} {r['total_trades']:<8} "
              f"{r['win_rate']:<7.0f}% {pnl_color}{r['total_pnl']:<9.2f} "
              f"{pnl_color}{r['pnl_pct']:<7.1f}% {r['max_drawdown']:<6.1f}% "
              f"{r['profit_factor']:<6.1f} {r['avg_win']:<8.2f} {r['avg_loss']:<8.2f}")
    
    # Best/worst
    if all_results:
        best = max(all_results, key=lambda r: r["pnl_pct"])
        worst = min(all_results, key=lambda r: r["pnl_pct"])
        print(f"\n  BEST:  {best['symbol']} {best['interval']} -> +{best['pnl_pct']}% (WR {best['win_rate']}%)")
        print(f"  WORST: {worst['symbol']} {worst['interval']} -> {worst['pnl_pct']}% (WR {worst['win_rate']}%)")
        
        avg_pnl = sum(r["pnl_pct"] for r in all_results) / len(all_results)
        avg_wr = sum(r["win_rate"] for r in all_results) / len(all_results)
        print(f"  AVG:   PnL {avg_pnl:+.1f}% | WR {avg_wr:.0f}%")
    
    # Save results
    with open(r"D:\All_in_AI\Trading_system\data\backtest_30d_results.json", "w", encoding="utf-8") as f:
        json.dump({"results": all_results, "config": {
            "days": DAYS, "symbols": SYMBOLS, "intervals": INTERVALS,
            "balance": INITIAL_BALANCE, "risk_pct": RISK_PCT, "threshold": SCORE_THRESHOLD,
            "run_at": datetime.utcnow().isoformat(),
        }}, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to data/backtest_30d_results.json")

if __name__ == "__main__":
    asyncio.run(main())
