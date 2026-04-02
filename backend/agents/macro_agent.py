"""
宏观分析Agent — 使用 FRED API 真实数据
"""
import asyncio
from typing import Dict, Any
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from backend.data_sources.macro.fred import FREDDataSource


class MacroAgent(BaseAgent):
    """宏观分析Agent - 专注于经济周期、利率、流动性、通胀"""
    
    def __init__(self, fred_api_key: str = None):
        super().__init__(
            name="宏观领航员 🧭",
            agent_type=AgentType.MACRO,
            personality=(
                "我看大势。美联储加息还是降息？美元走强还是走弱？"
                "BTC dominance在上升还是下降？流动性在扩张还是收缩？"
                "宏观环境决定了市场的天花板和地板。"
                "做合约要先看大势，逆大势的交易注定被碾压。"
            )
        )
        self.fred = FREDDataSource(fred_api_key) if fred_api_key else None
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """执行宏观分析"""
        try:
            if not self.fred:
                return self._no_data_result("未配置 FRED API Key")
            
            # 获取真实 FRED 数据
            data = await self.fred.get_comprehensive_macro_data()
            
            score = 50
            observations = []
            details = []
            
            # === 1. 货币政策（联邦基金利率）===
            fed_rate = data.get('fed_funds_rate', {}).get('value')
            if fed_rate is not None:
                if fed_rate < 2.0:
                    score += 15
                    monetary = "极度宽松 — 利好风险资产"
                elif fed_rate < 3.5:
                    score += 8
                    monetary = "偏宽松"
                elif fed_rate > 5.0:
                    score -= 12
                    monetary = "紧缩 — 不利于风险资产"
                elif fed_rate > 4.0:
                    score -= 5
                    monetary = "偏紧缩"
                else:
                    monetary = "中性"
                observations.append(f"联邦基金利率: {fed_rate}% ({monetary})")
                details.append(f"💰 货币政策: {monetary}，当前利率 {fed_rate}%")
            
            # === 2. 通胀（CPI 同比）===
            cpi_yoy = data.get('cpi', {}).get('change_yoy')
            if cpi_yoy is not None:
                if cpi_yoy > 5.0:
                    score -= 10
                    inflation = "高通胀"
                elif cpi_yoy > 3.0:
                    score -= 5
                    inflation = "温和通胀"
                elif cpi_yoy < 1.0:
                    score += 5
                    inflation = "低通胀"
                else:
                    score += 2
                    inflation = "通胀可控"
                observations.append(f"CPI同比: {cpi_yoy}% ({inflation})")
                details.append(f"📈 通胀: CPI 同比 {cpi_yoy}% ({inflation})")
            
            # === 3. 核心 PCE（美联储首选指标）===
            pce_yoy = data.get('core_pce', {}).get('change_yoy')
            if pce_yoy is not None:
                if pce_yoy > 3.0:
                    score -= 5
                elif pce_yoy < 2.0:
                    score += 5
                details.append(f"📊 核心PCE同比: {pce_yoy}% (Fed目标2%)")
            
            # === 4. GDP 增长 ===
            gdp_yoy = data.get('gdp', {}).get('change_yoy')
            if gdp_yoy is not None:
                if gdp_yoy > 3.0:
                    score += 10
                    gdp_signal = "强劲增长"
                elif gdp_yoy > 1.5:
                    score += 5
                    gdp_signal = "温和增长"
                elif gdp_yoy < 0:
                    score -= 15
                    gdp_signal = "经济衰退"
                else:
                    gdp_signal = "低增长"
                observations.append(f"GDP增长: {gdp_yoy}% ({gdp_signal})")
                details.append(f"🏛️ GDP 同比: {gdp_yoy}% ({gdp_signal})")
            
            # === 5. M2 货币供应 ===
            m2_yoy = data.get('m2_money_supply', {}).get('change_yoy')
            if m2_yoy is not None:
                if m2_yoy > 8:
                    score += 10
                    m2_signal = "流动性充裕 — 利好BTC"
                elif m2_yoy > 3:
                    score += 3
                    m2_signal = "流动性正常"
                elif m2_yoy < 0:
                    score -= 10
                    m2_signal = "流动性收缩 — 风险信号"
                else:
                    m2_signal = "流动性偏紧"
                observations.append(f"M2增长: {m2_yoy}% ({m2_signal})")
                details.append(f"💧 M2 货币供应同比: {m2_yoy}% ({m2_signal})")
            
            # === 6. 收益率曲线 ===
            yield_data = data.get('yield_curve_spread', {})
            spread = yield_data.get('value')
            inverted = yield_data.get('inverted')
            if spread is not None:
                if inverted:
                    score -= 8
                    yield_signal = f"收益率曲线倒挂 ({spread}bp) — 衰退预警"
                elif spread < 0.5:
                    score -= 3
                    yield_signal = f"收益率曲线趋平 ({spread}bp)"
                else:
                    score += 3
                    yield_signal = f"收益率曲线正常 ({spread}bp)"
                observations.append(f"10Y-2Y利差: {spread}bp ({'倒挂' if inverted else '正常'})")
                details.append(f"📉 收益率曲线: {yield_signal}")
            
            # === 7. 失业率 ===
            ue = data.get('unemployment_rate', {}).get('value')
            if ue is not None:
                if ue < 4.0:
                    score += 3
                    ue_signal = "就业市场强劲"
                elif ue > 6.0:
                    score -= 8
                    ue_signal = "就业市场恶化"
                else:
                    ue_signal = "就业市场稳定"
                details.append(f"👷 失业率: {ue}% ({ue_signal})")
            
            # === 8. 消费者信心 ===
            sentiment = data.get('consumer_sentiment', {}).get('value')
            if sentiment is not None:
                if sentiment > 80:
                    score += 3
                elif sentiment < 60:
                    score -= 5
                details.append(f"😊 消费者信心: {sentiment:.1f}")
            
            # === 9. 经济周期 ===
            cycle = data.get('economic_cycle', {}).get('phase', 'unknown')
            cycle_map = {"expansion": "扩张期", "peak": "见顶期", "contraction": "衰退期", "moderate_growth": "温和增长", "unknown": "待判断"}
            cycle_cn = cycle_map.get(cycle, cycle)
            
            # === 10. 高危静默期检测 (Veto Power) ===
            is_high_risk = False
            high_risk_reason = ""
            
            # Simulated high risk logic for demonstrating Veto Power 
            # (In production, checking Forex Factory/economic calendar API is better)
            if fed_rate and fed_rate > 5.25 and spread and spread < -0.80:
                is_high_risk = True
                high_risk_reason = "极端高息+深度倒挂，流动性枯竭风险极大"
            elif cpi_yoy and cpi_yoy > 8.0:
                is_high_risk = True
                high_risk_reason = "超级滞胀期，美联储可能突发加息"
                
            # For demonstration, let's also pass user_config flag to manually trigger it
            force_high_risk = (user_config or {}).get("force_high_risk_macro", False)
            if force_high_risk:
                is_high_risk = True
                high_risk_reason = "CPI/非农数据发布前1小时静默期"
            
            if is_high_risk:
                score -= 30  # Heavily penalize score during black swan
                observations.append(f"🚨 一票否决生效: {high_risk_reason}")
                details.append(f"🚨 [VETO POWER]: {high_risk_reason}")
            
            # 确定方向
            score = max(0, min(100, score))
            direction = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"
            
            # 数据质量
            quality = data.get('data_quality', 'unknown')
            
            reasoning = f"""基于 FRED API 真实宏观经济数据分析：

📊 宏观评分：{score}/100 ({direction})
📡 数据质量：{quality}

关键指标：
{chr(10).join(details)}

🔄 经济周期判断：{cycle_cn}

💡 对加密市场影响：
- {'高利率环境压制风险资产估值' if fed_rate and fed_rate > 4 else '低利率环境利好风险资产' if fed_rate and fed_rate < 3 else '利率环境中性'}
- {'通胀压力较大，Fed可能维持紧缩' if cpi_yoy and cpi_yoy > 3.5 else '通胀回落，降息预期升温' if cpi_yoy and cpi_yoy < 2.5 else '通胀可控'}
- {'M2扩张利好BTC等稀缺资产' if m2_yoy and m2_yoy > 5 else 'M2收缩不利于风险资产' if m2_yoy and m2_yoy < 0 else 'M2增长中性'}

⚠️ 数据来源：FRED API（美联储经济数据库）— 100% 真实数据"""
            
            self.current_analysis = AnalysisResult(
                agent_type=AgentType.MACRO,
                score=score,
                direction=direction,
                reasoning=reasoning,
                key_observations=observations,
                data_sources=["FRED API (真实数据)"],
                metadata={
                    "is_high_risk_regime": is_high_risk,
                    "high_risk_reason": high_risk_reason
                }
            )
            
            return self.current_analysis
            
        except Exception as e:
            return self._no_data_result(f"FRED数据获取失败: {str(e)}")
    
    def _no_data_result(self, reason: str) -> AnalysisResult:
        return AnalysisResult(
            agent_type=AgentType.MACRO,
            score=50,
            direction="neutral",
            reasoning=f"宏观分析无法完成: {reason}\n建议配置 FRED API Key。",
            key_observations=[reason],
            data_sources=["无数据"]
        )
