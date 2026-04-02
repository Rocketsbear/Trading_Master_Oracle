"""
信号冲突矩阵 — Signal Conflict Resolution Matrix
定义高胜率信号组合和冲突组合，用于最终评分调整
"""
from typing import Dict, List, Tuple
from loguru import logger


def evaluate_signal_conflicts(indicators: Dict) -> Dict:
    """
    评估信号冲突/共振，返回最终调整分数
    
    输入: indicators dict from quick_analyze, containing:
      - rsi, adx, trend_15m, trend_1h, trend_4h
      - macd_growing, bb_position, volume_ratio
      - stoch_rsi, market_regime, smc_structure
      - orderbook_imbalance
    
    输出: {
        "adjustment": int (-8 to +8),
        "confidence_level": "high" | "medium" | "low" | "conflict",
        "reasons": [str],
        "combo_name": str | None,
    }
    """
    reasons = []
    adjustment = 0
    combo_name = None
    
    rsi = indicators.get("rsi", 50)
    adx = indicators.get("adx", 20)
    trend_15m = indicators.get("trend_15m", 0)
    trend_1h = indicators.get("trend_1h", 0)
    trend_4h = indicators.get("trend_4h", 0)
    macd_growing = indicators.get("macd_growing", False)
    bb_pos = indicators.get("bb_position", 50)
    vol_ratio = indicators.get("volume_ratio", 1.0)
    stoch_rsi = indicators.get("stoch_rsi", 50)
    market_regime = indicators.get("market_regime", "ranging")
    smc_structure = indicators.get("smc_structure", "neutral")
    orderbook_imbalance = indicators.get("orderbook_imbalance", 1.0)
    
    trends_aligned = (trend_15m > 0 and trend_1h > 0 and trend_4h > 0)
    trends_aligned_bear = (trend_15m < 0 and trend_1h < 0 and trend_4h < 0)
    
    # ===== HIGH CONFIDENCE COMBOS (多信号共振) =====
    
    # COMBO 1: 全面多头共振 — 趋势+动量+成交量+结构全部一致
    if (trends_aligned and macd_growing and rsi > 50 and rsi < 70 
        and vol_ratio > 1.2 and smc_structure == "bullish" and adx > 25):
        adjustment += 8
        combo_name = "🔥 全面多头共振"
        reasons.append("趋势+MACD+量能+SMC全部多头确认")
    
    # COMBO 2: 全面空头共振
    elif (trends_aligned_bear and macd_growing and rsi < 50 and rsi > 30
          and vol_ratio > 1.2 and smc_structure == "bearish" and adx > 25):
        adjustment -= 8
        combo_name = "🔥 全面空头共振"
        reasons.append("趋势+MACD+量能+SMC全部空头确认")
    
    # COMBO 3: 超卖反弹信号 — RSI + StochRSI 双超卖 + 订单簿支撑
    elif (rsi < 30 and stoch_rsi is not None and stoch_rsi < 20 
          and bb_pos < 15 and orderbook_imbalance > 1.3):
        adjustment += 6
        combo_name = "📈 超卖反弹共振"
        reasons.append("RSI+StochRSI双超卖+BB下轨+买盘支撑")
    
    # COMBO 4: 超买回调信号
    elif (rsi > 70 and stoch_rsi is not None and stoch_rsi > 80 
          and bb_pos > 85 and orderbook_imbalance < 0.77):
        adjustment -= 6
        combo_name = "📉 超买回调共振"
        reasons.append("RSI+StochRSI双超买+BB上轨+卖盘压制")
    
    # COMBO 5: 趋势确认 + 量能确认 (中等强度)
    elif trends_aligned and vol_ratio > 1.5 and adx > 20:
        adjustment += 4
        combo_name = "📊 趋势量能共振"
        reasons.append("多时间框架一致+放量确认")
    elif trends_aligned_bear and vol_ratio > 1.5 and adx > 20:
        adjustment -= 4
        combo_name = "📊 趋势量能空头"
        reasons.append("多时间框架空头+放量确认")
    
    # ===== CONFLICT COMBOS (信号冲突) =====
    
    # CONFLICT 1: 趋势多 + RSI超买 + 量缩 = 潜在顶部
    if trend_15m > 0 and trend_1h > 0 and rsi > 70 and vol_ratio < 0.8:
        conflict_adj = -5
        adjustment += conflict_adj
        reasons.append(f"⚠️ 趋势多但RSI超买+缩量{conflict_adj}")
        if combo_name is None:
            combo_name = "⚠️ 顶部背离"
    
    # CONFLICT 2: 趋势空 + RSI超卖 + 量缩 = 潜在底部
    elif trend_15m < 0 and trend_1h < 0 and rsi < 30 and vol_ratio < 0.8:
        conflict_adj = 5
        adjustment += conflict_adj
        reasons.append(f"⚠️ 趋势空但RSI超卖+缩量{'+' if conflict_adj > 0 else ''}{conflict_adj}")
        if combo_name is None:
            combo_name = "⚠️ 底部背离"
    
    # CONFLICT 3: 震荡市 + 强方向信号 = 降信心
    if market_regime == "ranging" and adx < 20:
        if abs(adjustment) > 3:
            dampen = -int(adjustment * 0.4)  # 减弱 40%
            reasons.append(f"震荡市信号减弱{dampen:+d}")
            adjustment += dampen
    
    # CONFLICT 4: 订单簿 vs 趋势冲突
    if orderbook_imbalance > 1.5 and trend_15m < 0 and trend_1h < 0:
        reasons.append("⚠️ 订单簿买方强但趋势空头，注意假突破")
        adjustment -= 2
    elif orderbook_imbalance < 0.67 and trend_15m > 0 and trend_1h > 0:
        reasons.append("⚠️ 订单簿卖方强但趋势多头，注意假跌破")
        adjustment += 2
    
    # Clamp final adjustment
    adjustment = max(-8, min(8, adjustment))
    
    # Determine confidence level
    if abs(adjustment) >= 6:
        confidence = "high"
    elif abs(adjustment) >= 3:
        confidence = "medium"
    elif len(reasons) > 1 and any("⚠️" in r for r in reasons):
        confidence = "conflict"
    else:
        confidence = "low"
    
    if not reasons:
        reasons.append("无明显信号共振或冲突")
    
    return {
        "adjustment": adjustment,
        "confidence_level": confidence,
        "reasons": reasons,
        "combo_name": combo_name,
    }
