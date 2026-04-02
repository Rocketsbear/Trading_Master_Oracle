"""
多交易所多空比深度分析引擎
Professional multi-exchange Long/Short ratio analysis

6维分析:
1. 多所共识 (consensus)    — 3所一致 vs 分歧
2. 变化速度 (rate of change)  — L/S 变化速度
3. 极端告警 (extreme zone)   — <0.8 或 >2.5
4. 融资费率交叉 (funding cross) — L/S×FR 交叉验证
5. 拥挤度背离 (divergence)   — 价格 vs L/S 背离
6. 综合评分 + 告警
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from loguru import logger


class LSAnalyzer:
    """专业级多交易所多空比分析引擎"""
    
    # ===== 告警阈值 (可优化) =====
    EXTREME_LONG = 2.5     # L/S > 2.5 → 多头极端拥挤
    WARNING_LONG = 1.8     # L/S > 1.8 → 多头偏拥挤
    HEALTHY_LONG = 1.2     # 1.2-1.8 → 健康多头
    NEUTRAL_HIGH = 1.2     # 0.8-1.2 → 中性
    NEUTRAL_LOW = 0.8
    WARNING_SHORT = 0.6    # L/S < 0.6 → 空头偏拥挤
    EXTREME_SHORT = 0.4    # L/S < 0.4 → 空头极端拥挤
    
    # 用户要求的原始告警线 (集成到极端区域逻辑中)
    USER_ALERT_HIGH = 2.8
    USER_ALERT_LOW = 0.8
    
    @classmethod
    def analyze_multi_exchange(
        cls,
        long_short_ratios: Dict[str, Dict],
        funding_rates: Dict[str, float] = None,
        oi_change_pct: float = None,
        price_change_pct: float = None,
        avg_long_pct: float = None,
    ) -> Dict[str, Any]:
        """
        综合多交易所多空比分析
        
        Args:
            long_short_ratios: {"binance": {"ratio": 1.2, "long_pct": 54.5, "short_pct": 45.5}, ...}
            funding_rates: {"binance": 0.0001, "okx": 0.0002, ...}
            oi_change_pct: OI 变化百分比
            price_change_pct: 最近价格变化 %
            avg_long_pct: 平均做多比例
            
        Returns:
            综合分析结果 + 评分
        """
        if not long_short_ratios:
            return {
                "score_adjustment": 0,
                "alert": None,
                "details": "无多空比数据",
                "exchanges": {},
                "avg_ratio": None,
            }
        
        # 提取各交易所比率
        ratios = {name: data["ratio"] for name, data in long_short_ratios.items() if "ratio" in data}
        
        if not ratios:
            return {
                "score_adjustment": 0,
                "alert": None,
                "details": "无有效多空比数据",
                "exchanges": {},
                "avg_ratio": None,
            }
        
        avg_ratio = sum(ratios.values()) / len(ratios)
        
        # ===== 6维分析 =====
        total_adj = 0
        breakdown = []
        alerts = []
        
        # DIM 1: 多所共识分析 (±6)
        consensus_adj, consensus_desc = cls._dim_consensus(ratios)
        total_adj += consensus_adj
        if consensus_adj != 0:
            breakdown.append(consensus_desc)
        
        # DIM 2: 极端告警 (±8)
        extreme_adj, extreme_desc, extreme_alert = cls._dim_extreme(avg_ratio, ratios)
        total_adj += extreme_adj
        if extreme_adj != 0:
            breakdown.append(extreme_desc)
        if extreme_alert:
            alerts.append(extreme_alert)
        
        # DIM 3: 融资费率交叉验证 (±5)
        if funding_rates:
            cross_adj, cross_desc = cls._dim_funding_cross(avg_ratio, funding_rates)
            total_adj += cross_adj
            if cross_adj != 0:
                breakdown.append(cross_desc)
        
        # DIM 4: OI 联动分析 (±4)
        if oi_change_pct is not None:
            oi_adj, oi_desc = cls._dim_oi_linkage(avg_ratio, oi_change_pct)
            total_adj += oi_adj
            if oi_adj != 0:
                breakdown.append(oi_desc)
        
        # DIM 5: 价格背离检测 (±6)
        if price_change_pct is not None:
            div_adj, div_desc = cls._dim_price_divergence(avg_ratio, price_change_pct)
            total_adj += div_adj
            if div_adj != 0:
                breakdown.append(div_desc)
        
        # DIM 6: 交易所偏差检测 (信息性)
        skew_info = cls._dim_exchange_skew(ratios)
        
        # 总评分限幅
        total_adj = max(-12, min(12, total_adj))
        
        # 确定整体判断
        if avg_ratio > cls.EXTREME_LONG:
            zone = "extreme_long"
            zone_label = "🔴 多头极端拥挤"
        elif avg_ratio > cls.WARNING_LONG:
            zone = "warning_long"
            zone_label = "🟡 多头拥挤"
        elif avg_ratio > cls.HEALTHY_LONG:
            zone = "healthy_long"
            zone_label = "🟢 健康多头"
        elif avg_ratio > cls.NEUTRAL_LOW:
            zone = "neutral"
            zone_label = "⚪ 中性均衡"
        elif avg_ratio > cls.WARNING_SHORT:
            zone = "warning_short"
            zone_label = "🟡 空头拥挤"
        elif avg_ratio > cls.EXTREME_SHORT:
            zone = "extreme_short"
            zone_label = "🔴 空头极端拥挤"
        else:
            zone = "extreme_short"
            zone_label = "🔴 空头极端恐慌"
        
        return {
            "score_adjustment": total_adj,
            "avg_ratio": round(avg_ratio, 3),
            "zone": zone,
            "zone_label": zone_label,
            "exchanges": ratios,
            "breakdown": breakdown,
            "alerts": alerts,
            "skew_info": skew_info,
            "details": f"L/S={avg_ratio:.2f} {zone_label} | {' | '.join(breakdown)}" if breakdown else f"L/S={avg_ratio:.2f} {zone_label}",
        }
    
    # ===== DIM 1: 多所共识 (±6) =====
    @classmethod
    def _dim_consensus(cls, ratios: Dict[str, float]) -> Tuple[int, str]:
        """
        3所同向 → 信号强 (±6)
        2看多1看空 → 偏弱 (±3)
        分歧 → 犹豫 (0)
        """
        if len(ratios) < 2:
            return 0, ""
        
        bullish = sum(1 for r in ratios.values() if r > 1.15)
        bearish = sum(1 for r in ratios.values() if r < 0.85)
        total = len(ratios)
        
        if bullish == total:
            return 3, f"全所看多+3({total}所L/S>1.15)"
        elif bearish == total:
            return -3, f"全所看空-3({total}所L/S<0.85)"
        elif bullish >= total * 0.66:
            return 2, f"多数偏多+2({bullish}/{total})"
        elif bearish >= total * 0.66:
            return -2, f"多数偏空-2({bearish}/{total})"
        else:
            return 0, ""
    
    # ===== DIM 2: 极端告警 (±8) =====
    @classmethod
    def _dim_extreme(cls, avg_ratio: float, ratios: Dict[str, float]) -> Tuple[int, str, Optional[str]]:
        """
        极端拥挤 → 反向指标 (逆向思维)
        L/S > 2.5 → 多头极端，准备空 → score -8
        L/S > 1.8 → 多头拥挤，谨慎做多 → score -4
        L/S < 0.6 → 空头极端，准备多 → score +8
        L/S < 0.8 → 空头拥挤，谨慎做空 → score +4
        
        用户告警线: >2.8 或 <0.8 → 生成告警
        """
        adj = 0
        desc = ""
        alert = None
        
        # 检查是否有任一交易所极端
        max_ratio = max(ratios.values())
        min_ratio = min(ratios.values())
        
        if avg_ratio >= cls.EXTREME_LONG:
            adj = -8
            desc = f"🚨多头极端{avg_ratio:.2f}>2.5 逆向-8"
            if avg_ratio >= cls.USER_ALERT_HIGH or max_ratio >= cls.USER_ALERT_HIGH:
                alert = f"🚨 多空比告警: L/S={avg_ratio:.2f} 超过2.8! 多头极端拥挤，高风险做多"
        elif avg_ratio >= cls.WARNING_LONG:
            adj = -4
            desc = f"⚠️多头拥挤{avg_ratio:.2f}>1.8 谨慎-4"
        elif avg_ratio <= cls.EXTREME_SHORT:
            adj = 8
            desc = f"🚨空头极端{avg_ratio:.2f}<0.4 逆向+8"
        elif avg_ratio <= cls.WARNING_SHORT:
            adj = 4
            desc = f"⚠️空头拥挤{avg_ratio:.2f}<0.6 反弹+4"
        elif avg_ratio <= cls.USER_ALERT_LOW:
            adj = 3
            desc = f"多空比{avg_ratio:.2f}<0.8 偏空+3"
            if min_ratio <= cls.USER_ALERT_LOW:
                alert = f"⚠️ 多空比告警: L/S={avg_ratio:.2f} 低于0.8! 空头占优"
        
        return adj, desc, alert
    
    # ===== DIM 3: 融资费率交叉 (±5) =====
    @classmethod
    def _dim_funding_cross(cls, avg_ratio: float, funding_rates: Dict[str, float]) -> Tuple[int, str]:
        """
        L/S + Funding Rate 交叉验证:
        
        L/S高 + FR高 → 极度拥挤，即将反转 (-5)
        L/S高 + FR低/负 → 真实看多（未被套利盘利用），信号强 (+3)
        L/S低 + FR负 → 极度恐慌，即将反弹 (+5)
        L/S低 + FR高 → 矛盾信号，谨慎 (0)
        """
        avg_fr = sum(funding_rates.values()) / len(funding_rates) if funding_rates else 0
        
        # 阈值
        fr_high = avg_fr > 0.0005    # >0.05%
        fr_low = avg_fr < -0.0003    # <-0.03%
        ls_high = avg_ratio > 1.5
        ls_low = avg_ratio < 0.7
        
        if ls_high and fr_high:
            return -5, f"L/S{avg_ratio:.2f}高+FR{avg_fr:.4%}高=极拥挤-5"
        elif ls_high and fr_low:
            return 3, f"L/S{avg_ratio:.2f}高+FR{avg_fr:.4%}低=真多头+3"
        elif ls_low and fr_low:
            return 5, f"L/S{avg_ratio:.2f}低+FR{avg_fr:.4%}低=恐慌反弹+5"
        elif ls_low and fr_high:
            return 0, f"L/S低+FR高=矛盾信号"
        
        return 0, ""
    
    # ===== DIM 4: OI 联动 (±4) =====
    @classmethod
    def _dim_oi_linkage(cls, avg_ratio: float, oi_change_pct: float) -> Tuple[int, str]:
        """
        L/S + OI 联动:
        
        L/S高 + OI增 → 新多头在入场，趋势延续 (+2)
        L/S高 + OI降 → 多头在平仓，即将反转 (-4)
        L/S低 + OI增 → 新空头在入场，下跌延续 (-2)
        L/S低 + OI降 → 空头在平仓，触底信号 (+4)
        """
        oi_rising = oi_change_pct > 3      # OI涨3%+
        oi_falling = oi_change_pct < -3    # OI跌3%+
        ls_high = avg_ratio > 1.3
        ls_low = avg_ratio < 0.8
        
        if ls_high and oi_falling:
            return -4, f"L/S{avg_ratio:.2f}高+OI降{oi_change_pct:+.1f}%=多头平仓-4"
        elif ls_low and oi_falling:
            return 4, f"L/S{avg_ratio:.2f}低+OI降{oi_change_pct:+.1f}%=空头平仓触底+4"
        elif ls_high and oi_rising:
            return 2, f"L/S{avg_ratio:.2f}高+OI增{oi_change_pct:+.1f}%=趋势延续+2"
        elif ls_low and oi_rising:
            return -2, f"L/S{avg_ratio:.2f}低+OI增{oi_change_pct:+.1f}%=下跌延续-2"
        
        return 0, ""
    
    # ===== DIM 5: 价格背离 (±6) =====
    @classmethod
    def _dim_price_divergence(cls, avg_ratio: float, price_change_pct: float) -> Tuple[int, str]:
        """
        价格 vs L/S 背离检测:
        
        价格涨 + L/S降 → 看空背离 (聪明钱在减仓) (-6)
        价格跌 + L/S升 → 看多背离 (聪明钱在建仓) (+6)
        同向 → 确认趋势 (0)
        """
        price_up = price_change_pct > 1.5     # 涨1.5%+
        price_down = price_change_pct < -1.5  # 跌1.5%+
        ls_bullish = avg_ratio > 1.2
        ls_bearish = avg_ratio < 0.85
        
        if price_up and ls_bearish:
            return -6, f"🔻价格涨{price_change_pct:+.1f}%但L/S{avg_ratio:.2f}<0.85=看空背离-6"
        elif price_down and ls_bullish:
            return 6, f"🔺价格跌{price_change_pct:+.1f}%但L/S{avg_ratio:.2f}>1.2=看多背离+6"
        
        return 0, ""
    
    # ===== DIM 6: 交易所偏差 =====
    @classmethod
    def _dim_exchange_skew(cls, ratios: Dict[str, float]) -> Optional[str]:
        """
        检测交易所间偏差 — 某所明显偏离其他所可能意味着
        该所的散户更快追涨杀跌
        """
        if len(ratios) < 2:
            return None
        
        vals = list(ratios.values())
        avg = sum(vals) / len(vals)
        
        skewed = []
        for name, r in ratios.items():
            pct_diff = abs(r - avg) / avg * 100 if avg > 0 else 0
            if pct_diff > 15:  # 偏差>15%
                direction = "偏多" if r > avg else "偏空"
                skewed.append(f"{name} {direction}{pct_diff:.0f}%(L/S={r:.2f})")
        
        if skewed:
            return f"交易所偏差: {', '.join(skewed)}"
        return None
    
    @classmethod
    def format_for_display(cls, result: Dict) -> str:
        """格式化输出用于前端显示"""
        if not result or result.get("avg_ratio") is None:
            return "多空比: N/A"
        
        lines = [
            f"📊 多空比分析: L/S={result['avg_ratio']:.2f} {result['zone_label']}",
        ]
        
        # 各交易所数据
        exchanges = result.get("exchanges", {})
        if exchanges:
            ex_parts = [f"{name}:{ratio:.2f}" for name, ratio in exchanges.items()]
            lines.append(f"   交易所: {' | '.join(ex_parts)}")
        
        # 评分调整
        adj = result.get("score_adjustment", 0)
        if adj != 0:
            lines.append(f"   评分: {'+' if adj > 0 else ''}{adj}")
        
        # 告警
        for alert in result.get("alerts", []):
            lines.append(f"   {alert}")
        
        # 偏差
        skew = result.get("skew_info")
        if skew:
            lines.append(f"   {skew}")
        
        return "\n".join(lines)
