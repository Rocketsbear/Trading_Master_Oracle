"""
清算区间推算器 — Liquidation Zone Estimator
利用多交易所 OI + 资金费率 + 价格整数关口 推算清算密集区
无需付费 API，纯逻辑推算

核心原理：
1. 高 OI + 高正资金费率 → 大量做多，清算区在下方
2. 高 OI + 负资金费率 → 大量做空，清算区在上方
3. 整数关口 (如 $70,000) 是止损/清算集中点
4. 常见杠杆 (3x/5x/10x/20x/50x) 对应不同清算距离
"""
import asyncio
from typing import Dict, List, Optional
from loguru import logger


# 常见杠杆及其清算距离百分比 (近似)
# 做多清算价 ≈ entry * (1 - 1/leverage)
# 做空清算价 ≈ entry * (1 + 1/leverage)
LEVERAGE_TIERS = [
    {"leverage": 3, "pct": 33.3, "label": "3x"},
    {"leverage": 5, "pct": 20.0, "label": "5x"},
    {"leverage": 10, "pct": 10.0, "label": "10x"},
    {"leverage": 20, "pct": 5.0, "label": "20x"},
    {"leverage": 25, "pct": 4.0, "label": "25x"},
    {"leverage": 50, "pct": 2.0, "label": "50x"},
    {"leverage": 100, "pct": 1.0, "label": "100x"},
]


def _find_round_numbers(price: float, num_levels: int = 5) -> List[float]:
    """找到价格附近的整数关口"""
    if price <= 0:
        return []
    
    # 根据价格量级确定整数关口步长
    if price > 50000:
        step = 1000  # BTC: $69000, $70000, $71000
    elif price > 5000:
        step = 500   # ETH: $3500, $4000, $4500
    elif price > 500:
        step = 50    # BNB: $550, $600, $650
    elif price > 50:
        step = 5     # SOL: $85, $90, $95
    elif price > 5:
        step = 1     # DOT: $6, $7, $8
    else:
        step = 0.1   # XRP: $0.5, $0.6, $0.7
    
    base = int(price / step) * step
    levels = []
    for i in range(-num_levels, num_levels + 1):
        level = round(base + i * step, 2)
        if level > 0:
            levels.append(level)
    return sorted(levels)


