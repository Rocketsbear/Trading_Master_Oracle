"""
Volume Profile (VPVR) — 多交易所K线聚合成交量分布
统计每个价格区间的累积成交量，找到关键支撑/阻力

核心概念：
- POC (Point of Control): 成交量最集中的价格 → 强支撑/阻力
- VAH (Value Area High): 成交量分布的上边界 (70% 分布)
- VAL (Value Area Low): 成交量分布的下边界 (70% 分布)
- 高成交量节点 = 价格容易停留
- 低成交量节点 = 价格快速穿过
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from loguru import logger


def compute_volume_profile(
    klines_list: List[List[Dict]],
    num_bins: int = 50,
) -> Optional[Dict]:
    """
    从多交易所K线数据计算 Volume Profile
    
    klines_list: [exchange1_klines, exchange2_klines, ...]
      每个 klines: [{time, open, high, low, close, volume}, ...]
    num_bins: 价格区间数量 (越多越精细)
    
    返回: {
        "poc": float,              # Point of Control 价格
        "vah": float,              # Value Area High
        "val": float,              # Value Area Low
        "profile": [{price, volume, pct}],  # 完整分布
        "high_volume_nodes": [],   # 高成交量节点
        "low_volume_nodes": [],    # 低成交量节点 (快速穿越区)
    }
    """
    # Merge all klines from all exchanges
    all_volume_data = []  # [(price, volume), ...]
    
    for klines in klines_list:
        if not klines:
            continue
        for k in klines:
            # 将每根K线的成交量分配到该K线的价格范围内
            high = k.get("high", 0)
            low = k.get("low", 0)
            volume = k.get("volume", 0)
            
            if high <= 0 or low <= 0 or volume <= 0:
                continue
            
            # 典型价格 = (H + L + C) / 3
            typical_price = (high + low + k.get("close", high)) / 3
            all_volume_data.append((typical_price, volume, high, low))
    
    if not all_volume_data:
        return None
    
    # 确定价格范围
    all_highs = [d[2] for d in all_volume_data]
    all_lows = [d[3] for d in all_volume_data]
    price_min = min(all_lows)
    price_max = max(all_highs)
    
    if price_max <= price_min:
        return None
    
    # 创建价格区间 (bins)
    bin_size = (price_max - price_min) / num_bins
    bins = []
    for i in range(num_bins):
        bin_low = price_min + i * bin_size
        bin_high = bin_low + bin_size
        bin_mid = (bin_low + bin_high) / 2
        bins.append({
            "price": round(bin_mid, 2),
            "low": round(bin_low, 2),
            "high": round(bin_high, 2),
            "volume": 0.0,
        })
    
    # 将每根K线的成交量分配到对应区间
    for typical, volume, high, low in all_volume_data:
        # 找到价格在哪个bin内
        # 简易分配：将成交量分配到典型价格所在的bin
        bin_idx = int((typical - price_min) / bin_size)
        bin_idx = max(0, min(num_bins - 1, bin_idx))
        bins[bin_idx]["volume"] += volume
        
        # 如果K线跨度大，也按比例分配到邻近bin (更精确的VPVR)
        candle_range = high - low
        if candle_range > bin_size * 2:
            # 大阳/大阴线，按比例分配
            for j in range(num_bins):
                if bins[j]["low"] <= high and bins[j]["high"] >= low:
                    overlap = min(bins[j]["high"], high) - max(bins[j]["low"], low)
                    if overlap > 0 and candle_range > 0:
                        pct = overlap / candle_range
                        bins[j]["volume"] += volume * pct * 0.3  # 30% 额外分配
    
    # 计算总成交量
    total_volume = sum(b["volume"] for b in bins)
    if total_volume <= 0:
        return None
    
    # 计算百分比
    for b in bins:
        b["pct"] = round(b["volume"] / total_volume * 100, 2)
    
    # === POC === 成交量最高的价格区间
    poc_bin = max(bins, key=lambda b: b["volume"])
    poc = poc_bin["price"]
    
    # === Value Area (70% of total volume) ===
    sorted_bins = sorted(bins, key=lambda b: b["volume"], reverse=True)
    va_volume = 0
    va_prices = []
    for b in sorted_bins:
        va_volume += b["volume"]
        va_prices.append(b["price"])
        if va_volume >= total_volume * 0.7:
            break
    
    vah = max(va_prices) if va_prices else price_max
    val = min(va_prices) if va_prices else price_min
    
    # === High Volume Nodes (HVN) ===
    avg_vol = total_volume / num_bins
    hvn = [
        {"price": b["price"], "volume": round(b["volume"], 2), "pct": b["pct"]}
        for b in bins if b["volume"] > avg_vol * 1.5
    ]
    hvn.sort(key=lambda x: x["volume"], reverse=True)
    
    # === Low Volume Nodes (LVN) ===
    lvn = [
        {"price": b["price"], "volume": round(b["volume"], 2), "pct": b["pct"]}
        for b in bins if 0 < b["volume"] < avg_vol * 0.5
    ]
    
    # Simplified profile (top 20 bins for response size)
    profile = sorted(bins, key=lambda b: b["volume"], reverse=True)[:20]
    for p in profile:
        p["volume"] = round(p["volume"], 2)
    profile.sort(key=lambda p: p["price"])
    
    return {
        "poc": round(poc, 2),
        "vah": round(vah, 2),
        "val": round(val, 2),
        "price_range": {"min": round(price_min, 2), "max": round(price_max, 2)},
        "bin_size": round(bin_size, 2),
        "total_volume": round(total_volume, 2),
        "exchanges_used": len([k for k in klines_list if k]),
        "candles_analyzed": sum(len(k) for k in klines_list if k),
        "profile": profile,
        "high_volume_nodes": hvn[:5],  # Top 5
        "low_volume_nodes": lvn[:5],
    }


def score_volume_profile(vp: Dict, current_price: float) -> Dict:
    """
    基于 Volume Profile 给出评分调整
    
    规则:
    - 价格在 POC 附近 → 强支撑/阻力区, 可能反弹 (±3)
    - 价格在 VAL 以下 → 低于价值区, 可能回升 (+3)
    - 价格在 VAH 以上 → 高于价值区, 可能回落 (-3)
    - 价格在 LVN 区域 → 快速穿越, 趋势可能加速 (±2)
    """
    if not vp:
        return {"adjustment": 0, "reasons": ["VPVR数据不足"]}
    
    poc = vp["poc"]
    vah = vp["vah"]
    val = vp["val"]
    
    adjustment = 0
    reasons = []
    
    # 价格相对 POC 位置
    dist_to_poc_pct = abs(current_price - poc) / current_price * 100
    
    if dist_to_poc_pct < 0.3:
        # 在 POC 附近 — 强支撑/阻力
        if current_price >= poc:
            reasons.append(f"价格在POC(${poc:,.0f})附近↑,量密支撑")
        else:
            reasons.append(f"价格在POC(${poc:,.0f})附近↓,量密压力")
    
    # 价格相对 Value Area 位置
    if current_price < val:
        adjustment += 3
        reasons.append(f"价格${current_price:,.0f}<VAL(${val:,.0f}),低于价值区回升+3")
    elif current_price > vah:
        adjustment -= 3
        reasons.append(f"价格${current_price:,.0f}>VAH(${vah:,.0f}),高于价值区回落-3")
    elif val <= current_price <= vah:
        reasons.append(f"价格在价值区内(${val:,.0f}-${vah:,.0f})")
    
    # 检查是否在 LVN (低成交量节点) → 趋势加速区
    lvn_nodes = vp.get("low_volume_nodes", [])
    for node in lvn_nodes:
        if abs(current_price - node["price"]) / current_price < 0.003:
            adjustment += 2 if current_price > poc else -2
            reasons.append(f"价格在LVN(${node['price']:,.0f}),可能快速穿越{'↑' if current_price > poc else '↓'}")
            break
    
    adjustment = max(-5, min(5, adjustment))
    
    if not reasons:
        reasons.append(f"POC=${poc:,.0f}, VA=[${val:,.0f}-${vah:,.0f}]")
    
    return {
        "adjustment": adjustment,
        "poc": poc,
        "vah": vah,
        "val": val,
        "reasons": reasons,
    }
