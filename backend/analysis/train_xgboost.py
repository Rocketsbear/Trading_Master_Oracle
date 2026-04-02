import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
import os

DATA_FILE = os.path.join(os.path.dirname(__file__), "ml_training_data.csv")
MODEL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trading", "models", "xgb_model.json")

def main():
    print("=== XGBoost Real-world Training Pipeline ===")
    if not os.path.exists(DATA_FILE):
        print("Data file not found. Run data_generator.py first.")
        return
        
    df = pd.read_csv(DATA_FILE)
    print(f"Total labeled samples loaded: {len(df)}")
    
    # We drop any invalid or NaN rows
    df = df.dropna()
    
    features = ['rsi', 'adx', 'atr_pct', 'vol_ratio', 'trend_align', 'bb_width_pct', 'bb_pos', 'side']
    X = df[features]
    y = df['label']
    
    print(f"Features: {features}")
    print(f"Baseline Win Rate (Class Imbalance): {y.mean() * 100:.2f}%")
    
    # Temporal Split (DO NOT USE random split in quantitative finance to prevent lookahead bias)
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    print(f"Training on {len(X_train)} samples, Validating on {len(X_test)} samples (Walk-forward)...")
    
    # Calculate scale pos weight to handle class imbalance (if e.g. only 15% of trades win)
    num_neg = len(y_train[y_train == 0])
    num_pos = len(y_train[y_train == 1])
    scale_pos_weight = num_neg / num_pos if num_pos > 0 else 1.0
    
    # Initialize extreme gradient boosting classifier
    model = xgb.XGBClassifier(
        n_estimators=500,
        learning_rate=0.03, # Slow learning for better generalization
        max_depth=5,        # Shallow trees to prevent overfitting
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight, 
        eval_metric='auc',
        early_stopping_rounds=30,
        random_state=42
    )
    
    # Fit the forest
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=25
    )
    
    # Out of sample (OOS) evaluation
    preds = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, 1]
    
    print("\n=== Validation Results (OOS) ===")
    print(f"Accuracy: {accuracy_score(y_test, preds):.4f}")
    print(f"ROC AUC: {roc_auc_score(y_test, probs):.4f}")
    
    print("\nClassification Report:")
    print(classification_report(y_test, preds))
    
    print("\n=== Feature Importance (What matters most in Crypto?) ===")
    importance = model.feature_importances_
    for f, imp in sorted(zip(features, importance), key=lambda x: x[1], reverse=True):
        print(f"{f}: {imp * 100:.2f}%")
        
    os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
    model.save_model(MODEL_FILE)
    print(f"\n[SUCCESS] AI Quant Model exported to: {MODEL_FILE}")

if __name__ == "__main__":
    main()