async def estimate_liquidation_zones(
    current_price: float,
    exchange_data: Dict,
    symbol: str = "BTCUSDT",
) -> Dict:
    """
    推算清算密集区
    
    输入:
    - current_price: 当前价格
    - exchange_data: get_comprehensive_exchange_data() 的返回值
    - symbol: 交易对
    
    返回:
    - liquidation_zones: 上方/下方清算密集区
    - dominant_side: 做多/做空哪方清算密集
    - score_adjustment: 给评分引擎的调整分 (±5)
    - reasoning: 推理说明
    """
    zones_above = []  # 空头清算区 (价格上涨时触发)
    zones_below = []  # 多头清算区 (价格下跌时触发)
    
    # === 1. 从资金费率推算主导方向 ===
    funding_rates = exchange_data.get("funding_rates", {})
    avg_fr = exchange_data.get("avg_funding_rate", 0)
    
    # 正资金费率 → 做多主导，清算集中在下方
    # 负资金费率 → 做空主导，清算集中在上方
    long_dominant = avg_fr > 0.0001 if avg_fr else False
    short_dominant = avg_fr < -0.0001 if avg_fr else False
    
    # === 2. 从 OI 强度推算清算规模 ===
    oi_data = exchange_data.get("open_interests", {})
    oi_change = exchange_data.get("oi_change_pct", 0)
    oi_trend = exchange_data.get("oi_trend", "stable")
    
    # OI 增加 = 新仓位建立 = 更多潜在清算
    oi_intensity = "high" if oi_trend == "increasing" else "low" if oi_trend == "decreasing" else "medium"
    
    # === 3. 计算各杠杆级别的清算价位 ===
    for tier in LEVERAGE_TIERS:
        lev = tier["leverage"]
        pct = tier["pct"] / 100
        
        # 做多清算价 (价格下跌时触发)
        long_liq = round(current_price * (1 - pct), 2)
        # 做空清算价 (价格上涨时触发)
        short_liq = round(current_price * (1 + pct), 2)
        
        # 估算该杠杆的清算密度 (基于资金费率方向)
        if long_dominant:
            long_density = "high" if lev >= 10 else "medium"
            short_density = "low"
        elif short_dominant:
            long_density = "low"
            short_density = "high" if lev >= 10 else "medium"
        else:
            long_density = "medium" if lev >= 20 else "low"
            short_density = "medium" if lev >= 20 else "low"
        
        zones_below.append({
            "price": long_liq,
            "leverage": tier["label"],
            "type": "long_liquidation",
            "density": long_density,
            "distance_pct": round(pct * 100, 1),
        })
        
        zones_above.append({
            "price": short_liq,
            "leverage": tier["label"],
            "type": "short_liquidation",
            "density": short_density,
            "distance_pct": round(pct * 100, 1),
        })
    
    # === 4. 整数关口叠加(增强密度) ===
    round_levels = _find_round_numbers(current_price)
    round_below = [l for l in round_levels if l < current_price]
    round_above = [l for l in round_levels if l > current_price]
    
    # 标记靠近整数关口的清算区为"增强密度"
    for zone in zones_below:
        for rl in round_below:
            if abs(zone["price"] - rl) / current_price < 0.005:  # 0.5%以内
                zone["density"] = "very_high"
                zone["round_number"] = rl
                break
    
    for zone in zones_above:
        for rl in round_above:
            if abs(zone["price"] - rl) / current_price < 0.005:
                zone["density"] = "very_high"
                zone["round_number"] = rl
                break
    
    # === 5. 计算评分调整 ===
    score_adj = 0
    reasons = []
    
    # 高密度清算区在下方 = 磁铁效应下拉 → 空头信号
    high_below = sum(1 for z in zones_below if z["density"] in ("high", "very_high"))
    high_above = sum(1 for z in zones_above if z["density"] in ("high", "very_high"))
    
    if long_dominant and oi_intensity != "low":
        # 做多拥挤 + OI 高 → 下方清算多，价格可能被吸引下跌
        score_adj -= 3
        reasons.append(f"做多拥挤(FR={avg_fr:.4%}), 下方清算密集")
    elif short_dominant and oi_intensity != "low":
        # 做空拥挤 → 上方清算多，价格可能被逼空上涨
        score_adj += 3
        reasons.append(f"做空拥挤(FR={avg_fr:.4%}), 上方清算密集")
    
    # 价格接近高密度整数关口
    nearest_round_below = max(round_below) if round_below else 0
    nearest_round_above = min(round_above) if round_above else current_price * 2
    
    dist_to_round_below = (current_price - nearest_round_below) / current_price * 100
    dist_to_round_above = (nearest_round_above - current_price) / current_price * 100
    
    if dist_to_round_below < 1.0 and long_dominant:
        score_adj -= 2
        reasons.append(f"距下方整数关口${nearest_round_below:,.0f}仅{dist_to_round_below:.1f}%")
    elif dist_to_round_above < 1.0 and short_dominant:
        score_adj += 2
        reasons.append(f"距上方整数关口${nearest_round_above:,.0f}仅{dist_to_round_above:.1f}%")
    
    score_adj = max(-5, min(5, score_adj))
    
    # === 6. 确定主导方 ===
    if long_dominant:
        dominant = "long_heavy"
        dominant_label = "做多清算密集"
    elif short_dominant:
        dominant = "short_heavy"
        dominant_label = "做空清算密集"
    else:
        dominant = "balanced"
        dominant_label = "多空均衡"
    
    # 保留最相关的清算区 (高密度 + 距离近)
    key_zones_below = [z for z in zones_below if z["density"] in ("high", "very_high")][:3]
    key_zones_above = [z for z in zones_above if z["density"] in ("high", "very_high")][:3]
    
    # 多交易所资金费率明细
    fr_details = {ex: round(fr * 100, 4) for ex, fr in funding_rates.items()}
    
    # OI 明细
    oi_details = {}
    for ex, oi_val in oi_data.items():
        oi_details[ex] = round(oi_val, 2)
    
    return {
        "score_adjustment": score_adj,
        "dominant_side": dominant,
        "dominant_label": dominant_label,
        "reasons": reasons if reasons else ["清算分布均匀，无明显方向偏移"],
        "key_zones_below": key_zones_below,
        "key_zones_above": key_zones_above,
        "round_numbers": round_levels,
        "nearest_support": nearest_round_below,
        "nearest_resistance": nearest_round_above,
        "funding_rates": fr_details,
        "oi": oi_details,
        "oi_intensity": oi_intensity,
        "avg_funding_rate_pct": round(avg_fr * 100, 4) if avg_fr else 0,
    }
