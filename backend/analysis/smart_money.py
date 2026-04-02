"""
Smart Money Concepts (SMC) — 轻量纯Python实现
实现 ICT 核心概念: BOS/CHoCH, Order Blocks, Fair Value Gaps
无外部依赖，直接使用 OHLCV 列表数据

Based on ICT (Inner Circle Trader) methodology.
"""
from typing import List, Dict, Tuple, Optional
from loguru import logger


def find_swing_points(highs: List[float], lows: List[float], swing_length: int = 5) -> List[Dict]:
    """
    查找摆动高低点 (Swing Highs & Lows)
    swing_length: 左右各看多少根K线
    Returns: [{index, type: 'high'|'low', level}]
    """
    swings = []
    n = len(highs)
    
    for i in range(swing_length, n - swing_length):
        # Swing High: 当前 high 是前后 swing_length 根K线中最高的
        is_swing_high = all(highs[i] >= highs[j] for j in range(i - swing_length, i + swing_length + 1) if j != i)
        if is_swing_high:
            swings.append({"index": i, "type": "high", "level": highs[i]})
        
        # Swing Low: 当前 low 是前后 swing_length 根K线中最低的
        is_swing_low = all(lows[i] <= lows[j] for j in range(i - swing_length, i + swing_length + 1) if j != i)
        if is_swing_low:
            swings.append({"index": i, "type": "low", "level": lows[i]})
    
    return sorted(swings, key=lambda x: x["index"])


def detect_bos_choch(closes: List[float], highs: List[float], lows: List[float], 
                      swing_length: int = 5) -> Dict:
    """
    检测 Break of Structure (BOS) 和 Change of Character (CHoCH)
    
    BOS = 趋势延续性突破 (高点被突破→多头BOS, 低点被突破→空头BOS)
    CHoCH = 性格转变 (下降趋势中突破前高→看多CHoCH, 上升趋势中突破前低→看空CHoCH)
    
    Returns: {
        "last_bos": {"type": "bullish"|"bearish", "level": float, "index": int} | None,
        "last_choch": {"type": "bullish"|"bearish", "level": float, "index": int} | None,
        "market_structure": "bullish"|"bearish"|"neutral",
        "structures": [...] # all detected structures
    }
    """
    swings = find_swing_points(highs, lows, swing_length)
    
    if len(swings) < 3:
        return {"last_bos": None, "last_choch": None, "market_structure": "neutral", "structures": []}
    
    structures = []
    # Track the last swing high and swing low
    last_swing_high = None
    last_swing_low = None
    trend = "neutral"  # Current trend based on structure
    
    for swing in swings:
        if swing["type"] == "high":
            if last_swing_high is not None:
                # Check if current price broke above the last swing high
                for j in range(swing["index"], min(swing["index"] + swing_length * 2, len(closes))):
                    if j < len(closes) and closes[j] > last_swing_high["level"]:
                        if trend == "bearish":
                            # Breaking high in downtrend = CHoCH (bullish)
                            structures.append({
                                "type": "choch", "direction": "bullish",
                                "level": last_swing_high["level"], "index": j
                            })
                            trend = "bullish"
                        else:
                            # Breaking high in uptrend = BOS (bullish)
                            structures.append({
                                "type": "bos", "direction": "bullish",
                                "level": last_swing_high["level"], "index": j
                            })
                            trend = "bullish"
                        break
            last_swing_high = swing
            
        elif swing["type"] == "low":
            if last_swing_low is not None:
                # Check if current price broke below the last swing low
                for j in range(swing["index"], min(swing["index"] + swing_length * 2, len(closes))):
                    if j < len(closes) and closes[j] < last_swing_low["level"]:
                        if trend == "bullish":
                            # Breaking low in uptrend = CHoCH (bearish)
                            structures.append({
                                "type": "choch", "direction": "bearish",
                                "level": last_swing_low["level"], "index": j
                            })
                            trend = "bearish"
                        else:
                            # Breaking low in downtrend = BOS (bearish)
                            structures.append({
                                "type": "bos", "direction": "bearish",
                                "level": last_swing_low["level"], "index": j
                            })
                            trend = "bearish"
                        break
            last_swing_low = swing
    
    # Get the most recent signals
    last_bos = None
    last_choch = None
    for s in reversed(structures):
        if s["type"] == "bos" and last_bos is None:
            last_bos = s
        if s["type"] == "choch" and last_choch is None:
            last_choch = s
        if last_bos and last_choch:
            break
    
    return {
        "last_bos": last_bos,
        "last_choch": last_choch,
        "market_structure": trend,
        "structures": structures[-5:],  # Keep last 5 for context
    }


