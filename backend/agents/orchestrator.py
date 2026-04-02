"""
Agent协调器 - 管理和协调所有Agent的协作
"""
import asyncio
from typing import Dict, Any, List
from datetime import datetime
import json
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult, AgentMessage, ModeratorAgent
from backend.agents.technical_agent import TechnicalAgent
from backend.agents.onchain_agent import OnchainAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.sentiment_agent import SentimentAgent
from backend.agents.metaphysical_agent import MetaphysicalAgent
from backend.agents.risk_agent import RiskAgent
from backend.agents.portfolio_agent import PortfolioAgent
from loguru import logger


class AgentOrchestrator:
    """Agent协调器 - 管理多Agent协作"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # 初始化 LLM 客户端 (Agent 讨论用)
        self.llm = None
        agent_llm_config = self.config.get('agent_llm', {})
        if agent_llm_config.get('api_key'):
            try:
                from backend.ai.llm_client import LLMClient
                agent_base_url = agent_llm_config.get('base_url', 'https://gpt-agent.cc')
                if not agent_base_url.endswith('/v1'):
                    agent_base_url = agent_base_url.rstrip('/') + '/v1'
                self.llm = LLMClient(
                    api_key=agent_llm_config['api_key'],
                    base_url=agent_base_url,
                    model=agent_llm_config.get('model', 'MiniMax-M2.5-highspeed'),
                    protocol=agent_llm_config.get('protocol', 'anthropic'),
                )
                logger.info(f"✅ Agent LLM ({agent_llm_config.get('model', 'MiniMax-M2.5-highspeed')}, {agent_llm_config.get('protocol', 'anthropic')}) 初始化成功")
            except Exception as e:
                logger.warning(f"⚠️ Agent LLM 初始化失败: {e}，讨论和决策将使用规则引擎")
        else:
            logger.warning("⚠️ 未配置 Agent LLM API Key，讨论和决策将使用规则引擎")
        
        # 初始化所有Agent
        self.agents = {
            AgentType.TECHNICAL: TechnicalAgent(),
            AgentType.ONCHAIN: OnchainAgent(self.config.get('onchainos')),
            AgentType.MACRO: MacroAgent(self.config.get('fred_api_key')),
            AgentType.SENTIMENT: SentimentAgent(self.config.get('jwt_token')),
            AgentType.METAPHYSICAL: MetaphysicalAgent(self.config.get('deepseek', {})),
            AgentType.RISK_MANAGER: RiskAgent(),
        }
        
        # 组合指挥官 — 最终决策者
        self.portfolio_agent = PortfolioAgent()
        self.risk_agent = self.agents[AgentType.RISK_MANAGER]
        
        # 注入 LLM 到所有 Agent
        if self.llm:
            for agent in self.agents.values():
                agent.set_llm(self.llm)
        
        # 主持人 — 使用 DeepSeek (更快、更稳定)
        self.moderator = ModeratorAgent()
        deepseek_cfg = self.config.get('deepseek', {})
        if deepseek_cfg.get('api_key'):
            try:
                from backend.ai.llm_client import LLMClient
                mod_base_url = deepseek_cfg.get('base_url', 'https://openrouter.fans/v1')
                if not mod_base_url.endswith('/v1'):
                    mod_base_url = mod_base_url.rstrip('/') + '/v1'
                self.moderator_llm = LLMClient(
                    api_key=deepseek_cfg['api_key'],
                    base_url=mod_base_url,
                    model=deepseek_cfg.get('model', 'deepseek-chat'),
                    protocol='openai',
                )
                self.moderator.set_llm(self.moderator_llm)
                logger.info("✅ 主持人 LLM (DeepSeek) 初始化成功")
            except Exception as e:
                logger.warning(f"⚠️ DeepSeek 主持人初始化失败: {e}，使用默认 LLM")
                if self.llm:
                    self.moderator.set_llm(self.llm)
        elif self.llm:
            self.moderator.set_llm(self.llm)
        
        # 状态
        self.is_running = False
        self.current_symbol = None
        self.current_interval = None
        
    async def run_analysis(
        self,
        symbol: str,
        interval: str,
        user_config: Dict = None,
        websocket = None
    ) -> Dict:
        """运行完整的分析流程"""
        self.is_running = True
        self.current_symbol = symbol
        self.current_interval = interval
        self.moderator._current_symbol = symbol
        
        results = {}
        all_messages = []
        
        try:
            # === 预获取增强数据 (VPVR, 清算区间, 订单簿) ===
            enriched_context = {}
            try:
                from backend.data_sources.market.exchange_data import ExchangeDataSource
                from backend.analysis.volume_profile import compute_volume_profile, score_volume_profile
                from backend.analysis.liquidation_estimator import estimate_liquidation_zones
                import httpx
                
                _ex = ExchangeDataSource()
                
                # 并行获取: 多交易所K线(VPVR) + 综合数据(OI/FR/LS) + 订单簿
                async def _fetch_orderbook():
                    async with httpx.AsyncClient(timeout=3.0) as c:
                        r = await c.get("https://api.binance.com/api/v3/depth", params={"symbol": symbol, "limit": 50})
                        if r.status_code == 200:
                            d = r.json()
                            bid = sum(float(b[1]) * float(b[0]) for b in d.get("bids", []))
                            ask = sum(float(a[1]) * float(a[0]) for a in d.get("asks", []))
                            return {"bid_total": round(bid, 2), "ask_total": round(ask, 2), "imbalance": round(bid / ask, 2) if ask > 0 else 1.0}
                    return None
                
                kline_tasks = [
                    _ex.binance_klines(symbol, "1h", 200, "futures"),
                    _ex.okx_klines(symbol, "1h", 200, "futures"),
                    _ex.bybit_klines(symbol, "1h", 200, "futures"),
                    _ex.hyperliquid_klines(symbol, "1h", 200, "futures"),
                ]
                
                exchange_task = _ex.get_comprehensive_exchange_data(symbol)
                ob_task = _fetch_orderbook()
                
                all_results = await asyncio.gather(
                    *kline_tasks, exchange_task, ob_task,
                    return_exceptions=True
                )
                
                klines_results = all_results[:4]
                ex_data = all_results[4] if not isinstance(all_results[4], Exception) else {}
                ob_data = all_results[5] if not isinstance(all_results[5], Exception) else None
                
                # VPVR
                valid_klines = [k for k in klines_results if isinstance(k, list) and len(k) > 0]
                if valid_klines:
                    # 获取当前价格用于VPVR评分
                    last_price = valid_klines[0][-1].get("close", 0) if valid_klines[0] else 0
                    vp = compute_volume_profile(valid_klines, num_bins=50)
                    if vp:
                        vp_score = score_volume_profile(vp, last_price) if last_price > 0 else {}
                        enriched_context["vpvr"] = {
                            "poc": vp.get("poc"), "vah": vp.get("vah"), "val": vp.get("val"),
                            "exchanges_used": vp.get("exchanges_used", 0),
                            "high_volume_nodes": vp.get("high_volume_nodes", [])[:3],
                            "score_adjustment": vp_score.get("adjustment", 0),
                            "reasons": vp_score.get("reasons", []),
                        }
                
                # 清算推算
                if ex_data and last_price > 0:
                    liq = await estimate_liquidation_zones(last_price, ex_data, symbol)
                    if liq:
                        enriched_context["liquidation"] = {
                            "dominant_side": liq.get("dominant_side"),
                            "dominant_label": liq.get("dominant_label"),
                            "score_adjustment": liq.get("score_adjustment", 0),
                            "reasons": liq.get("reasons", []),
                            "key_zones_below": liq.get("key_zones_below", []),
                            "key_zones_above": liq.get("key_zones_above", []),
                            "nearest_support": liq.get("nearest_support"),
                            "nearest_resistance": liq.get("nearest_resistance"),
                            "funding_rates": liq.get("funding_rates", {}),
                        }
                
                # 订单簿
                if ob_data:
                    enriched_context["orderbook"] = ob_data
                
                # 多空比深度分析
                if ex_data:
                    try:
                        from backend.analysis.ls_analyzer import LSAnalyzer
                        ls_ratios = ex_data.get("long_short_ratios", {})
                        fr_rates = ex_data.get("funding_rates", {})
                        oi_chg = ex_data.get("oi_change_pct")
                        ls_result = LSAnalyzer.analyze_multi_exchange(
                            long_short_ratios=ls_ratios,
                            funding_rates=fr_rates,
                            oi_change_pct=oi_chg,
                        )
                        enriched_context["ls_analysis"] = ls_result
                    except Exception:
                        pass
                
                # Scanner
                import time as _t
                _scan_cache = globals().get("_multi_scan_cache", {})
                if _scan_cache.get("result") and _t.time() - _scan_cache.get("timestamp", 0) < 300:
                    opps = _scan_cache["result"].get("opportunities", [])
                    if opps:
                        bull = sum(1 for o in opps if o.get("direction") == "bullish")
                        bear = sum(1 for o in opps if o.get("direction") == "bearish")
                        enriched_context["scanner"] = {
                            "bullish_count": bull, "bearish_count": bear, "total": len(opps),
                            "resonance": "bullish" if bull >= len(opps) * 0.7 else "bearish" if bear >= len(opps) * 0.7 else "mixed",
                        }
                
                await _ex.close()
                logger.info(f"深度分析增强数据: VPVR={'✅' if 'vpvr' in enriched_context else '❌'}, 清算={'✅' if 'liquidation' in enriched_context else '❌'}, 订单簿={'✅' if 'orderbook' in enriched_context else '❌'}, Scanner={'✅' if 'scanner' in enriched_context else '❌'}")
            except Exception as e:
                logger.warning(f"增强数据预获取错误(非致命): {e}")
            
            # 注入到 user_config
            if user_config is None:
                user_config = {}
            user_config["enriched_context"] = enriched_context
            
            # === 第一阶段：并行分析 ===
            await self._broadcast(websocket, {
                "type": "phase",
                "phase": 1,
                "message": "🔍 第一阶段：各专家开始独立分析..."
            })
            
            # 并行执行所有Agent的分析（带超时保护）
            analysis_tasks = [
                self._run_agent_analysis(agent_type, symbol, interval, user_config, websocket)
                for agent_type in AgentType
                if agent_type != AgentType.MODERATOR
            ]
            
            try:
                analyses = await asyncio.wait_for(
                    asyncio.gather(*analysis_tasks, return_exceptions=True),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("Agent分析超时，使用已完成的结果")
                analyses = []
                await self._broadcast(websocket, {
                    "type": "phase",
                    "phase": 2,
                    "message": "⚠️ 部分分析超时，使用已完成的结果..."
                })
            
            # 收集结果并逐个广播
            for agent_type, analysis in zip([t for t in AgentType if t != AgentType.MODERATOR], analyses):
                if analysis and not isinstance(analysis, (Exception, BaseException)):
                    results[agent_type] = analysis
                    agent_msg = {
                        "type": "agent_result",
                        "agent": agent_type.value,
                        "agent_name": self.agents[agent_type].name if agent_type in self.agents else str(agent_type),
                        "score": analysis.score,
                        "direction": analysis.direction,
                        "reasoning": analysis.reasoning,
                        "entry_price": analysis.entry_price,
                        "exit_price": analysis.exit_price,
                        "stop_loss": analysis.stop_loss,
                        "leverage": analysis.leverage,
                        "timestamp": datetime.now().isoformat()
                    }
                    all_messages.append(agent_msg)
                    await self._broadcast(websocket, agent_msg)
            
            # === 第二阶段：讨论 ===
            await self._broadcast(websocket, {
                "type": "phase",
                "phase": 2,
                "message": "💬 第二阶段：专家们开始讨论..."
            })
            
            # 并行发起所有Agent讨论（而非依次发表，避免后面的Agent超时）
            discussion_tasks = {
                agent_type: self._run_agent_discussion(agent_type, results, websocket, symbol=self.current_symbol or symbol)
                for agent_type in list(results.keys())
            }
            disc_results = await asyncio.gather(
                *discussion_tasks.values(),
                return_exceptions=True,
            )
            # 收集讨论内容 —— 传给主持人做综合决策
            discussion_messages = []
            # 按原始顺序广播讨论结果
            for agent_type, msg in zip(discussion_tasks.keys(), disc_results):
                if msg and not isinstance(msg, (Exception, BaseException)):
                    disc_msg = {
                        "type": "discussion",
                        "agent": msg.agent_name,
                        "message": msg.content,
                        "timestamp": datetime.now().isoformat()
                    }
                    all_messages.append(disc_msg)
                    discussion_messages.append(f"【{msg.agent_name}】{msg.content}")
                    await self._broadcast(websocket, disc_msg)
            
            # === 讨论后观点调整 — 让讨论真正影响评分 ===
            for agent_type, agent in self.agents.items():
                if agent_type in results:
                    other = [r for t, r in results.items() if t != agent_type]
                    old_score = results[agent_type].score
                    adjusted = await agent.adjust_opinion(other)
                    if adjusted and adjusted.score != old_score:
                        results[agent_type] = adjusted
                        adjust_msg = {
                            "type": "discussion",
                            "agent": agent.name,
                            "message": f"🔄 讨论后调整评分: {old_score:.0f} → {adjusted.score:.0f} ({adjusted.score - old_score:+.0f}分)",
                            "timestamp": datetime.now().isoformat()
                        }
                        all_messages.append(adjust_msg)
                        await self._broadcast(websocket, adjust_msg)
            
            # === 第三阶段：主持总结 ===
            await self._broadcast(websocket, {
                "type": "phase",
                "phase": 3,
                "message": "🎯 第三阶段：主持人综合各方意见..."
            })
            
            # 注入增强数据摘要到讨论消息，让主持人有完整信息
            if enriched_context:
                ec_summary_parts = []
                if "vpvr" in enriched_context:
                    vp = enriched_context["vpvr"]
                    ec_summary_parts.append(f"VPVR(4所): POC=${vp.get('poc',0):,.0f}, VAH=${vp.get('vah',0):,.0f}, VAL=${vp.get('val',0):,.0f}")
                if "liquidation" in enriched_context:
                    lq = enriched_context["liquidation"]
                    ec_summary_parts.append(f"清算推算: {lq.get('dominant_label','N/A')}, 支撑${lq.get('nearest_support',0):,.0f}, 阻力${lq.get('nearest_resistance',0):,.0f}")
                if "orderbook" in enriched_context:
                    ob = enriched_context["orderbook"]
                    ec_summary_parts.append(f"订单簿: 买${ob.get('bid_total',0):,.0f}/卖${ob.get('ask_total',0):,.0f}, 不平衡={ob.get('imbalance',1.0):.2f}")
                if "scanner" in enriched_context:
                    sc = enriched_context["scanner"]
                    ec_summary_parts.append(f"Scanner: 多{sc.get('bullish_count',0)}/空{sc.get('bearish_count',0)}/{sc.get('total',0)}总, 共振={sc.get('resonance','mixed')}")
                if ec_summary_parts:
                    discussion_messages.append(f"【增强数据摘要】{'；'.join(ec_summary_parts)}")
            
            # 主持做最终决策 (超时+异常保护)
            try:
                final_result = await asyncio.wait_for(
                    self.moderator.moderate(list(results.values()), discussion_messages=discussion_messages),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                logger.warning("主持人决策超时(30s)，使用规则引擎后备")
                await self._broadcast(websocket, {
                    "type": "discussion", "agent": "主持人",
                    "message": "⚠️ AI 决策超时，使用规则引擎快速决策...",
                    "timestamp": datetime.now().isoformat()
                })
                final_result = self.moderator._rule_based_moderate(
                    list(results.values()),
                    [f"{r.agent_type.value}: {r.reasoning[:60]}..." for r in results.values()]
                )
            except Exception as e:
                logger.error(f"主持人决策异常: {e}，使用规则引擎后备")
                await self._broadcast(websocket, {
                    "type": "discussion", "agent": "主持人",
                    "message": f"⚠️ AI 决策出错 ({type(e).__name__})，使用规则引擎...",
                    "timestamp": datetime.now().isoformat()
                })
                final_result = self.moderator._rule_based_moderate(
                    list(results.values()),
                    [f"{r.agent_type.value}: {r.reasoning[:60]}..." for r in results.values()]
                )
            
            # 计算平均入场/离场/杠杆 — 只取与最终方向一致的 agent
            final_dir = final_result.direction
            prices = [r for r in results.values() if r.entry_price]
            
            # 过滤: 只取方向一致的 agent 价格
            if final_dir != "neutral":
                matching = [r for r in prices if r.direction == final_dir]
                if matching:
                    prices = matching
            
            avg_entry = round(sum(r.entry_price for r in prices) / len(prices), 2) if prices else None
            avg_exit = round(sum(r.exit_price for r in prices) / len(prices), 2) if prices else None
            avg_sl = round(sum(r.stop_loss for r in prices) / len(prices), 2) if prices else None
            avg_lev = round(sum(r.leverage for r in prices if r.leverage) / len([r for r in prices if r.leverage])) if any(r.leverage for r in prices) else None
            
            # 🔴 验证 TP/SL 方向正确性
            if avg_entry and avg_exit and avg_sl:
                if final_dir == "bullish":
                    if avg_exit <= avg_entry:  # TP 应该 > entry
                        avg_exit = round(avg_entry * 1.02, 2)  # 至少 +2%
                    if avg_sl >= avg_entry:  # SL 应该 < entry
                        avg_sl = round(avg_entry * 0.98, 2)  # 至少 -2%
                elif final_dir == "bearish":
                    if avg_exit >= avg_entry:  # TP 应该 < entry
                        avg_exit = round(avg_entry * 0.98, 2)
                    if avg_sl <= avg_entry:  # SL 应该 > entry
                        avg_sl = round(avg_entry * 1.02, 2)
            
            # === 返回结果 ===
            final_result_dict = {
                "type": "final_decision",
                "direction": final_result.direction,
                "score": final_result.score,
                "reasoning": final_result.reasoning,
                "entry_price": avg_entry,
                "exit_price": avg_exit,
                "stop_loss": avg_sl,
                "leverage": avg_lev,
                "timestamp": datetime.now().isoformat()
            }
            
            await self._broadcast(websocket, final_result_dict)
            
            return {
                "success": True,
                "phase": "complete",
                "results": {k.value: self._analysis_to_dict(v) for k, v in results.items()},
                "final_decision": final_result_dict,
                "messages": all_messages
            }
            
        except Exception as e:
            logger.error(f"分析流程异常: {e}")
            await self._broadcast(websocket, {
                "type": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            self.is_running = False
    
    async def _run_agent_analysis(
        self,
        agent_type: AgentType,
        symbol: str,
        interval: str,
        user_config: Dict,
        websocket
    ) -> AnalysisResult:
        """运行单个Agent的分析"""
        agent = self.agents.get(agent_type)
        if not agent:
            return None
        
        # 通知开始分析
        await self._broadcast(websocket, {
            "type": "agent_start",
            "agent": agent_type.value,
            "agent_name": agent.name,
            "message": f"🧠 {agent.name} 开始分析..."
        })
        
        # 执行分析
        result = await agent.analyze(symbol, interval, user_config)
        
        # 通知完成
        await self._broadcast(websocket, {
            "type": "agent_complete",
            "agent": agent_type.value,
            "agent_name": agent.name,
            "score": result.score,
            "direction": result.direction,
            "message": f"✅ {agent.name} 完成分析：{result.score}分 ({result.direction})"
        })
        
        return result
    
    async def _run_agent_discussion(
        self,
        agent_type: AgentType,
        all_results: Dict[AgentType, AnalysisResult],
        websocket,
        symbol: str = "BTC"
    ) -> AgentMessage:
        """运行单个Agent的讨论 (带超时保护)"""
        agent = self.agents.get(agent_type)
        if not agent:
            return None
        
        other_results = [r for at, r in all_results.items() if at != agent_type]
        
        try:
            message = await asyncio.wait_for(
                agent.discuss(other_results, symbol=symbol),
                timeout=120.0
            )
            return message
        except asyncio.TimeoutError:
            logger.warning(f"Agent {agent.name} 讨论超时(120s)，跳过")
            return AgentMessage(
                agent_name=agent.name,
                agent_type=agent_type,
                content=f"⚠️ {agent.name}讨论超时，保留原始分析意见",
                score=agent.current_analysis.score if agent.current_analysis else 50,
            )
        except Exception as e:
            logger.warning(f"Agent {agent.name} 讨论异常: {e}")
            return None
    
    async def _broadcast(self, websocket, data: Dict):
        """广播消息到WebSocket"""
        if websocket:
            try:
                await websocket.send_json(data)
            except Exception as e:
                logger.warning(f"WebSocket 广播失败: {e}")
    
    def _analysis_to_dict(self, analysis: AnalysisResult) -> Dict:
        """将分析结果转换为字典"""
        return {
            "score": analysis.score,
            "direction": analysis.direction,
            "reasoning": analysis.reasoning,
            "key_observations": analysis.key_observations,
            "warnings": analysis.warnings,
            "data_sources": analysis.data_sources,
            "entry_price": analysis.entry_price,
            "exit_price": analysis.exit_price,
            "stop_loss": analysis.stop_loss,
            "leverage": analysis.leverage,
        }
    
    async def run_re_deliberation(self, user_opinion: str, websocket=None) -> Dict:
        """Phase 4: 用户意见注入 → 重新评议"""
        # 收集当前各 agent 结果
        results = {}
        for agent_type, agent in self.agents.items():
            if agent.current_analysis:
                results[agent_type] = agent.current_analysis
        
        if not results:
            return {"success": False, "error": "请先运行分析"}
        
        await self._broadcast(websocket, {
            "type": "phase", "phase": 4,
            "message": f"🗣️ 第四阶段：用户注入意见 → 重新评议..."
        })
        
        # 把用户意见广播
        await self._broadcast(websocket, {
            "type": "user_opinion",
            "message": user_opinion,
            "timestamp": datetime.now().isoformat()
        })
        
        # 让每个 agent 基于用户意见重新讨论 (带超时)
        all_messages = []
        for agent_type, agent in self.agents.items():
            if not agent.current_analysis:
                continue
            if agent.llm:
                try:
                    other_results = [r for at, r in results.items() if at != agent_type]
                    prompt = f"""用户刚提出了自己的交易意见："{user_opinion}"

