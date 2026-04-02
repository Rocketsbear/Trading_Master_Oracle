"""
技术指标计算模块
提供 MACD、RSI、Bollinger Bands、ADX、ATR、OBV、VWAP 等
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from loguru import logger


class TechnicalIndicators:
    """技术指标计算器"""
    
    @staticmethod
    def calculate_macd(
        df: pd.DataFrame,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> pd.DataFrame:
        """计算 MACD 指标"""
        df = df.copy()
        ema_fast = df['close'].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow_period, adjust=False).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=signal_period, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        return df
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算 RSI 指标"""
        df = df.copy()
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        return df
    
    @staticmethod
    def calculate_bollinger_bands(
        df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
    ) -> pd.DataFrame:
        """计算布林带"""
        df = df.copy()
        df['bb_middle'] = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        df['bb_upper'] = df['bb_middle'] + (std * std_dev)
        df['bb_lower'] = df['bb_middle'] - (std * std_dev)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        return df
    
    @staticmethod
    def calculate_moving_averages(
        df: pd.DataFrame, periods: list = [20, 50, 200]
    ) -> pd.DataFrame:
        """计算移动平均线"""
        df = df.copy()
        for period in periods:
            df[f'ma_{period}'] = df['close'].rolling(window=period).mean()
        return df
    
    @staticmethod
    def calculate_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """计算成交量指标: OBV, VWAP"""
        df = df.copy()
        df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
        df['volume_ma_20'] = df['volume'].rolling(window=20).mean()
        return df
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        计算 ADX (Average Directional Index) + ATR
        ADX > 25: 趋势市场, ADX < 20: 震荡市场
        """
        df = df.copy()
        high, low, close = df['high'], df['low'], df['close']
        
        # True Range → ATR
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=period).mean()
        
        # +DM / -DM
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        plus_dm_smooth = pd.Series(plus_dm, index=df.index).rolling(window=period).mean()
        minus_dm_smooth = pd.Series(minus_dm, index=df.index).rolling(window=period).mean()
        
        # +DI / -DI
        df['plus_di'] = (plus_dm_smooth / df['atr']) * 100
        df['minus_di'] = (minus_dm_smooth / df['atr']) * 100
        
        # DX → ADX
        dx = abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']) * 100
        df['adx'] = dx.rolling(window=period).mean()
        
        return df
    
    @staticmethod
    def detect_market_regime(df: pd.DataFrame) -> Dict[str, Any]:
        """
        市场状态检测器
        输出: trending_up / trending_down / ranging / volatile
        """
        latest = df.iloc[-1]
        adx = float(latest.get('adx', 20))
        atr = float(latest.get('atr', 0))
        bb_width = float(latest.get('bb_width', 0.02))
        plus_di = float(latest.get('plus_di', 25))
        minus_di = float(latest.get('minus_di', 25))
        close = float(latest['close'])
        
        atr_pct = atr / close * 100 if close > 0 else 1
        
        if adx > 25 and plus_di > minus_di:
            regime = "trending_up"
            description = "上升趋势"
            strategy_hint = "趋势跟踪: 做多为主, 用MA支撑入场, 宽止损"
        elif adx > 25 and minus_di > plus_di:
            regime = "trending_down"
            description = "下降趋势"
            strategy_hint = "趋势跟踪: 做空为主, 用MA阻力入场, 宽止损"
        elif atr_pct > 3.0 or bb_width > 0.06:
            regime = "volatile"
            description = "高波动"
            strategy_hint = "降杠杆, 扩大SL, 减小仓位, 或观望"
        else:
            regime = "ranging"
            description = "震荡区间"
            strategy_hint = "均值回归: BB反弹策略, 区间高抛低吸, 小止损"
        
        return {
            "regime": regime,
            "description": description,
            "strategy_hint": strategy_hint,
            "adx": round(adx, 1),
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct, 3),
            "bb_width": round(bb_width, 4),
            "trend_strength": "强" if adx > 30 else "中" if adx > 20 else "弱",
        }

    # ===== 新增增强指标 =====
    
    @staticmethod
    def calculate_stoch_rsi(df: pd.DataFrame, rsi_period: int = 14, 
                            stoch_period: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> pd.DataFrame:
        """
        Stochastic RSI — RSI 的随机指标
        比 RSI 更灵敏的超买超卖检测
        K < 20 = 超卖, K > 80 = 超买, K/D 交叉 = 信号
        """
        df = df.copy()
        # First compute RSI if not already present
        if 'rsi' not in df.columns:
            df = TechnicalIndicators.calculate_rsi(df, rsi_period)
        
        rsi = df['rsi']
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min)
        stoch_rsi = stoch_rsi.fillna(0.5)
        
        df['stoch_rsi_k'] = stoch_rsi.rolling(window=k_smooth).mean() * 100
        df['stoch_rsi_d'] = df['stoch_rsi_k'].rolling(window=d_smooth).mean()
        return df
    
    @staticmethod
    def calculate_ema_fast(df: pd.DataFrame, periods: list = [8, 21]) -> pd.DataFrame:
        """EMA(8/21) 快速均线 — 日内交易入场/离场信号"""
        df = df.copy()
        for p in periods:
            df[f'ema_{p}'] = df['close'].ewm(span=p, adjust=False).mean()
        return df
    
    @staticmethod
    def calculate_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
        """
        经典 Pivot Points — 基于前一根K线的HLC
        P = (H+L+C)/3,  R1 = 2P-L,  S1 = 2P-H,  R2 = P+(H-L),  S2 = P-(H-L)
        """
        df = df.copy()
        prev_high = df['high'].shift(1)
        prev_low = df['low'].shift(1)
        prev_close = df['close'].shift(1)
        
        df['pivot'] = (prev_high + prev_low + prev_close) / 3
        df['pivot_r1'] = 2 * df['pivot'] - prev_low
        df['pivot_s1'] = 2 * df['pivot'] - prev_high
        df['pivot_r2'] = df['pivot'] + (prev_high - prev_low)
        df['pivot_s2'] = df['pivot'] - (prev_high - prev_low)
        return df
    
    @staticmethod
    def calculate_williams_r(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Williams %R — 超买超卖指标, 范围 -100 到 0"""
        df = df.copy()
        highest_high = df['high'].rolling(window=period).max()
        lowest_low = df['low'].rolling(window=period).min()
        df['williams_r'] = -100 * (highest_high - df['close']) / (highest_high - lowest_low)
        return df
    
    @staticmethod
    def calculate_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        """
        Supertrend — ATR自适应趋势跟踪线
        价格在 Supertrend 之上 = 多头, 之下 = 空头
        方向翻转 = 强烈趋势变化信号
        """
        df = df.copy()
        if 'atr' not in df.columns:
            df = TechnicalIndicators.calculate_adx(df, period)
        
        hl2 = (df['high'] + df['low']) / 2
        atr = df['atr']
        
        upper_band = hl2 + multiplier * atr
        lower_band = hl2 - multiplier * atr
        
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)
        
        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = -1
        
        for i in range(1, len(df)):
            if df['close'].iloc[i] > upper_band.iloc[i - 1]:
                direction.iloc[i] = 1
            elif df['close'].iloc[i] < lower_band.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]
                
                if direction.iloc[i] == 1 and lower_band.iloc[i] < lower_band.iloc[i - 1]:
                    lower_band.iloc[i] = lower_band.iloc[i - 1]
                if direction.iloc[i] == -1 and upper_band.iloc[i] > upper_band.iloc[i - 1]:
                    upper_band.iloc[i] = upper_band.iloc[i - 1]
            
            supertrend.iloc[i] = lower_band.iloc[i] if direction.iloc[i] == 1 else upper_band.iloc[i]
        
        df['supertrend'] = supertrend
        df['supertrend_dir'] = direction  # 1 = bullish, -1 = bearish
        return df

    @staticmethod
    def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标（含增强指标）"""
        df = TechnicalIndicators.calculate_macd(df)
        df = TechnicalIndicators.calculate_rsi(df)
        df = TechnicalIndicators.calculate_bollinger_bands(df)
        df = TechnicalIndicators.calculate_moving_averages(df)
        df = TechnicalIndicators.calculate_volume_indicators(df)
        df = TechnicalIndicators.calculate_adx(df)
        # Enhanced indicators
        df = TechnicalIndicators.calculate_stoch_rsi(df)
        df = TechnicalIndicators.calculate_ema_fast(df)
        df = TechnicalIndicators.calculate_pivot_points(df)
        df = TechnicalIndicators.calculate_williams_r(df)
        df = TechnicalIndicators.calculate_supertrend(df)
        logger.info("所有技术指标计算完成 (含增强指标: StochRSI/EMA/Pivot/WilliamsR/Supertrend)")
        return df
    
    @staticmethod
    def analyze_indicators(df: pd.DataFrame) -> Dict[str, Any]:
        """
        分析技术指标 — 置信度加权评分模型
        每个信号附带 confidence 权重，最终加权平均
        """
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        signals_list = []
        
        # 1. MACD
        macd_cross = "golden" if latest['macd'] > latest['macd_signal'] and prev['macd'] <= prev['macd_signal'] else \
                     "death" if latest['macd'] < latest['macd_signal'] and prev['macd'] >= prev['macd_signal'] else "none"
        macd_trend = "bullish" if latest['macd'] > 0 else "bearish"
        
        if macd_cross == 'golden':
            signals_list.append({"name": "MACD_cross", "score": 80, "confidence": 0.9})
        elif macd_cross == 'death':
            signals_list.append({"name": "MACD_cross", "score": 20, "confidence": 0.9})
        elif macd_trend == 'bullish':
            signals_list.append({"name": "MACD_trend", "score": 60, "confidence": 0.5})
        else:
            signals_list.append({"name": "MACD_trend", "score": 40, "confidence": 0.5})
        
        # 2. RSI
        rsi_val = float(latest['rsi'])
        rsi_status = "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"
        
        if rsi_val < 20:
            signals_list.append({"name": "RSI", "score": 90, "confidence": 0.95})
        elif rsi_val < 30:
            signals_list.append({"name": "RSI", "score": 75, "confidence": 0.8})
        elif rsi_val > 80:
            signals_list.append({"name": "RSI", "score": 10, "confidence": 0.95})
        elif rsi_val > 70:
            signals_list.append({"name": "RSI", "score": 25, "confidence": 0.8})
        else:
            signals_list.append({"name": "RSI", "score": 50, "confidence": 0.3})
        
        # 3. Bollinger Band
        bb_pos = "above_upper" if latest['close'] > latest['bb_upper'] else \
                 "below_lower" if latest['close'] < latest['bb_lower'] else "middle"
        
        if bb_pos == 'below_lower':
            signals_list.append({"name": "BB", "score": 75, "confidence": 0.7})
        elif bb_pos == 'above_upper':
            signals_list.append({"name": "BB", "score": 25, "confidence": 0.7})
        else:
            signals_list.append({"name": "BB", "score": 50, "confidence": 0.2})
        
        # 4. 均线排列
        ma_trend = "bullish" if latest['close'] > latest['ma_20'] > latest['ma_50'] else \
                   "bearish" if latest['close'] < latest['ma_20'] < latest['ma_50'] else "mixed"
        
        if ma_trend == 'bullish':
            signals_list.append({"name": "MA", "score": 70, "confidence": 0.75})
        elif ma_trend == 'bearish':
            signals_list.append({"name": "MA", "score": 30, "confidence": 0.75})
        else:
            signals_list.append({"name": "MA", "score": 50, "confidence": 0.3})
        
        # 5. 量价关系
        vol_ratio = float(latest['volume'] / latest['volume_ma_20']) if latest['volume_ma_20'] > 0 else 1
        obv_trend = "increasing" if latest['obv'] > prev['obv'] else "decreasing"
        
        if vol_ratio > 1.5 and obv_trend == 'increasing':
            signals_list.append({"name": "Volume", "score": 70, "confidence": 0.6})
        elif vol_ratio > 1.5 and obv_trend == 'decreasing':
            signals_list.append({"name": "Volume", "score": 30, "confidence": 0.6})
        else:
            signals_list.append({"name": "Volume", "score": 50, "confidence": 0.2})
        
        # 6. ADX 趋势强度
        adx_val = float(latest.get('adx', 20))
        plus_di = float(latest.get('plus_di', 25))
        minus_di = float(latest.get('minus_di', 25))
        
        if adx_val > 25:
            if plus_di > minus_di:
                signals_list.append({"name": "ADX", "score": 70, "confidence": 0.7})
            else:
                signals_list.append({"name": "ADX", "score": 30, "confidence": 0.7})
        else:
            signals_list.append({"name": "ADX", "score": 50, "confidence": 0.2})
        
        # ===== 7. Stochastic RSI =====
        stoch_k = float(latest.get('stoch_rsi_k', 50))
        stoch_d = float(latest.get('stoch_rsi_d', 50))
        prev_stoch_k = float(prev.get('stoch_rsi_k', 50))
        prev_stoch_d = float(prev.get('stoch_rsi_d', 50))
        stoch_cross_up = stoch_k > stoch_d and prev_stoch_k <= prev_stoch_d
        stoch_cross_down = stoch_k < stoch_d and prev_stoch_k >= prev_stoch_d
        
        if stoch_k < 20 and stoch_cross_up:
            signals_list.append({"name": "StochRSI", "score": 85, "confidence": 0.85})
        elif stoch_k < 20:
            signals_list.append({"name": "StochRSI", "score": 75, "confidence": 0.7})
        elif stoch_k > 80 and stoch_cross_down:
            signals_list.append({"name": "StochRSI", "score": 15, "confidence": 0.85})
        elif stoch_k > 80:
            signals_list.append({"name": "StochRSI", "score": 25, "confidence": 0.7})
        else:
            signals_list.append({"name": "StochRSI", "score": 50, "confidence": 0.25})
        
        # ===== 8. EMA(8/21) =====
        ema8 = float(latest.get('ema_8', latest['close']))
        ema21 = float(latest.get('ema_21', latest['close']))
        prev_ema8 = float(prev.get('ema_8', prev['close']))
        prev_ema21 = float(prev.get('ema_21', prev['close']))
        ema_cross_up = ema8 > ema21 and prev_ema8 <= prev_ema21
        ema_cross_down = ema8 < ema21 and prev_ema8 >= prev_ema21
        
        if ema_cross_up:
            signals_list.append({"name": "EMA8/21", "score": 80, "confidence": 0.85})
        elif ema_cross_down:
            signals_list.append({"name": "EMA8/21", "score": 20, "confidence": 0.85})
        elif ema8 > ema21:
            signals_list.append({"name": "EMA8/21", "score": 62, "confidence": 0.5})
        else:
            signals_list.append({"name": "EMA8/21", "score": 38, "confidence": 0.5})
        
        # ===== 9. Supertrend =====
        st_dir = int(latest.get('supertrend_dir', 0))
        prev_st_dir = int(prev.get('supertrend_dir', 0))
        st_flip = st_dir != prev_st_dir and st_dir != 0
        
        if st_flip and st_dir == 1:
            signals_list.append({"name": "Supertrend", "score": 82, "confidence": 0.9})
        elif st_flip and st_dir == -1:
            signals_list.append({"name": "Supertrend", "score": 18, "confidence": 0.9})
        elif st_dir == 1:
            signals_list.append({"name": "Supertrend", "score": 63, "confidence": 0.55})
        elif st_dir == -1:
            signals_list.append({"name": "Supertrend", "score": 37, "confidence": 0.55})
        else:
            signals_list.append({"name": "Supertrend", "score": 50, "confidence": 0.2})
        
        # === 置信度加权评分 ===
        total_weight = sum(s['confidence'] for s in signals_list)
        weighted_score = sum(s['score'] * s['confidence'] for s in signals_list) / total_weight if total_weight > 0 else 50
        
        # 信号一致性奖金 (now with 9 signals, higher threshold)
        bullish_signals = sum(1 for s in signals_list if s['score'] > 55 and s['confidence'] > 0.4)
        bearish_signals = sum(1 for s in signals_list if s['score'] < 45 and s['confidence'] > 0.4)
        
        agreement_bonus = 0
        if bullish_signals >= 6:
            agreement_bonus = 8
        elif bullish_signals >= 4:
            agreement_bonus = 5
        elif bearish_signals >= 6:
            agreement_bonus = -8
        elif bearish_signals >= 4:
            agreement_bonus = -5
        
        score = max(0, min(100, int(weighted_score + agreement_bonus)))
        
        # === 市场状态 ===
        regime = TechnicalIndicators.detect_market_regime(df)
        
        # === Pivot Point proximity ===
        pivot = float(latest.get('pivot', latest['close']))
        pivot_r1 = float(latest.get('pivot_r1', pivot * 1.01))
        pivot_s1 = float(latest.get('pivot_s1', pivot * 0.99))
        pivot_r2 = float(latest.get('pivot_r2', pivot * 1.02))
        pivot_s2 = float(latest.get('pivot_s2', pivot * 0.98))
        current = float(latest['close'])
        pivot_bias = "above_pivot" if current > pivot else "below_pivot"
        
        # Williams %R
        williams_r = float(latest.get('williams_r', -50))
        williams_status = "oversold" if williams_r < -80 else "overbought" if williams_r > -20 else "neutral"
        
        signals = {
            "macd": {
                "value": float(latest['macd']),
                "signal": float(latest['macd_signal']),
                "histogram": float(latest['macd_hist']),
                "cross": macd_cross,
                "trend": macd_trend,
            },
            "rsi": {
                "value": rsi_val,
                "status": rsi_status,
                "trend": "bullish" if rsi_val > prev['rsi'] else "bearish",
            },
            "bollinger": {
                "upper": float(latest['bb_upper']),
                "middle": float(latest['bb_middle']),
                "lower": float(latest['bb_lower']),
                "width": float(latest['bb_width']),
                "position": bb_pos,
                "squeeze": latest['bb_width'] < 0.02,
            },
            "moving_averages": {
                "ma_20": float(latest['ma_20']),
                "ma_50": float(latest['ma_50']),
                "ma_200": float(latest.get('ma_200', latest['ma_50'])),
                "trend": ma_trend,
            },
            "volume": {
                "obv": float(latest['obv']),
                "vwap": float(latest['vwap']),
                "volume_ratio": vol_ratio,
                "trend": obv_trend,
            },
            "adx": {
                "value": adx_val,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "trend_strength": "强" if adx_val > 30 else "中" if adx_val > 20 else "弱",
            },
            "atr": {
                "value": float(latest.get('atr', 0)),
                "pct": round(float(latest.get('atr', 0)) / float(latest['close']) * 100, 3) if latest['close'] > 0 else 0,
            },
            # New enhanced indicators
            "stoch_rsi": {
                "k": round(stoch_k, 1),
                "d": round(stoch_d, 1),
                "cross_up": stoch_cross_up,
                "cross_down": stoch_cross_down,
                "status": "oversold" if stoch_k < 20 else "overbought" if stoch_k > 80 else "neutral",
            },
            "ema_fast": {
                "ema_8": round(ema8, 2),
                "ema_21": round(ema21, 2),
                "cross_up": ema_cross_up,
                "cross_down": ema_cross_down,
                "trend": "bullish" if ema8 > ema21 else "bearish",
            },
            "supertrend": {
                "value": round(float(latest.get('supertrend', 0)), 2),
                "direction": st_dir,
                "flip": st_flip,
                "trend": "bullish" if st_dir == 1 else "bearish",
            },
            "pivot_points": {
                "pivot": round(pivot, 2),
                "r1": round(pivot_r1, 2),
                "s1": round(pivot_s1, 2),
                "r2": round(pivot_r2, 2),
                "s2": round(pivot_s2, 2),
                "bias": pivot_bias,
            },
            "williams_r": {
                "value": round(williams_r, 1),
                "status": williams_status,
            },
            "market_regime": regime,
            "signal_details": signals_list,
            "agreement_bonus": agreement_bonus,
            "overall_score": score,
            "overall_trend": "bullish" if score > 60 else "bearish" if score < 40 else "neutral",
        }
        
        logger.info(f"技术分析完成: 评分{score}, 状态={regime['regime']}, ADX={adx_val:.1f}, StochRSI={stoch_k:.0f}, ST={'↑' if st_dir==1 else '↓'}")
        return signals