def detect_order_blocks(opens: List[float], closes: List[float], highs: List[float], 
                         lows: List[float], volumes: List[float], lookback: int = 20) -> List[Dict]:
    """
    检测 Order Blocks (订单块)
    
    牛市OB: 下跌→上涨突破的最后一根阴线 (机构买入区)
    熊市OB: 上涨→下跌突破的最后一根阳线 (机构卖出区)
    
    Returns: [{"type": "bullish"|"bearish", "top": float, "bottom": float, "index": int, "strength": float}]
    """
    obs = []
    n = len(opens)
    
    for i in range(2, min(lookback, n - 1)):
        idx = n - 1 - i  # Work backwards from current
        if idx < 1:
            break
        
        # Bullish OB: bearish candle followed by strong bullish candle that closes above its high
        if closes[idx] < opens[idx]:  # Current candle is bearish
            if idx + 1 < n and closes[idx + 1] > opens[idx + 1]:  # Next candle is bullish
                if closes[idx + 1] > highs[idx]:  # Bullish candle closes above bearish candle's high
                    # Check if volume is above average (strong move)
                    avg_vol = sum(volumes[max(0, idx-10):idx]) / max(1, min(10, idx))
                    strength = volumes[idx + 1] / avg_vol if avg_vol > 0 else 1
                    
                    obs.append({
                        "type": "bullish",
                        "top": highs[idx],
                        "bottom": lows[idx],
                        "index": idx,
                        "strength": round(strength, 2),
                        "mitigated": any(lows[j] <= lows[idx] for j in range(idx + 2, n)),
                    })
        
        # Bearish OB: bullish candle followed by strong bearish candle that closes below its low
        if closes[idx] > opens[idx]:  # Current candle is bullish
            if idx + 1 < n and closes[idx + 1] < opens[idx + 1]:  # Next candle is bearish
                if closes[idx + 1] < lows[idx]:  # Bearish candle closes below bullish candle's low
                    avg_vol = sum(volumes[max(0, idx-10):idx]) / max(1, min(10, idx))
                    strength = volumes[idx + 1] / avg_vol if avg_vol > 0 else 1
                    
                    obs.append({
                        "type": "bearish",
                        "top": highs[idx],
                        "bottom": lows[idx],
                        "index": idx,
                        "strength": round(strength, 2),
                        "mitigated": any(highs[j] >= highs[idx] for j in range(idx + 2, n)),
                    })
    
    # Only return un-mitigated OBs (still valid)
    active_obs = [ob for ob in obs if not ob["mitigated"]]
    return active_obs[:5]  # Top 5 most recent


def detect_fvg(opens: List[float], closes: List[float], highs: List[float], 
               lows: List[float], lookback: int = 20) -> List[Dict]:
    """
    检测 Fair Value Gaps (公允价值缺口)
    
    牛市FVG: 前一根K线的High < 后一根K线的Low (中间有价格真空)
    熊市FVG: 前一根K线的Low > 后一根K线的High (中间有价格真空)
    
    Returns: [{"type": "bullish"|"bearish", "top": float, "bottom": float, "index": int, "filled": bool}]
    """
    fvgs = []
    n = len(opens)
    
    for i in range(2, min(lookback, n)):
        idx = n - 1 - i
        if idx < 1 or idx + 1 >= n:
            continue
        
        # Bullish FVG: gap between candle[idx-1].high and candle[idx+1].low
        if idx - 1 >= 0:
            prev_high = highs[idx - 1]
            next_low = lows[idx + 1]
            
            if next_low > prev_high:  # Bullish FVG exists
                # Check if it's been filled
                filled = any(lows[j] <= prev_high for j in range(idx + 2, n))
                fvgs.append({
                    "type": "bullish",
                    "top": next_low,
                    "bottom": prev_high,
                    "mid": round((next_low + prev_high) / 2, 2),
                    "index": idx,
                    "filled": filled,
                })
            
            # Bearish FVG
            prev_low = lows[idx - 1]
            next_high = highs[idx + 1]
            
            if prev_low > next_high:  # Bearish FVG exists
                filled = any(highs[j] >= prev_low for j in range(idx + 2, n))
                fvgs.append({
                    "type": "bearish",
                    "top": prev_low,
                    "bottom": next_high,
                    "mid": round((prev_low + next_high) / 2, 2),
                    "index": idx,
                    "filled": filled,
                })
    
    # Only return unfilled FVGs (still valid targets)
    active_fvgs = [f for f in fvgs if not f["filled"]]
    return active_fvgs[:5]


