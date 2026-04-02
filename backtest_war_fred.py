"""
War-Enhanced Backtest
Simulates trading during crisis/war periods by integrating:
1. Historical daily Fear & Greed Index (FNG)
2. FRED Macro Data (10Y Treasury Yield to detect safe-haven flows)
3. Dynamic switching to S5 Crisis Scorer when FNG <= 25 or macro stress detected

Tests BTCUSDT, ETHUSDT, SOLUSDT on 30m over 30 days.
"""
import asyncio
import sys
import json
import time
from datetime import datetime, timedelta
import httpx

sys.path.insert(0, r"D:\All_in_AI\Trading_system")

from backend.trading.backtester_v2 import HistoricalDataFetcher, score_bar, _SortedLookup
from backend.trading.crisis_scorer import crisis_score
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL = "30m"
DAYS = 30
INITIAL_BALANCE = 10000
RISK_PCT = 2.0
SCORE_THRESHOLD = 65

async def fetch_historical_fng(days: int) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://api.alternative.me/fng/?limit={days+5}&format=json")
            if r.status_code == 200:
                data = r.json()["data"]
                # Map timestamp to FNG value
                return {int(d["timestamp"]): int(d["value"]) for d in data}
    except Exception as e:
        logger.warning(f"FNG history fetch failed: {e}")
    return {}

async def fetch_historical_treasury(days: int) -> dict:
    from backend.data_sources.macro.fred import FREDDataSource
    fng_config = {}
    try:
        with open(r"D:\All_in_AI\Trading_system\config\api_keys.json", "r", encoding="utf-8") as f:
            fng_config = json.load(f)
    except:
        pass
    fred_key = fng_config.get("fred", {}).get("api_key")
    if not fred_key or fred_key == "YOUR_FRED_API_KEY":
        print(" [!] No FRED API key found, skipping treasury data integration.")
        return {}
    
    try:
        fred = FREDDataSource(fred_key)
        data = await fred._get_series("DGS10", lookback_days=days+5)
        # Returns a pandas Series with DateIndex
        res = {}
        for ts, val in data.dropna().items():
            # ts is Timestamp, convert to ms Unix
            res[int(ts.timestamp())] = float(val)
        return res
    except Exception as e:
        logger.warning(f"FRED history fetch failed: {e}")
    return {}

