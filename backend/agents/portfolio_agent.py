"""
组合指挥官 Agent 🎯 — 最终决策者，综合所有Agent意见 + 凯利公式仓位管理
"""
from typing import Dict, Any, List
import math
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from loguru import logger


class PortfolioAgent(BaseAgent):
    """组合指挥官 🎯 — 最终决策者"""
    
    def __init__(self):
        super().__init__(
            name="组合指挥官",
            agent_type=AgentType.PORTFOLIO_MANAGER,
            personality=(
                "我是最终决策者。我综合所有Agent意见，但不简单平均。"
                "我用加权投票决定方向，用凯利公式计算最优仓位。"
                "至少3个Agent同方向才执行。如果风控卫士说'不'，我无条件服从。"
                "宁可错过，也不冲动交易。信心<60%不交易。"
            )
        )
        # Agent weights for final decision
        self.agent_weights = {
            AgentType.TECHNICAL: 0.30,    # 趋势猎手 — 最高权重
            AgentType.ONCHAIN: 0.15,      # 巨鲸追踪者
            AgentType.MACRO: 0.15,        # 宏观领航员
            AgentType.SENTIMENT: 0.15,    # 逆向交易者
            AgentType.METAPHYSICAL: 0.15, # 量化工程师
            AgentType.RISK_MANAGER: 0.10, # 风控卫士 — 有否决权
        }
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """作为独立Agent时的基础分析（通常通过 make_final_decision 调用）"""
        return AnalysisResult(
            agent_type=AgentType.PORTFOLIO_MANAGER,
            score=50,
            direction="neutral",
            reasoning="等待各Agent分析完成",
        )
    
    def make_final_decision(self, agent_results: List[AnalysisResult], 
                           account_balance: float = 10000,
                           current_price: float = 0) -> Dict[str, Any]:
        """
        综合所有Agent意见，做最终交易决策
        
        Returns: {
            "action": "buy" | "sell" | "hold",
            "confidence": 0-100,
            "position_size_pct": 0-100 (% of balance),
            "reasoning": str,
            "agent_votes": {...},
            "vetoed": bool,
        }
        """
        if not agent_results:
            return {"action": "hold", "confidence": 0, "position_size_pct": 0,
                    "reasoning": "无Agent分析数据", "agent_votes": {}, "vetoed": False}
        
        # === STEP 1: Check Risk Agent Veto ===
        risk_result = next((r for r in agent_results if r.agent_type == AgentType.RISK_MANAGER), None)
        if risk_result:
            is_vetoed = any("否决" in str(w) or "🚫" in str(w) for w in risk_result.warnings)
            if is_vetoed:
                return {
                    "action": "hold",
                    "confidence": 0,
                    "position_size_pct": 0,
                    "reasoning": f"🛡️ 风控否决: {risk_result.reasoning}",
                    "agent_votes": {r.agent_type.value: r.direction for r in agent_results},
                    "vetoed": True,
                }
        
        # === STEP 2: Weighted Vote ===
        bullish_weight = 0
        bearish_weight = 0
        total_weight = 0
        agent_votes = {}
        
        for result in agent_results:
            weight = self.agent_weights.get(result.agent_type, 0.1)
            total_weight += weight
            agent_votes[result.agent_type.value] = {
                "direction": result.direction,
                "score": result.score,
                "weight": weight,
            }
            if result.direction == "bullish":
                bullish_weight += weight
            elif result.direction == "bearish":
                bearish_weight += weight
        
        # === STEP 3: Consensus Check — need 3+ agents in same direction ===
        bullish_count = sum(1 for r in agent_results if r.direction == "bullish")
        bearish_count = sum(1 for r in agent_results if r.direction == "bearish")
        
        if bullish_count >= 3 and bullish_weight > bearish_weight:
            direction = "buy"
            consensus_strength = bullish_weight / total_weight if total_weight > 0 else 0
        elif bearish_count >= 3 and bearish_weight > bullish_weight:
            direction = "sell"
            consensus_strength = bearish_weight / total_weight if total_weight > 0 else 0
        else:
            return {
                "action": "hold",
                "confidence": 0,
                "position_size_pct": 0,
                "reasoning": f"共识不足: 多{bullish_count}/空{bearish_count}，需≥3个Agent同方向",
                "agent_votes": agent_votes,
                "vetoed": False,
            }
        
        # === STEP 4: Confidence Score ===
        weighted_avg_score = sum(
            r.score * self.agent_weights.get(r.agent_type, 0.1)
            for r in agent_results
        ) / total_weight if total_weight > 0 else 50
        
        confidence = round(consensus_strength * 100, 1)
        
        # Must have >60% confidence to trade
        if confidence < 60:
            return {
                "action": "hold",
                "confidence": confidence,
                "position_size_pct": 0,
                "reasoning": f"信心{confidence}% < 60%，不交易 (多{bullish_count}/空{bearish_count})",
                "agent_votes": agent_votes,
                "vetoed": False,
            }
        
        # === STEP 5: Kelly Position Sizing ===
        # Simplified Kelly: f = (p*b - q) / b
        # p = consensus_strength (proxy for win probability)
        # b = avg risk/reward ratio from agents
        win_prob = min(0.7, consensus_strength)  # Cap at 70%
        avg_rr = 2.0  # Default R:R
        
        # Get R:R from agent results if available
        entry_prices = [r.entry_price for r in agent_results if r.entry_price]
        tp_prices = [r.exit_price for r in agent_results if r.exit_price]
        sl_prices = [r.stop_loss for r in agent_results if r.stop_loss]
        
        if entry_prices and tp_prices and sl_prices:
            avg_entry = sum(entry_prices) / len(entry_prices)
            avg_tp = sum(tp_prices) / len(tp_prices)
            avg_sl = sum(sl_prices) / len(sl_prices)
            potential_gain = abs(avg_tp - avg_entry)
            potential_loss = abs(avg_entry - avg_sl)
            if potential_loss > 0:
                avg_rr = potential_gain / potential_loss
        
        kelly_fraction = (win_prob * avg_rr - (1 - win_prob)) / avg_rr
        kelly_fraction = max(0, min(0.25, kelly_fraction))  # Cap at 25% of balance
        
        # Half-Kelly for safety
        position_size_pct = round(kelly_fraction * 50, 1)  # 50% of full Kelly
        
        reasoning = (
            f"{'📈 做多' if direction == 'buy' else '📉 做空'} | "
            f"共识 {bullish_count if direction == 'buy' else bearish_count}/{len(agent_results)} Agent | "
            f"信心 {confidence}% | "
            f"半凯利仓位 {position_size_pct}% | "
            f"R:R {avg_rr:.1f}:1"
        )
        
        self.current_analysis = AnalysisResult(
            agent_type=AgentType.PORTFOLIO_MANAGER,
            score=weighted_avg_score,
            direction="bullish" if direction == "buy" else "bearish",
            reasoning=reasoning,
        )
        
        return {
            "action": direction,
            "confidence": confidence,
            "position_size_pct": position_size_pct,
            "reasoning": reasoning,
            "agent_votes": agent_votes,
            "vetoed": False,
            "kelly_fraction": kelly_fraction,
            "weighted_score": round(weighted_avg_score, 1),
        }
