import asyncio
import httpx
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import sys

# Ensure backend modules can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.trading.ml_predictor import ml_predictor

# Configuration
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
TIMEFRAMES = ["5m", "15m", "1H", "4H"] # OKX formats
DAYS_TO_FETCH = 90
INITIAL_BALANCE = 10000.0
TAKER_FEE = 0.0005  # OKX Swap Taker

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

async def fetch_okx_historical_klines(symbol, interval, days):
    """Fetch historical K-lines from OKX public API."""
    print(f"[{symbol} | {interval}] Fetching {days} days of history...")
    url = "https://www.okx.com/api/v5/market/history-candles"
    
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    
    all_candles = []
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        current_after = ""
        while True:
            params = {
                "instId": symbol,
                "bar": interval,
                "limit": 100,
            }
            if current_after:
                params["after"] = current_after
                
            try:
                res = await client.get(url, params=params)
                data = res.json()
                
                if data.get("code") != "0" or not data.get("data"):
                    break
                    
                batch = data["data"]
                all_candles.extend(batch)
                
                last_ts = int(batch[-1][0])
                if last_ts <= start_time:
                    break
                    
                current_after = str(last_ts)
                await asyncio.sleep(0.1) # Rate limit protection
            except Exception as e:
                print(f"Error fetching data: {e}")
                break
                
    if not all_candles:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_candles, columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"])
    df = df[["ts", "open", "high", "low", "close", "volCcy"]]
    df.columns = ["time", "open", "high", "low", "close", "volume"]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    df['time'] = df['time'] / 1000.0
    
    # Filter to exact date range and sort chronologically
    df = df[df['time'] >= (start_time / 1000.0)]
    df = df.sort_values("time").reset_index(drop=True)
    return df

