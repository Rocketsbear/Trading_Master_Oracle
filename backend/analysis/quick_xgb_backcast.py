import pandas as pd
import xgboost as xgb
import os

DATA_FILE = os.path.join(os.path.dirname(__file__), "ml_training_data.csv")
MODEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trading", "models", "xgb_model.json")

def calculate_kelly(prob_win, risk_reward=1.66):
    """Calculate Kelly Criterion fraction"""
    if prob_win <= 0 or prob_win >= 1:
        return 0.0
    q = 1.0 - prob_win
    kelly = prob_win - (q / risk_reward)
    return max(0.0, kelly)

def main():
    print("=== Vectorised XGBoost Quick Backcast (90 Days) ===")
    
    if not os.path.exists(DATA_FILE) or not os.path.exists(MODEL_FILE):
        print("Missing data or model file.")
        return
        
    df = pd.read_csv(DATA_FILE).dropna()
    model = xgb.XGBClassifier()
    model.load_model(MODEL_FILE)
    
    features = ['rsi', 'adx', 'atr_pct', 'vol_ratio', 'trend_align', 'bb_width_pct', 'bb_pos', 'side']
    X = df[features]
    
    print("Inferencing full dataset through XGBoost...")
    probs = model.predict_proba(X)[:, 1]
    df['prob_win'] = probs
    
    # Simulate V5 entry conditions: Trend aligned, Vol > 1.2, Prob > 0.50
    # Because ML is raw, let's just use Prob > 0.52 (a slight edge threshold) to take trades
    THRESHOLD = 0.55
    df['signal'] = (df['prob_win'] >= THRESHOLD)
    
    trades = df[df['signal'] == True].copy()
    print(f"\nTotal signals generated (Prob >= {THRESHOLD}): {len(trades)}")
    
    if len(trades) == 0:
        print("No trades triggered. The model is extremely conservative.")
        return
        
    # Calculate trading performance
    trades['kelly_frac'] = trades['prob_win'].apply(lambda p: calculate_kelly(p, 1.66))
    
    # We apply a max Kelly limit like V5 (max 8% risk per trade)
    trades['actual_risk'] = trades['kelly_frac'].clip(0, 0.08)
    
    # PNL calculation: 
    # Win = + (actual_risk * 1.66)
    # Loss = - actual_risk
    # Wait, actual_risk is the % of capital RISKED.
    # So if you risk 1%, and you hit TP (1.66 R:R), you make 1.66%.
    # If you hit SL, you lose 1.0%.
    
    def calc_trade_pnl_pct(row):
        if row['label'] == 1:
            return row['actual_risk'] * 1.66
        else:
            return -row['actual_risk']
            
    trades['trade_pnl_pct'] = trades.apply(calc_trade_pnl_pct, axis=1)
    
    win_rate = trades['label'].mean() * 100
    
    # Sequential compounding approximation (assuming non-overlapping or simple sum for demo)
    total_roi_pct = trades['trade_pnl_pct'].sum() * 100
    avg_kelly = trades['actual_risk'].mean() * 100
    
    out = []
    out.append("=== XGBoost Strategy Performance ===")
    out.append(f"Total Trades Taken:   {len(trades)}")
    out.append(f"Algorithm Win Rate:   {win_rate:.2f}%")
    out.append(f"Avg Kelly Risk/Trade: {avg_kelly:.2f}%")
    out.append(f"Estimated Total ROI:  {total_roi_pct:+.2f}%")
    out.append("\nPerformance by Ticker:")
    for sym in trades['symbol'].unique():
        sym_trades = trades[trades['symbol'] == sym]
        sym_win_rate = sym_trades['label'].mean() * 100
        sym_roi = sym_trades['trade_pnl_pct'].sum() * 100
        out.append(f" - {sym}: Trades={len(sym_trades)}, WinRate={sym_win_rate:.2f}%, Expected ROI={sym_roi:+.2f}%")
        
    final_output = "\n".join(out)
    print(final_output)
    with open("d:/tmp/xgb_metrics.txt", "w", encoding="utf-8") as f:
        f.write(final_output)

if __name__ == "__main__":
    main()