你之前的分析是：评分{agent.current_analysis.score}，方向{agent.current_analysis.direction}。
其他专家的意见评分范围为 {min(r.score for r in other_results):.0f}-{max(r.score for r in other_results):.0f}。

请结合用户的交易意见，重新审视你的分析。你需要：
1. 尊重用户意见但也要保持专业判断
2. 给出修正后的入场价、止盈价、止损价
3. 推荐杠杆倍数
4. 简短说明理由（50字内）"""
                    response = await asyncio.wait_for(
                        agent.llm.chat([
                            {"role": "system", "content": f"你是{agent.name}，{agent.personality}。简短回复。"},
                            {"role": "user", "content": prompt}
                        ]),
                        timeout=40.0
                    )
                    msg = {"type": "discussion", "agent": agent.name, "message": response, "timestamp": datetime.now().isoformat()}
                    all_messages.append(msg)
                    await self._broadcast(websocket, msg)
                except asyncio.TimeoutError:
                    logger.warning(f"Agent {agent.name} 重新评议超时(40s)")
                    msg = {"type": "discussion", "agent": agent.name, "message": f"⚠️ {agent.name}评议超时，保留原始意见", "timestamp": datetime.now().isoformat()}
                    all_messages.append(msg)
                except Exception as e:
                    logger.warning(f"Agent {agent.name} 重新评议失败: {e}")
        
        # 主持人做最终综合 (带超时+异常保护)
        try:
            final_result = await asyncio.wait_for(
                self.moderator.moderate(list(results.values()), user_opinion=user_opinion),
                timeout=30.0
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"主持人重新评议异常: {e}，使用规则引擎")
            final_result = self.moderator._rule_based_moderate(
                list(results.values()),
                [f"{r.agent_type.value}: {r.reasoning[:60]}..." for r in results.values()],
                user_opinion=user_opinion
            )
        
        prices = [r for r in results.values() if r.entry_price]
        avg_entry = round(sum(r.entry_price for r in prices) / len(prices), 2) if prices else None
        avg_exit = round(sum(r.exit_price for r in prices) / len(prices), 2) if prices else None
        avg_sl = round(sum(r.stop_loss for r in prices) / len(prices), 2) if prices else None
        avg_lev = round(sum(r.leverage for r in prices if r.leverage) / len([r for r in prices if r.leverage])) if any(r.leverage for r in prices) else None
        
        final_dict = {
            "type": "final_decision",
            "direction": final_result.direction, "score": final_result.score,
            "reasoning": final_result.reasoning,
            "entry_price": avg_entry, "exit_price": avg_exit,
            "stop_loss": avg_sl, "leverage": avg_lev,
            "user_opinion_integrated": True,
            "timestamp": datetime.now().isoformat()
        }
        await self._broadcast(websocket, final_dict)
        
        return {"success": True, "final_decision": final_dict, "messages": all_messages}
    
    def get_agent_status(self) -> List[Dict]:
        """获取所有Agent的状态"""
        status = []
        for agent_type, agent in self.agents.items():
            status.append(agent.to_dict())
        return status