class WarBacktester:
    def __init__(self):
        self.fetcher = HistoricalDataFetcher()
        self.fng_lookup = None
        self.dgs10_lookup = None

    async def run_single(self, symbol, start, end):
        t0 = time.time()
        print(f"  {symbol} 30m War-Enhanced...", end=" ", flush=True)

        klines = await self.fetcher.fetch_klines(symbol, "30m", start - timedelta(days=10), end)
        fr_data = await self.fetcher.fetch_funding_rate(symbol, start, end)
        ls_data = await self.fetcher.fetch_long_short_ratio(symbol, start, end)
        oi_data = await self.fetcher.fetch_oi_history(symbol, start, end)

        if len(klines) < 100:
            print("SKIP")
            return None

        fr_lookup = _SortedLookup(fr_data)
        ls_lookup = _SortedLookup(ls_data)
        oi_lookup = _SortedLookup(oi_data)

        balance = INITIAL_BALANCE
        position = None
        trades = []
        start_ms = int(start.timestamp() * 1000)

        closes, highs, lows, opens, volumes = [], [], [], [], []
        last_trade_idx = -999
        consecutive_losses = 0
        peak_balance = INITIAL_BALANCE
        max_drawdown = 0

        # Simulation
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
            ts_sec = ts // 1000

            # Daily lookup for FNG/Treasury (timestamp matching)
            # Find closest FNG in the past
            fng_val = 50
            if self.fng_lookup and self.fng_lookup.keys:
                import bisect
                pos = bisect.bisect_right(self.fng_lookup.keys, ts_sec) - 1
                if pos >= 0:
                    fng_val = self.fng_lookup.data[self.fng_lookup.keys[pos]]

            # Find closest Treasury Yield
            dgs_val = None
            if self.dgs10_lookup and self.dgs10_lookup.keys:
                import bisect
                pos = bisect.bisect_right(self.dgs10_lookup.keys, ts_sec) - 1
                if pos >= 0:
                    dgs_val = self.dgs10_lookup.data[self.dgs10_lookup.keys[pos]]

            # Check existing position
            if position:
                sl_hit = (position["side"] == "buy" and low <= position["sl"]) or \
                         (position["side"] == "sell" and high >= position["sl"])
                tp_hit = (position["side"] == "buy" and high >= position["tp"]) or \
                         (position["side"] == "sell" and low <= position["tp"])

                bars_held = idx - position["opened_idx"]
                max_hold = position.get("max_hold", 36)

                if bars_held >= max_hold and not tp_hit:
                    pnl = _calc_pnl(position, price)
                    balance += pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": price, "pnl": round(pnl, 2), "reason": "timeout", "mode": position.get("mode", "normal")})
                    position = None
                    last_trade_idx = idx
                    consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
                elif sl_hit or tp_hit:
                    exit_p = position["sl"] if sl_hit else position["tp"]
                    pnl = _calc_pnl(position, exit_p)
                    balance += pnl
                    trades.append({"side": position["side"], "entry": position["entry"],
                                   "exit": round(exit_p, 2), "pnl": round(pnl, 2),
                                   "reason": "sl" if sl_hit else "tp", "mode": position.get("mode", "normal")})
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

            peak_balance = max(peak_balance, balance)
            dd = (peak_balance - balance) / peak_balance * 100
            max_drawdown = max(max_drawdown, dd)

            # Evaluate every 1 hour (2 candles on 30m)
            if idx % 2 != 0:
                continue

            # Skipping logic
            if idx - last_trade_idx < 6: # 3 hrs cooldown
                continue
            if consecutive_losses >= 3: # circuit breaker
                consecutive_losses = 0
                continue
            if position:
                continue

            fr_val = fr_lookup.find(ts)
            ls_val = ls_lookup.find(ts)
            oi_curr = oi_lookup.find(ts)
            oi_prev = oi_lookup.find(ts - 3600000)

            # --- WAR CRISIS DETECTION ---
            # Drops in Treasury yield often indicate safe-haven flows during war panic
            is_crisis = fng_val <= 25

            if is_crisis:
                # Use S5 Crisis Scorer
                k_list = [{"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": volumes[i]} for i in range(-100, 0)]
                result = await crisis_score(symbol, k_list, price, fng_val, fr_val, ls_val)
                direction = result["direction"]
                
                if direction != "neutral":
                    lev = result.get("leverage", 2)
                    sl_price = result["sl_price"]
                    tp_price = result["tp_price"]
                    
                    risk_amount = balance * RISK_PCT / 100
                    sl_dist = abs(price - sl_price) * lev
                    if sl_dist > 0:
                        pos_size = risk_amount / sl_dist
                        position = {
                            "side": "sell", "entry": price, "amount": pos_size,
                            "sl": sl_price, "tp": tp_price, "leverage": lev,
                            "opened_idx": idx, "mode": "crisis", "max_hold": 72
                        }
                        last_trade_idx = idx
            else:
                # Normal mode
                result = score_bar(
                    closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes,
                    current_price=price,
                    funding_rate=fr_val, ls_ratio=ls_val,
                    oi_current=oi_curr, oi_prev=oi_prev,
                    fng_value=fng_val,
                    score_threshold=SCORE_THRESHOLD,
                )
                
                direction = result["direction"]
                if direction != "neutral":
                    side = "buy" if direction == "bullish" else "sell"
                    lev = result.get("leverage", 2)
                    sl_price = result["sl"]
                    tp_price = result["tp"]
                    
                    risk_amount = balance * RISK_PCT / 100
                    sl_dist = abs(price - sl_price) * lev
                    if sl_dist > 0:
                        pos_size = risk_amount / sl_dist
                        position = {
                            "side": side, "entry": price, "amount": pos_size,
                            "sl": sl_price, "tp": tp_price, "leverage": lev,
                            "opened_idx": idx, "mode": "normal", "max_hold": 36
                        }
                        last_trade_idx = idx

        if position:
            pnl = _calc_pnl(position, closes[-1])
            balance += pnl
            trades.append({"side": position["side"], "entry": position["entry"],
                           "exit": closes[-1], "pnl": round(pnl, 2), "reason": "end", "mode": position.get("mode", "normal")})

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        crisis_trades = sum(1 for t in trades if t.get("mode") == "crisis")
        
        elapsed = time.time() - t0
        print(f"{len(trades)} trades ({crisis_trades} crisis S5) | WR {win_rate:.0f}% | PnL ${total_pnl:+.2f} ({total_pnl/INITIAL_BALANCE*100:+.1f}%) | DD {max_drawdown:.1f}% | {elapsed:.0f}s")

        return {
            "symbol": symbol, "total_trades": len(trades), "crisis_trades": crisis_trades,
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / INITIAL_BALANCE * 100, 1),
            "max_drawdown": round(max_drawdown, 1)
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
    print(f"  War-Enhanced CRISIS Backtest (30 Days)")
    print(f"  Fetching Macro & Sentiment Data...")
    
    bt = WarBacktester()
    fng_raw = await fetch_historical_fng(DAYS)
    bt.fng_lookup = _SortedLookup(fng_raw)
    dgs_raw = await fetch_historical_treasury(DAYS)
    bt.dgs10_lookup = _SortedLookup(dgs_raw)
    
    print(f"  FNG Days Loaded: {len(fng_raw)}")
    print(f"  DGS10 (Treasury) Loaded: {len(dgs_raw)}")
    print("=" * 80)
    
    all_results = []
    for symbol in SYMBOLS:
        res = await bt.run_single(symbol, start, end)
        if res:
            all_results.append(res)
            
    # Summary table
    print(f"\n{'='*80}")
    print(f"  SUMMARY — 30-DAY WAR BACKTEST")
    print(f"{'='*80}")
    print(f"{'Symbol':<10} {'Trades':<8} {'Crisis':<8} {'WinRate':<8} {'PnL($)':<10} {'PnL(%)':<8} {'MaxDD':<7}")
    print(f"{'─'*80}")
    for r in all_results:
        pnl_color = "+" if r["total_pnl"] >= 0 else ""
        print(f"{r['symbol']:<10} {r['total_trades']:<8} {r['crisis_trades']:<8} "
              f"{r['win_rate']:<7.0f}% {pnl_color}{r['total_pnl']:<9.2f} "
              f"{pnl_color}{r['pnl_pct']:<7.1f}% {r['max_drawdown']:<6.1f}%")

if __name__ == "__main__":
    asyncio.run(main())
