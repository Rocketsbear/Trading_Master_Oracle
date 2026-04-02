"""
链上分析Agent - 使用 OnchainOS 真实链上数据 + OKX CEX 数据
"""
import asyncio
from typing import Dict, Any
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from backend.data_sources.onchain.onchainos import OnchainDataSource


class OnchainAgent(BaseAgent):
    """链上分析Agent - 专注于链上交易活动、巨鲸信号、聪明钱行为"""
    
    def __init__(self, onchainos_config: Dict = None):
        super().__init__(
            name="巨鲸追踪者 🐋",
            agent_type=AgentType.ONCHAIN,
            personality=(
                "我专注追踪聪明钱的动向。大户在转移BTC到交易所？"
                "那是抛售信号。鲸鱼在从交易所提币？那是囤积信号。"
                "资金费率极端？说明市场过度拥挤。"
                "链上数据不会骗人——它比任何KOL的喊单都诚实。"
            )
        )
        cfg = onchainos_config or {}
        self.onchain = OnchainDataSource(
            api_key=cfg.get("api_key", ""),
            api_secret=cfg.get("api_secret", ""),
            passphrase=cfg.get("passphrase", ""),
        )
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """执行链上分析"""
        try:
            # 获取综合链上数据
            data = await self.onchain.get_comprehensive_onchain_data(symbol)
            
            price_data = data.get('price', {})
            trades_data = data.get('trades', {})
            signals_data = data.get('signals', {})
            index_data = data.get('index_price', {})
            price_deviation = data.get('price_deviation_pct')
            onchainos_active = data.get('onchainos_active', False)
            
            # === 评分逻辑 ===
            score = 50
            observations = []
            
            # 1. 交易活动分析（买卖比例）
            buy_ratio = trades_data.get('buy_ratio', 50)
            total_trades = trades_data.get('total_trades', 0)
            total_volume = trades_data.get('total_volume_usd', 0)
            trade_source = trades_data.get('source', 'N/A')
            
            if buy_ratio > 65:
                score += 15
                trade_signal = f"买盘强劲，买入占比 {buy_ratio:.0f}%"
            elif buy_ratio > 55:
                score += 8
                trade_signal = f"买盘略占优势，买入占比 {buy_ratio:.0f}%"
            elif buy_ratio < 35:
                score -= 15
                trade_signal = f"卖盘压力大，买入仅占 {buy_ratio:.0f}%"
            elif buy_ratio < 45:
                score -= 8
                trade_signal = f"卖盘略占优势，买入占比 {buy_ratio:.0f}%"
            else:
                trade_signal = f"买卖均衡，买入占比 {buy_ratio:.0f}%"
            
            observations.append(f"交易: {total_trades}笔 ({trade_source}), 买入{buy_ratio:.0f}%")
            
            # 2. 聪明钱信号分析 (真实 OnchainOS 数据)
            smart_money_count = signals_data.get('smart_money_count', 0)
            whale_count = signals_data.get('whale_count', 0)
            kol_count = signals_data.get('kol_count', 0)
            total_signals = signals_data.get('total_signals', 0)
            signals_amount = signals_data.get('total_amount_usd', 0)
            
            if smart_money_count > 3:
                score += 12
                sm_signal = f"🔥 聪明钱活跃！{smart_money_count}个地址正在买入"
            elif smart_money_count > 0:
                score += 5
                sm_signal = f"有{smart_money_count}个聪明钱信号"
            else:
                sm_signal = "暂无聪明钱信号"
            
            if whale_count > 2:
                score += 10
                whale_signal = f"🐋 巨鲸频繁操作！{whale_count}个巨鲸地址活跃"
            elif whale_count > 0:
                score += 4
                whale_signal = f"{whale_count}个巨鲸在操作"
            else:
                whale_signal = "巨鲸暂无明显动作"
            
            if kol_count > 2:
                score += 5
                kol_signal = f"📢 {kol_count}个KOL正在买入"
            elif kol_count > 0:
                score += 2
                kol_signal = f"{kol_count}个KOL信号"
            else:
                kol_signal = "暂无KOL信号"
            
            observations.append(f"信号: 聪明钱{smart_money_count}, 巨鲸{whale_count}, KOL{kol_count}")
            
            # 3. Index Price 偏差检测 (抗操纵)
            deviation_section = ""
            if price_deviation is not None:
                if abs(price_deviation) > 1.0:
                    # 价格偏差超过1% — 可能有操纵
                    score -= 5
                    deviation_section = f"⚠️ CEX/Index 价差偏离 {price_deviation:+.3f}% — 可能存在价格操纵"
                    observations.append(f"⚠️ 价格偏差 {price_deviation:+.3f}%")
                elif abs(price_deviation) > 0.5:
                    deviation_section = f"CEX/Index 价差 {price_deviation:+.3f}% — 轻微偏离"
                else:
                    deviation_section = f"CEX/Index 价差 {price_deviation:+.3f}% — 正常"
            
            # 4. 资金费率
            funding_rate = signals_data.get('funding_rate', 0)
            oi = signals_data.get('open_interest', 0)
            
            if funding_rate > 0.001:
                score -= 5
                observations.append(f"费率偏高({funding_rate:.4%})，多头拥挤")
            elif funding_rate < -0.001:
                score += 5
                observations.append(f"费率为负({funding_rate:.4%})，空头占优")
            
            # 5. 增强数据 (来自 orchestrator 预获取)
            ec = (user_config or {}).get("enriched_context", {})
            vpvr = ec.get("vpvr")
            liq = ec.get("liquidation")
            
            vpvr_section = ""
            if vpvr:
                vpvr_section = f"""
📊 VPVR: POC=${vpvr.get('poc',0):,.0f}, 价值区[${vpvr.get('val',0):,.0f}-${vpvr.get('vah',0):,.0f}]"""
            
            liq_section = ""
            if liq:
                liq_section = f"""
🔥 清算推算: {liq.get('dominant_label', 'N/A')}, 支撑${liq.get('nearest_support',0):,.0f}, 阻力${liq.get('nearest_resistance',0):,.0f}"""
            
            # 6. 价格数据
            price = price_data.get('price', 0)
            if price > 0:
                observations.append(f"价格: ${price:,.2f}")
            
            # 确定方向
            score = max(0, min(100, score))
            direction = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"
            
            # 生成分析报告
            signal_source = signals_data.get('source', 'N/A')
            
            # Top signals detail
            top_signals_text = ""
            top_signals = signals_data.get('top_signals', [])
            if top_signals:
                top_signals_text = "\n\n🔥 最新信号:"
                for sig in top_signals[:5]:
                    top_signals_text += f"\n   - {sig.get('wallet_type','')}: {sig.get('token_symbol','?')} ${sig.get('amount_usd',0):,.0f} ({sig.get('chain','')})"
                    if sig.get('sold_ratio', 0) < 0.1:
                        top_signals_text += " 💎未卖出"
            
            reasoning = f"""基于 {symbol} 的链上数据分析：

📊 链上评分：{score}/100 ({direction})

{'✅ OnchainOS 真实链上数据已启用' if onchainos_active else '⚠️ OnchainOS 未配置，使用 CEX 数据替代'}

1. 交易活动 ({trade_source})：
   {trade_signal}
   - {'DEX' if total_trades > 0 else '估算'}交易 {total_trades}笔, 买入{trades_data.get('buys',0)}笔, 卖出{trades_data.get('sells',0)}笔
   - 成交量: ${total_volume:,.0f}

2. 聪明钱信号 ({signal_source})：
   - {sm_signal}
   - 巨鲸：{whale_signal}
   - KOL：{kol_signal}
   - 信号总金额：${signals_amount:,.0f}

3. 衍生品：
   - 资金费率: {funding_rate:.4%}
   - OI: {oi:,.0f}

4. 价格：${price:,.2f}
   {deviation_section}
{vpvr_section}{liq_section}{top_signals_text}

⚠️ 数据来源：{signal_source}"""

            self.current_analysis = AnalysisResult(
                agent_type=AgentType.ONCHAIN,
                score=score,
                direction=direction,
                reasoning=reasoning,
                key_observations=observations,
                data_sources=[signal_source, "OKX CEX (FR/OI/LS)", "CoinGecko"],
            )
            
            return self.current_analysis
            
        except Exception as e:
            return AnalysisResult(
                agent_type=AgentType.ONCHAIN,
                score=50,
                direction="neutral",
                reasoning=f"链上分析出错：{str(e)}",
                data_sources=["OKX OnchainOS"]
            )
