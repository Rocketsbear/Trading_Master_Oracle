"""
多Agent协作系统 - Agent基类
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import json


class AgentType(Enum):
    TECHNICAL = "technical"
    ONCHAIN = "onchain"
    MACRO = "macro"
    SENTIMENT = "sentiment"
    METAPHYSICAL = "metaphysical"
    MODERATOR = "moderator"
    RISK_MANAGER = "risk_manager"
    PORTFOLIO_MANAGER = "portfolio_manager"


@dataclass
class AgentMessage:
    """Agent消息"""
    agent_name: str
    agent_type: AgentType
    content: str
    score: Optional[float] = None
    reasoning: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    is_final: bool = False


@dataclass
class AnalysisResult:
    """分析结果"""
    agent_type: AgentType
    score: float
    direction: str  # "bullish", "bearish", "neutral"
    reasoning: str
    key_observations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    # 交易建议字段
    entry_price: Optional[float] = None   # 建议入场价
    exit_price: Optional[float] = None    # 建议出场价 (止盈)
    stop_loss: Optional[float] = None     # 止损价
    leverage: Optional[int] = None        # 建议杠杆倍数 (1-20)
    metadata: Dict[str, Any] = field(default_factory=dict) # 元数据用于System 2通信


class BaseAgent(ABC):
    """Agent基类"""
    
    def __init__(self, name: str, agent_type: AgentType, personality: str):
        self.name = name
        self.agent_type = agent_type
        self.personality = personality
        self.current_analysis: Optional[AnalysisResult] = None
        self.discussion_history: List[AgentMessage] = []
        self.llm = None  # 由 orchestrator 注入
    
    def set_llm(self, llm_client):
        """注入 LLM 客户端"""
        self.llm = llm_client
    
    @abstractmethod
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """独立分析 - 每个Agent自己的分析方法"""
        pass
    
    async def discuss(self, other_results: List[AnalysisResult], symbol: str = "BTC") -> AgentMessage:
        """参与讨论 - 使用 LLM 基于其他Agent的观点发表看法"""
        my_score = self.current_analysis.score if self.current_analysis else 50
        my_reasoning = self.current_analysis.reasoning if self.current_analysis else "无分析数据"
        
        # 使用 LLM 生成真正的讨论
        if self.llm:
            try:
                other_analyses = [
                    {
                        "name": r.agent_type.value,
                        "score": r.score,
                        "direction": r.direction,
                        "reasoning": r.reasoning,
                    }
                    for r in other_results
                ]
                content = await self.llm.discuss_as_agent(
                    agent_name=self.name,
                    agent_personality=self.personality,
                    own_analysis=my_reasoning,
                    other_analyses=other_analyses,
                    symbol=symbol,
                )
            except Exception as e:
                from loguru import logger
                logger.warning(f"{self.name} LLM 讨论失败: {e}，使用模板")
                content = self._template_discuss(other_results)
        else:
            content = self._template_discuss(other_results)
        
        return AgentMessage(
            agent_name=self.name,
            agent_type=self.agent_type,
            content=content,
            score=my_score,
            reasoning=self.current_analysis.reasoning if self.current_analysis else None
        )
    
    def _template_discuss(self, other_results: List[AnalysisResult]) -> str:
        """模板讨论（LLM 不可用时的后备） — 使用真实数据生成有深度的讨论"""
        if not self.current_analysis:
            return "数据不足，暂无法给出讨论意见。"
        
        my = self.current_analysis
        my_score = my.score
        my_dir = my.direction
        
        # 找到与自己观点最不同的 Agent
        diffs = [(r, abs(my_score - r.score)) for r in other_results]
        biggest_diff = max(diffs, key=lambda x: x[1], default=None)
        same_dir = [r for r in other_results if r.direction == my_dir]
        diff_dir = [r for r in other_results if r.direction != my_dir and r.direction != 'neutral']
        
        # 提取自己的关键观点（前80字）
        my_key = my.reasoning[:80] if my.reasoning else "综合分析"
        
        # 提取关键数据点
        obs = my.key_observations[:3] if my.key_observations else []
        obs_text = "；".join(obs[:2]) if obs else my_key
        
        parts = []
        
        if diff_dir and biggest_diff and biggest_diff[1] > 15:
            # 有明显分歧 — 指出分歧
            opp = biggest_diff[0]
            parts.append(f"我注意到{opp.agent_type.value}给出了{opp.score}分({opp.direction})，与我的{my_score}分({my_dir})存在分歧。")
            parts.append(f"从我的角度看，{obs_text}。")
            if len(same_dir) >= 2:
                parts.append(f"但{len(same_dir)}位专家与我观点一致，多数支持{my_dir}。")
        elif len(same_dir) >= 3:
            # 高度一致
            avg = sum(r.score for r in other_results) / len(other_results)
            parts.append(f"各方观点高度一致({len(same_dir)}/{len(other_results)}位专家{my_dir})，市场信号较为明确。")
            parts.append(f"我的分析依据：{obs_text}。")
            if abs(my_score - avg) > 5:
                parts.append(f"但我的评分({my_score})略{'高' if my_score > avg else '低'}于均值({avg:.0f})，原因是{my_key[:40]}。")
        else:
            # 一般情况
            parts.append(f"综合讨论，我维持{my_dir}判断(评分{my_score})。")
            parts.append(f"核心依据：{obs_text}。")
            if diff_dir:
                parts.append(f"理解{diff_dir[0].agent_type.value}的{diff_dir[0].direction}观点，但{my_key[:50]}。")
        
        return "".join(parts)
    
    async def adjust_opinion(self, other_results: List[AnalysisResult]) -> AnalysisResult:
        """
        根据讨论调整观点 — 让讨论真正影响评分
        
        规则:
        - 如果 3+ 个Agent方向一致且与自己相反 → 调整 ±8 分
        - 如果存在高置信度的反向证据 → 调整 ±5 分
        - 最大调整幅度 ±10 分（保持专业独立性）
        """
        if not self.current_analysis or not other_results:
            return self.current_analysis
        
        my_score = self.current_analysis.score
        my_dir = self.current_analysis.direction
        
        # 统计其他Agent的方向
        bullish_others = sum(1 for r in other_results if r.direction == "bullish")
        bearish_others = sum(1 for r in other_results if r.direction == "bearish")
        other_avg_score = sum(r.score for r in other_results) / len(other_results) if other_results else 50
        
        adjustment = 0
        reasons = []
        
        # 规则1: 多数Agent方向与自己相反 → 适度妥协
        total_others = len(other_results)
        if my_dir == "bullish" and bearish_others >= 3:
            adjustment -= 8
            reasons.append(f"{bearish_others}/{total_others}位专家看空，下调8分")
        elif my_dir == "bearish" and bullish_others >= 3:
            adjustment += 8
            reasons.append(f"{bullish_others}/{total_others}位专家看多，上调8分")
        elif my_dir == "bullish" and bearish_others >= 2:
            adjustment -= 4
            reasons.append(f"{bearish_others}位专家看空，微调-4分")
        elif my_dir == "bearish" and bullish_others >= 2:
            adjustment += 4
            reasons.append(f"{bullish_others}位专家看多，微调+4分")
        
        # 规则2: 与整体均值偏差过大 → 向均值回归
        score_diff = my_score - other_avg_score
        if abs(score_diff) > 20:
            regression = -int(score_diff * 0.15)  # 向均值回归15%
            adjustment += regression
            reasons.append(f"与均值偏差{score_diff:.0f}分，回归{regression:+d}分")
        
        # 规则3: 限制最大调整幅度 ±10
        adjustment = max(-10, min(10, adjustment))
        
        if adjustment != 0:
            new_score = max(0, min(100, my_score + adjustment))
            new_dir = "bullish" if new_score >= 60 else "bearish" if new_score <= 40 else "neutral"
            
            from loguru import logger
            logger.info(f"🔄 {self.name} 讨论后调整: {my_score}→{new_score} ({adjustment:+d}) [{', '.join(reasons)}]")
            
            # 更新自身分析
            self.current_analysis.score = new_score
            self.current_analysis.direction = new_dir
            self.current_analysis.reasoning += f"\n\n🔄 讨论后调整: {my_score}→{new_score} ({adjustment:+d}分) [{'; '.join(reasons)}]"
        
        return self.current_analysis
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "type": self.agent_type.value,
            "personality": self.personality,
            "current_score": self.current_analysis.score if self.current_analysis else None,
            "current_direction": self.current_analysis.direction if self.current_analysis else None
        }


class ModeratorAgent(BaseAgent):
    """主持人Agent - 协调各方，最终决策"""
    
    def __init__(self):
        super().__init__(
            name="主持人",
            agent_type=AgentType.MODERATOR,
            personality="中立、理性、善于综合各方观点做出决策"
        )
        self.all_results: List[AnalysisResult] = []
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """主持人最后做总结"""
        # 这个方法实际上不会被直接调用
        # 主持人的分析是通过 moderate 方法完成的
        return AnalysisResult(
            agent_type=AgentType.MODERATOR,
            score=50,
            direction="neutral",
            reasoning="等待各方分析完成"
        )
    
    async def moderate(self, results: List[AnalysisResult], user_opinion: str = None, discussion_messages: List[str] = None) -> AnalysisResult:
        """主持综合各方观点，给出最终决策（使用 LLM）"""
        self.all_results = results
        
        if not results:
            return AnalysisResult(
                agent_type=AgentType.MODERATOR,
                score=50,
                direction="neutral",
                reasoning="没有足够的分析数据"
            )
        
        # 准备各专家分析摘要
        all_analyses = [
            {
                "name": r.agent_type.value,
                "score": r.score,
                "direction": r.direction,
                "reasoning": r.reasoning,
                "entry_price": r.entry_price,
                "exit_price": r.exit_price,
                "stop_loss": r.stop_loss,
                "leverage": r.leverage,
            }
            for r in results
        ]
        
        key_points = [f"{r.agent_type.value}: {r.reasoning[:80]}..." for r in results]
        
        # 格式化讨论摘要
        discussion_summary = "\n".join(discussion_messages) if discussion_messages else None
        
        # 使用 LLM 做最终决策
        if self.llm:
            try:
                decision = await self.llm.moderate_decision(
                    all_analyses=all_analyses,
                    symbol=getattr(self, '_current_symbol', 'BTC'),
                    user_opinion=user_opinion,
                    discussion_summary=discussion_summary,
                )
                return AnalysisResult(
                    agent_type=AgentType.MODERATOR,
                    score=decision["score"],
                    direction=decision["direction"],
                    reasoning=decision["reasoning"],
                    key_observations=key_points,
                    data_sources=["综合所有Agent分析（AI决策）"]
                )
            except Exception as e:
                from loguru import logger
                logger.warning(f"LLM 主持决策失败: {e}，使用规则引擎")
        
        # 后备: 规则引擎
        return self._rule_based_moderate(results, key_points, user_opinion)
    
    def _rule_based_moderate(self, results, key_points, user_opinion=None):
        """规则引擎后备决策"""
        avg_score = sum(r.score for r in results) / len(results)
        directions = [r.direction for r in results]
        bullish_count = directions.count("bullish")
        bearish_count = directions.count("bearish")
        
        if bullish_count > bearish_count:
            direction = "bullish"
        elif bearish_count > bullish_count:
            direction = "bearish"
        else:
            direction = "neutral"
        
        direction_text = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
        scores = sorted([(r.agent_type.value, r.score) for r in results], key=lambda x: x[1], reverse=True)
        
        user_note = f"\n\n💬 用户意见：{user_opinion}" if user_opinion else ""
        reasoning = f"""综合{len(results)}位专家的分析意见：\n\n平均评分：{avg_score:.1f}/100，倾向：{direction_text[direction]}\n\n最高评分：{scores[0][0]} ({scores[0][1]:.0f}分)\n最低评分：{scores[-1][0]} ({scores[-1][1]:.0f}分){user_note}\n\n⚠️ 注意：本次使用规则引擎决策（LLM 不可用）"""
        
        return AnalysisResult(
            agent_type=AgentType.MODERATOR,
            score=avg_score,
            direction=direction,
            reasoning=reasoning,
            key_observations=key_points,
            data_sources=["综合所有Agent分析"]
        )
