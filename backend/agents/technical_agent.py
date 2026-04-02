"""
技术分析Agent — Binance K线 + 多交易所多空比/OI 数据
"""
import asyncio
from typing import Dict, Any
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from backend.data_sources.exchanges.binance_api import BinanceDataSource
from backend.analysis.technical import TechnicalIndicators
from backend.data_sources.market.exchange_data import ExchangeDataSource
from loguru import logger


class TechnicalAgent(BaseAgent):
    """技术分析Agent - K线指标 + 多交易所多空比/OI/资金费率"""
    
    def __init__(self):
        super().__init__(
            name="趋势猎手 🦅",
            agent_type=AgentType.TECHNICAL,
            personality=(
                "我只在趋势明确时出手。ADX>25确认趋势存在，"
                "EMA20/50排列确认方向，MACD柱状图放大确认动量。"
                "逆势单？不存在的。我宁愿错过也不逆势操作。"
                "多时间框架必须一致才入场。震荡市我选择观望。"
            )
        )
        self.binance = BinanceDataSource()
        self.exchanges = ExchangeDataSource()
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """执行技术分析"""
        try:
            # ===== 并行获取所有数据 =====
            klines_task = self.binance.get_klines(symbol, interval, 200)
            ticker_task = self.binance.get_ticker_24h(symbol)
            exchange_task = self.exchanges.get_comprehensive_exchange_data(symbol)
            
            klines, ticker, ex_data = await asyncio.gather(
                klines_task, ticker_task, exchange_task,
                return_exceptions=True,
            )
            
            # 处理 K线异常
            if isinstance(klines, Exception):
                raise klines
            if isinstance(ticker, Exception):
                ticker = {"price": 0, "price_change_percent": 0}
            if isinstance(ex_data, Exception):
                logger.warning(f"多交易所数据获取失败: {ex_data}")
                ex_data = {}
            
            # ===== 技术指标计算 =====
            df = TechnicalIndicators.calculate_all_indicators(klines)
            analysis = TechnicalIndicators.analyze_indicators(df)
            
            score = analysis['overall_score']
            observations = []
            
            # MACD
            if analysis['macd']['cross'] == 'golden':
                observations.append("MACD出现金叉信号")
            elif analysis['macd']['cross'] == 'death':
                observations.append("MACD出现死叉信号")
            
            # RSI
            if analysis['rsi']['status'] == 'oversold':
                observations.append("RSI超卖，可能反弹")
            elif analysis['rsi']['status'] == 'overbought':
                observations.append("RSI超买，可能回调")
            
            # 布林带
            if analysis['bollinger']['position'] == 'below_lower':
                observations.append("价格触及布林下轨")
            elif analysis['bollinger']['position'] == 'above_upper':
                observations.append("价格触及布林上轨")
            
            # ===== 多空比分析 =====
            ls_details = []
            avg_long = ex_data.get("avg_long_pct")
            ls_ratios = ex_data.get("long_short_ratios", {})
            
            if ls_ratios:
                for exchange, data in ls_ratios.items():
                    ls_details.append(f"  {exchange.upper()}: 多{data['long_pct']}% / 空{data['short_pct']}%")
                
                # 计算平均多空比
                ratios = [v['ratio'] for v in ls_ratios.values() if 'ratio' in v]
                avg_ratio = sum(ratios) / len(ratios) if ratios else 1.0
                
                if avg_long is not None:
                    # 多空比信号 (基于用户定义的阈值)
                    if avg_ratio < 0.8:
                        score += 12  # 空头过多 → 超卖反弹信号
                        observations.append(f"🟢 多空比={avg_ratio:.2f} (<0.8) — 做多权重增加")
                    elif avg_ratio > 2.8:
                        score -= 12  # 多头过多 → 过热回调信号
                        observations.append(f"🔴 多空比={avg_ratio:.2f} (>2.8) — 做空权重增加")
                    elif avg_ratio > 2.0:
                        score -= 5
                        observations.append(f"⚠️ 多空比={avg_ratio:.2f} — 多头偏多")
                    elif avg_ratio < 1.0:
                        score += 5
                        observations.append(f"⚠️ 多空比={avg_ratio:.2f} — 空头偏多")
                    else:
                        observations.append(f"多空比={avg_ratio:.2f} — 多空均衡")
            
            # ===== OI 变化趋势 =====
            oi_details = []
            oi_data = ex_data.get("open_interests", {})
            oi_change = ex_data.get("oi_change_pct")
            oi_trend = ex_data.get("oi_trend", "unknown")
            
            for exchange, oi_val in oi_data.items():
                oi_details.append(f"  {exchange.upper()}: {oi_val:,.0f}")
            
            if oi_change is not None:
                if oi_trend == "increasing":
                    score += 5
                    observations.append(f"OI增加{oi_change:+.1f}%，趋势得到确认")
                elif oi_trend == "decreasing":
                    score -= 5
                    observations.append(f"OI下降{oi_change:+.1f}%，趋势可能减弱")
                else:
                    observations.append(f"OI变化平稳({oi_change:+.1f}%)")
            
            # ===== 资金费率 =====
            fr_details = []
            funding_rates = ex_data.get("funding_rates", {})
            avg_fr = ex_data.get("avg_funding_rate")
            
            for exchange, fr in funding_rates.items():
                fr_details.append(f"  {exchange.upper()}: {fr:.4%}")
            
            if avg_fr is not None:
                if avg_fr > 0.001:  # > 0.1%
                    score -= 5
                    observations.append(f"资金费率偏高({avg_fr:.4%})，多头拥挤")
                elif avg_fr < -0.001:  # < -0.1%
                    score += 5
                    observations.append(f"资金费率为负({avg_fr:.4%})，空头占优")
            
            # ===== 增强数据 (来自 orchestrator 预获取) =====
            ec = (user_config or {}).get("enriched_context", {})
            
            # VPVR
            vpvr_section = ""
            vpvr = ec.get("vpvr")
            if vpvr:
                vpvr_adj = vpvr.get("score_adjustment", 0)
                if vpvr_adj != 0:
                    score += vpvr_adj
                    observations.append(f"VPVR: POC=${vpvr['poc']:,.0f}, 评分{vpvr_adj:+d}")
                vpvr_section = f"""
📊 VPVR 成交量分布 ({vpvr.get('exchanges_used', 0)}所):
  POC (量密): ${vpvr.get('poc', 0):,.0f}
  VAH (价值区上轨): ${vpvr.get('vah', 0):,.0f}
  VAL (价值区下轨): ${vpvr.get('val', 0):,.0f}
  → {''.join(vpvr.get('reasons', [])[:2])}"""
            
            # 清算推算
            liq_section = ""
            liq = ec.get("liquidation")
            if liq:
                liq_adj = liq.get("score_adjustment", 0)
                if liq_adj != 0:
                    score += liq_adj
                    observations.append(f"清算推算: {liq.get('dominant_label','')}, 评分{liq_adj:+d}")
                liq_fr = liq.get("funding_rates", {})
                fr_str = ', '.join(f"{k}:{v}%" for k, v in liq_fr.items()) if liq_fr else "N/A"
                liq_section = f"""
🔥 清算区间推算:
  主导方: {liq.get('dominant_label', 'N/A')}
  下方支撑: ${liq.get('nearest_support', 0):,.0f}
  上方阻力: ${liq.get('nearest_resistance', 0):,.0f}
  4所资金费率: {fr_str}
  → {''.join(liq.get('reasons', [])[:2])}"""
            
            # 订单簿
            ob_section = ""
            ob = ec.get("orderbook")
            if ob:
                imb = ob.get("imbalance", 1.0)
                if imb > 1.3:
                    score += 3
                    observations.append(f"订单簿买方主导(不平衡={imb:.1f})")
                elif imb < 0.77:
                    score -= 3
                    observations.append(f"订单簿卖方主导(不平衡={imb:.1f})")
                ob_section = f"""
📋 订单簿深度:
  买盘: ${ob.get('bid_total', 0):,.0f} | 卖盘: ${ob.get('ask_total', 0):,.0f}
  → 不平衡: {imb:.2f} ({'买方主导' if imb > 1.3 else '卖方主导' if imb < 0.77 else '均衡'})"""
            
            # Scanner
            scanner_section = ""
            scanner = ec.get("scanner")
            if scanner:
                res = scanner.get("resonance", "mixed")
                if res == "bullish":
                    score += 5
                    observations.append(f"Scanner共振: {scanner['bullish_count']}/{scanner['total']}看多")
                elif res == "bearish":
                    score -= 5
                    observations.append(f"Scanner共振: {scanner['bearish_count']}/{scanner['total']}看空")
                scanner_section = f"""
🌐 多币种Scanner:
  多: {scanner.get('bullish_count', 0)} | 空: {scanner.get('bearish_count', 0)} | 总: {scanner.get('total', 0)}
  → 共振: {res}"""
            
            # ===== 限制分数范围 =====
            score = max(0, min(100, score))
            direction = "bullish" if score >= 55 else "bearish" if score <= 45 else "neutral"
            
            # ===== 生成推理 =====
            ex_counts = ex_data.get("exchanges_count", {})
            
            ls_section = ""
            if ls_details:
                ls_section = f"""
📊 持仓人数多空比 ({ex_counts.get('ls', 0)}所):
{chr(10).join(ls_details)}
  → 平均多头: {avg_long}%"""
            
            oi_section = ""
            if oi_details:
                oi_section = f"""
📏 持仓量 OI ({ex_counts.get('oi', 0)}所):
{chr(10).join(oi_details)}
  → 12h OI 变化: {f'{oi_change:+.1f}%' if oi_change is not None else 'N/A'} ({oi_trend})"""
            
            fr_section = ""
            if fr_details:
                fr_section = f"""
💰 资金费率 ({ex_counts.get('fr', 0)}所):
{chr(10).join(fr_details)}
  → 平均: {f'{avg_fr:.4%}' if avg_fr is not None else 'N/A'}"""
            
            reasoning = f"""基于{symbol}的{interval}周期技术分析 + 多交易所数据：

📊 技术评分：{score}/100 ({direction})

🔧 技术指标：
- MACD：{'金叉' if analysis['macd']['cross'] == 'golden' else '死叉' if analysis['macd']['cross'] == 'death' else '震荡'}，当前{'多头' if analysis['macd']['trend'] == 'bullish' else '空头'}趋势
- RSI(14)：{analysis['rsi']['value']:.1f}，{analysis['rsi']['status']}
- 布林带：价格位于{'上轨' if analysis['bollinger']['position'] == 'above_upper' else '下轨' if analysis['bollinger']['position'] == 'below_lower' else '中轨'}
- 均线：{analysis['moving_averages']['trend']}
{ls_section}
{oi_section}
{fr_section}
{vpvr_section}
{liq_section}
{ob_section}
{scanner_section}

当前价格：${ticker['price']:,.2f}
24h涨跌幅：{ticker['price_change_percent']:+.2f}%

⚠️ 数据来源：Binance K线 + Binance/OKX/Bybit/Hyperliquid 多交易所数据 + VPVR/清算推算（100% 真实）"""
            
            # ===== 计算建议入场/离场/杠杆 =====
            current_price = ticker['price']
            bb_upper = analysis['bollinger'].get('upper', current_price * 1.02)
            bb_lower = analysis['bollinger'].get('lower', current_price * 0.98)
            bb_middle = analysis['bollinger'].get('middle', current_price)
            
            if direction == "bullish":
                entry = round(current_price, 2)
                exit_tp = round(bb_upper, 2)  # 止盈目标：布林上轨
                sl = round(bb_lower, 2)       # 止损：布林下轨
            elif direction == "bearish":
                entry = round(current_price, 2)
                exit_tp = round(bb_lower, 2)   # 止盈目标：布林下轨
                sl = round(bb_upper, 2)        # 止损：布林上轨
            else:
                entry = round(current_price, 2)
                exit_tp = round(bb_upper, 2)
                sl = round(bb_lower, 2)
            
            # 杠杆：评分越极端越自信，杠杆越高
            confidence = abs(score - 50) / 50  # 0~1
            lev = max(1, min(20, int(3 + confidence * 12)))
            
            # === 凯利防线伸缩 (Dynamic Risk Ceilings) ===
            adx_val = df['adx'].iloc[-1] if 'adx' in df.columns else 20
            ma_trend = analysis['moving_averages']['trend']
            if adx_val > 30 and ma_trend in ['strong_bullish', 'strong_bearish']:
                dynamic_risk_limit = 0.08  # 主升浪/主跌浪 放平至8%
                market_structure_reason = "单边主升浪(ADX>30)，放宽凯利上限至8%"
            elif adx_val < 20:
                dynamic_risk_limit = 0.02  # 震荡市压低至2%
                market_structure_reason = "混沌震荡市(ADX<20)，压低凯利上限至2%"
            else:
                dynamic_risk_limit = 0.05  # 常态5%
                market_structure_reason = f"常态波动(ADX={adx_val:.1f})，凯利上限5%"
                
            self.current_analysis = AnalysisResult(
                agent_type=AgentType.TECHNICAL,
                score=score,
                direction=direction,
                reasoning=reasoning,
                key_observations=observations,
                data_sources=["Binance API", "OKX API", "Bybit API", "Hyperliquid API", "技术指标"],
                entry_price=entry,
                exit_price=exit_tp,
                stop_loss=sl,
                leverage=lev,
                metadata={
                    "dynamic_max_risk": dynamic_risk_limit,
                    "market_structure_reason": market_structure_reason
                }
            )
            
            return self.current_analysis
            
        except Exception as e:
            logger.error(f"技术分析出错: {e}")
            return AnalysisResult(
                agent_type=AgentType.TECHNICAL,
                score=50,
                direction="neutral",
                reasoning=f"技术分析出错：{str(e)}",
                data_sources=["Binance API"]
            )