async def run_backtest_simulation(symbol, df, interval_name):
    """Run the V2 ML + Kelly rolling simulation on historical data."""
    if len(df) < 200:
        return None
        
    print(f"[{symbol} | {interval_name}] Computing technical indicators vector...")
    
    df['rsi'] = calc_rsi(df['close'], 14)
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['sma20'] + 2 * df['std20']
    df['bb_lower'] = df['sma20'] - 2 * df['std20']
    
    df['sma50'] = df['close'].rolling(window=50).mean()
    df['sma200'] = df['close'].rolling(window=200).mean()
    
    df['atr'] = calc_atr(df['high'], df['low'], df['close'], 14)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean()
    df['momentum_14'] = df['close'] - df['close'].shift(14)
    
    print(f"[{symbol} | {interval_name}] Starting simulation on {len(df)} candles...")
    
    balance = INITIAL_BALANCE
    positions = [] # Only holding 1 position at a time
    trade_log = []
    
    for i in range(200, len(df)):
        current_candle = df.iloc[i]
        
        # Check active position for exit conditions
        if positions:
            pos = positions[0]
            hit_tp = False
            hit_sl = False
            close_price = 0
            
            if pos['side'] == 'buy':
                if current_candle['low'] <= pos['sl']:
                    hit_sl = True
                    close_price = pos['sl']
                elif current_candle['high'] >= pos['tp']:
                    hit_tp = True
                    close_price = pos['tp']
            else: # sell
                if current_candle['high'] >= pos['sl']:
                    hit_sl = True
                    close_price = pos['sl']
                elif current_candle['low'] <= pos['tp']:
                    hit_tp = True
                    close_price = pos['tp']
                    
            if hit_sl or hit_tp:
                raw_pnl_pct = (close_price - pos['entry']) / pos['entry'] if pos['side'] == 'buy' else (pos['entry'] - close_price) / pos['entry']
                raw_pnl_pct *= pos['leverage']
                
                fee_impact = TAKER_FEE * pos['leverage'] * 2
                net_pnl_pct = raw_pnl_pct - fee_impact
                
                net_pnl = pos['allocated_margin'] * net_pnl_pct
                balance += net_pnl
                
                trade_log.append({
                    "entry_time": pos['time'],
                    "exit_time": current_candle['time'],
                    "side": pos['side'],
                    "result": "TP" if hit_tp else "SL",
                    "pnl": net_pnl,
                    "pnl_pct": net_pnl_pct * 100,
                    "kelly_risk": pos['kelly_risk']
                })
                positions.clear()
        
        # If no position, evaluate entry
        if not positions:
            bb_range = current_candle['bb_upper'] - current_candle['bb_lower']
            bb_pos = 50
            if bb_range > 0:
                bb_pos = (current_candle['close'] - current_candle['bb_lower']) / bb_range * 100
            
            trend_dir = "bullish" if current_candle['momentum_14'] > 0 else "bearish"
            
            # Trend Alignment Logic
            t_align = 0
            if pd.notna(current_candle['sma50']) and pd.notna(current_candle['sma200']):
                if current_candle['sma50'] > current_candle['sma200']:
                    t_align = 1
                elif current_candle['sma50'] < current_candle['sma200']:
                    t_align = -1
            
            indicators = {
                'rsi': current_candle['rsi'],
                'adx': 30 if abs(current_candle['momentum_14']) > current_candle['atr'] * 2 else 15, # Proxy
                'atr_pct': current_candle['atr'] / current_candle['close'],
                'volume_ratio': current_candle['volume'] / current_candle['vol_sma20'] if current_candle['vol_sma20'] > 0 else 1.0,
                'trend_align': t_align,
                'bb_width_pct': bb_range / current_candle['close'],
                'bb_position': {
                    'width_pct': bb_range / current_candle['close'],
                    'position': 'above_upper' if bb_pos > 100 else 'below_lower' if bb_pos < 0 else 'above_mid' if bb_pos > 50 else 'below_mid'
                }
            }
            
            features = ml_predictor.extract_features(indicators, {})
            prediction = ml_predictor.predict(features, trend_dir)
            
            win_prob = prediction.get("probability", 0.5)
            entry = current_candle['close']
            atr = current_candle['atr']
            
            if win_prob >= 0.50:
                if trend_dir == "bullish":
                    sl = entry - (atr * 1.5)
                    tp = entry + (atr * 2.5)
                else:
                    sl = entry + (atr * 1.5)
                    tp = entry - (atr * 2.5)
                
                rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
                
                if rr > 0:
                    kelly = win_prob - ((1 - win_prob) / rr)
                    raw_risk = min(max(kelly, 0.0), 1.0) * 0.5 * 0.08 
                    
                    if raw_risk > 0.001: 
                        lev = 5 
                        allocated_margin = balance * raw_risk * lev
                        
                        positions.append({
                            "time": current_candle['time'],
                            "side": "buy" if trend_dir == "bullish" else "sell",
                            "entry": entry,
                            "sl": sl,
                            "tp": tp,
                            "leverage": lev,
                            "kelly_risk": raw_risk * 100,
                            "allocated_margin": allocated_margin,
                        })

    wins = [t for t in trade_log if t['pnl'] > 0]
    win_rate = len(wins) / len(trade_log) if trade_log else 0
    total_pnl = sum(t['pnl'] for t in trade_log)
    roi_pct = (balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    avg_kelly = np.mean([t['kelly_risk'] for t in trade_log]) if trade_log else 0
    
    return {
        "symbol": symbol,
        "interval": interval_name,
        "trades": len(trade_log),
        "win_rate": round(win_rate * 100, 2),
        "roi_pct": round(roi_pct, 2),
        "net_profit": round(total_pnl, 2),
        "avg_kelly": round(avg_kelly, 2)
    }

async def main():
    print("=== OKX 30-Day Walk-Forward Backtest Simulator ===")
    results = []
    
    try:
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                interval = tf.lower() if "m" in tf.lower() else tf.upper() 
                df = await fetch_okx_historical_klines(symbol, interval, DAYS_TO_FETCH)
                
                if df is not None and not df.empty:
                    stats = await run_backtest_simulation(symbol, df, tf)
                    if stats:
                        results.append(stats)
                else:
                    print(f"Failed to fetch {symbol} {tf} or no data returned.")
                    
        print("\n\n=== FINAL BACKTEST RESULTS MATRIX ===")
        print("| Symbol | Timeframe | Trades | Win Rate % | ROI % | Net Profit ($) | Avg Kelly % |")
        print("|---|---|---|---|---|---|---|")
        
        for r in results:
            print(f"| {r['symbol']} | {r['interval']} | {r['trades']} | {r['win_rate']}% | {r['roi_pct']}% | ${r['net_profit']} | {r['avg_kelly']}% |")
    except Exception as e:
        import traceback
        print("\n=== FATAL ERROR ===")
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())
