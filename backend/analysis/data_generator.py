import asyncio
import httpx
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import sys

# Ensure backend modules can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Configuration
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
TIMEFRAMES = ["15m", "1H", "4H"] # Focus on profitable timeframes for ML
DAYS_TO_FETCH = 180 # 6 months of data for deep learning
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "ml_training_data.csv")
TP_ATR_MULTIPLIER = 2.5
SL_ATR_MULTIPLIER = 1.5

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
    df = df[df['time'] >= (start_time / 1000.0)]
    df = df.sort_values("time").reset_index(drop=True)
    return df

def generate_labeled_dataset(symbol, interval_name, df):
    """Calculate features and apply lookahead to generate labels."""
    if len(df) < 200:
        return []
        
    print(f"[{symbol} | {interval_name}] Computing feature matrix...")
    
    df['rsi'] = calc_rsi(df['close'], 14).fillna(50)
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['sma20'] + 2 * df['std20']
    df['bb_lower'] = df['sma20'] - 2 * df['std20']
    
    df['sma50'] = df['close'].rolling(window=50).mean()
    df['sma200'] = df['close'].rolling(window=200).mean()
    
    df['atr'] = calc_atr(df['high'], df['low'], df['close'], 14).fillna(0)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().fillna(0)
    df['momentum_14'] = df['close'] - df['close'].shift(14)
    df['momentum_14'] = df['momentum_14'].fillna(0)
    
    dataset = []
    total_candles = len(df)
    
    # We stop evaluating 100 candles before the end to ensure lookahead has space
    for i in range(200, total_candles - 100):
        current = df.iloc[i]
        
        # Calculate Features
        bb_range = current['bb_upper'] - current['bb_lower']
        bb_pos = 50
        if bb_range > 0:
            bb_pos = (current['close'] - current['bb_lower']) / bb_range * 100
            
        t_align = 0
        if pd.notna(current['sma50']) and pd.notna(current['sma200']):
            if current['sma50'] > current['sma200']:
                t_align = 1
            elif current['sma50'] < current['sma200']:
                t_align = -1
                
        volume_ratio = current['volume'] / current['vol_sma20'] if current['vol_sma20'] > 0 else 1.0
        atr_pct = current['atr'] / current['close'] if current['close'] > 0 else 0
        bb_width_pct = bb_range / current['close'] if current['close'] > 0 else 0
        
        # ADX Proxy
        adx_proxy = 30 if abs(current['momentum_14']) > current['atr'] * 2 else 15
        
        entry_price = current['close']
        atr = current['atr']
        
        if atr <= 0:
            continue
            
        # Simulate BUY trade
        tp_buy = entry_price + (atr * TP_ATR_MULTIPLIER)
        sl_buy = entry_price - (atr * SL_ATR_MULTIPLIER)
        label_buy = 0
        
        # Lookahead into future prices for BUY
        for j in range(i + 1, min(i + 100, total_candles)):
            future = df.iloc[j]
            if future['low'] <= sl_buy:
                label_buy = 0
                break
            if future['high'] >= tp_buy:
                label_buy = 1
                break
                
        # Simulate SELL trade
        tp_sell = entry_price - (atr * TP_ATR_MULTIPLIER)
        sl_sell = entry_price + (atr * SL_ATR_MULTIPLIER)
        label_sell = 0
        
        # Lookahead into future prices for SELL
        for j in range(i + 1, min(i + 100, total_candles)):
            future = df.iloc[j]
            if future['high'] >= sl_sell:
                label_sell = 0
                break
            if future['low'] <= tp_sell:
                label_sell = 1
                break
                
        # We only append trades that show SOME momentum / volatility, to avoid training on flatlines
        # A simple filter: only if bb_width_pct is compressed and vol_ratio is somewhat high, OR just take all
        # To make the ML robust, we should train it on ALL data.
        
        # Append BUY sample
        dataset.append({
            "symbol": symbol,
            "interval": interval_name,
            "time": current['time'],
            "side": 1, # 1 for Buy
            "rsi": round(current['rsi'], 2),
            "adx": round(adx_proxy, 2),
            "atr_pct": round(atr_pct * 100, 4),
            "vol_ratio": round(volume_ratio, 2),
            "trend_align": t_align,
            "bb_width_pct": round(bb_width_pct * 100, 4),
            "bb_pos": round(bb_pos, 2),
            "label": label_buy
        })
        
        # Append SELL sample
        dataset.append({
            "symbol": symbol,
            "interval": interval_name,
            "time": current['time'],
            "side": 0, # 0 for Sell
            "rsi": round(current['rsi'], 2),
            "adx": round(adx_proxy, 2),
            "atr_pct": round(atr_pct * 100, 4),
            "vol_ratio": round(volume_ratio, 2),
            "trend_align": t_align,
            "bb_width_pct": round(bb_width_pct * 100, 4),
            "bb_pos": round(bb_pos, 2),
            "label": label_sell
        })
        
    return dataset

async def main():
    print("=== XGBoost Data Generator (V5 Rules) ===")
    all_datasets = []
    
    try:
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                interval = tf.lower() if "m" in tf.lower() else tf.upper() 
                df = await fetch_okx_historical_klines(symbol, interval, DAYS_TO_FETCH)
                
                if df is not None and not df.empty:
                    dataset = generate_labeled_dataset(symbol, tf, df)
                    all_datasets.extend(dataset)
                    print(f"[{symbol} | {tf}] Generated {len(dataset)} labeled samples.")
                else:
                    print(f"Failed to fetch {symbol} {tf} or no data returned.")
                    
        # Export logic
        if all_datasets:
            final_df = pd.DataFrame(all_datasets)
            final_df.to_csv(OUTPUT_CSV, index=False)
            
            total_samples = len(final_df)
            wins = len(final_df[final_df['label'] == 1])
            baseline_winrate = (wins / total_samples) * 100 if total_samples > 0 else 0
            
            print("\n=== DATA EXPORT SUCCESS ===")
            print(f"Total Labeled Samples: {total_samples}")
            print(f"Baseline Win Rate (Random Entry): {baseline_winrate:.2f}%")
            print(f"Output File: {OUTPUT_CSV}")
            
    except Exception as e:
        import traceback
        print("\n=== FATAL ERROR ===")
        print(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())