def analyze_smc(opens: List[float], closes: List[float], highs: List[float], 
                lows: List[float], volumes: List[float], current_price: float) -> Dict:
    """
    综合 SMC 分析 — 返回市场结构、订单块、FVG 和交易评分
    
    Returns: {
        "score_adjustment": int (-10 to +10),
        "market_structure": str,
        "signals": [str],
        "order_blocks": [...],
        "fvgs": [...],
        "bos_choch": {...},
        "nearest_ob": {...} | None,
        "nearest_fvg": {...} | None,
    }
    """
    signals = []
    score_adj = 0
    
    # 1. Market Structure (BOS/CHoCH)
    structure = detect_bos_choch(closes, highs, lows, swing_length=5)
    
    if structure["last_choch"]:
        choch = structure["last_choch"]
        recency = len(closes) - 1 - choch["index"]
        if recency <= 10:  # Recent CHoCH within last 10 candles
            if choch["direction"] == "bullish":
                score_adj += 5
                signals.append(f"🔄 CHoCH多头转势(第{recency}根)")
            else:
                score_adj -= 5
                signals.append(f"🔄 CHoCH空头转势(第{recency}根)")
    
    if structure["last_bos"]:
        bos = structure["last_bos"]
        recency = len(closes) - 1 - bos["index"]
        if recency <= 10:
            if bos["direction"] == "bullish":
                score_adj += 3
                signals.append(f"📈 BOS多头突破(第{recency}根)")
            else:
                score_adj -= 3
                signals.append(f"📉 BOS空头突破(第{recency}根)")
    
    # 2. Order Blocks
    obs = detect_order_blocks(opens, closes, highs, lows, volumes)
    nearest_ob = None
    
    for ob in obs:
        distance_pct = abs(current_price - (ob["top"] + ob["bottom"]) / 2) / current_price * 100
        if distance_pct < 0.5:  # Price is within 0.5% of an OB
            if ob["type"] == "bullish" and current_price >= ob["bottom"]:
                score_adj += 3
                signals.append(f"🟢 价格在多头OB区域(${ob['bottom']:.0f}-${ob['top']:.0f})")
                nearest_ob = ob
            elif ob["type"] == "bearish" and current_price <= ob["top"]:
                score_adj -= 3
                signals.append(f"🔴 价格在空头OB区域(${ob['bottom']:.0f}-${ob['top']:.0f})")
                nearest_ob = ob
        elif nearest_ob is None:
            nearest_ob = ob
    
    # 3. Fair Value Gaps
    fvgs = detect_fvg(opens, closes, highs, lows)
    nearest_fvg = None
    
    for fvg in fvgs:
        distance_pct = abs(current_price - fvg["mid"]) / current_price * 100
        if distance_pct < 0.3:  # Price near FVG
            if fvg["type"] == "bullish":
                score_adj += 2
                signals.append(f"⬜ 多头FVG待回补(${fvg['bottom']:.0f}-${fvg['top']:.0f})")
            else:
                score_adj -= 2
                signals.append(f"⬜ 空头FVG待回补(${fvg['bottom']:.0f}-${fvg['top']:.0f})")
            nearest_fvg = fvg
        elif nearest_fvg is None:
            nearest_fvg = fvg
    
    # Cap adjustment
    score_adj = max(-10, min(10, score_adj))
    
    if not signals:
        signals.append(f"市场结构: {structure['market_structure']}")
    
    return {
        "score_adjustment": score_adj,
        "market_structure": structure["market_structure"],
        "signals": signals,
        "order_blocks": obs[:3],
        "fvgs": fvgs[:3],
        "bos_choch": structure,
        "nearest_ob": nearest_ob,
        "nearest_fvg": nearest_fvg,
    }
