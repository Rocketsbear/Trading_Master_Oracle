"""
Machine Learning Predictive Engine (RandomForest Proxy)
用于在毫秒级将 18 层技术指标特征降维成单维度的“数学胜率 (Win Probability)”。
后期可替换为真实的 XGBoost/LightGBM 模型加载权重。
"""
from typing import Dict, Any
from loguru import logger
import os
import numpy as np
import xgboost as xgb

class MLPredictor:
    def __init__(self):
        self.version = "2.0-xgboost"
        self.model = None
        model_path = os.path.join(os.path.dirname(__file__), "models", "xgb_model.json")
        try:
            self.model = xgb.XGBClassifier()
            self.model.load_model(model_path)
            logger.info("🧠 本地 ML 预测引擎已初始化 (XGBoost v2.0)")
            logger.info("✅ 成功加载真实量化 XGBoost 模型!")
        except Exception as e:
            logger.error(f"❌ 加载 XGBoost 模型失败: {e}")

    def extract_features(self, indicators: Dict, exchange_data: Dict) -> Dict[str, float]:
        """将复杂的嵌套指标压扁为标准的数值特征张量 (Features)"""
        features = {}
        
        # 1. Price Action & Momentum
        features['rsi'] = float(indicators.get('rsi', 50))
        features['adx'] = float(indicators.get('adx', 20))
        features['atr_pct'] = float(indicators.get('atr_pct', 0.0))
        
        # 2. Bollinger Bands Oscillation (0.0 = lower band, 1.0 = upper band)
        bb = indicators.get('bb_position', {})
        features['bb_width_pct'] = float(bb.get('width_pct', 0.0))
        
        # Calculate numeric bb_pos if raw bands provided, else guess from 'position' string
        if 'bb_upper' in indicators and 'bb_lower' in indicators and 'close' in indicators:
            bb_range = indicators['bb_upper'] - indicators['bb_lower']
            features['bb_pos'] = (indicators['close'] - indicators['bb_lower']) / bb_range * 100 if bb_range > 0 else 50
        else:
            pos_str = bb.get('position', 'mid')
            if pos_str == 'above_upper': features['bb_pos'] = 110
            elif pos_str == 'above_mid': features['bb_pos'] = 75
            elif pos_str == 'below_mid': features['bb_pos'] = 25
            elif pos_str == 'below_lower': features['bb_pos'] = -10
            else: features['bb_pos'] = 50
            
        # 3. Volume & Flow
        features['volume_ratio'] = float(indicators.get('volume_ratio', 1.0))
        
        # 4. Trend Alignment & Volatility
        features['trend_align'] = indicators.get('trend_align', 0) # 1: bull, -1: bear, 0: flat

        return features

    def predict(self, features: Dict[str, float], direction: str = "bullish") -> Dict[str, Any]:
        """
        基于真实的量化 XGBoost 模型给出统计学胜率估计
        返回: 0.0 ~ 1.0 的胜率概率，以及预测信心
        """
        if not self.model:
            logger.warning("模型未加载，降级为默认胜率 0.5")
            return {"probability": 0.5, "confidence": "none"}
            
        side = 1.0 if direction == "bullish" else 0.0
        
        # Scale parameters to match the training pipeline (x100 for percentages)
        f_arr = [
            features.get('rsi', 50.0),
            features.get('adx', 20.0),
            features.get('atr_pct', 0.0) * 100.0,
            features.get('volume_ratio', 1.0),
            float(features.get('trend_align', 0.0)),
            features.get('bb_width_pct', 0.0) * 100.0,
            features.get('bb_pos', 50.0),
            side
        ]
        
        try:
            # Reshape for single prediction in scikit-learn/xgboost API
            x_matrix = np.array([f_arr])
            
            # Predict probability of class 1 (Win)
            prob_win = float(self.model.predict_proba(x_matrix)[0][1])
            
            # Since market is extremely loud, clamp extremely confident spurious signals
            final_prob = max(0.20, min(0.75, prob_win))
            
            confidence = "high" if final_prob > 0.60 or final_prob < 0.40 else "medium" if final_prob > 0.55 or final_prob < 0.45 else "low"
            
            return {
                "probability": round(final_prob, 3),
                "raw_features": {
                    "rsi": round(f_arr[0], 1),
                    "vol": round(f_arr[3], 2),
                    "trend": f_arr[4],
                    "atr_pct": round(f_arr[2] / 100.0, 4)
                },
                "confidence": confidence,
                "version": self.version
            }
        except Exception as e:
            logger.error(f"XGBoost 推理报错: {e}")
            return {"probability": 0.5, "confidence": "none"}

ml_predictor = MLPredictor()
