"""
风控卫士 Agent 🛡️ — 独立风控Agent，拥有一票否决权
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from loguru import logger


class RiskAgent(BaseAgent):
    """风控卫士 🛡️ — 我是最后一道防线，拥有一票否决权"""
    
    def __init__(self):
        super().__init__(
            name="风控卫士",
            agent_type=AgentType.RISK_MANAGER,
            personality=(
                "我是最后一道防线，任何交易必须经过我审核。"
                "我会检查：今日已亏多少、连亏几单、总暴露多大、"
                "同方向持仓是否过多。我宁可错过机会，也不允许失控的风险。"
                "日亏>3%停止交易，连亏3单暂停30分钟，"
                "单笔风险>1.5%余额拒绝，同方向持仓>2拒绝。"
            )
        )
        self.trade_log = []  # Track trades for risk analysis
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.last_pause_time = None
        self.open_positions_count = {}  # {symbol_side: count}
    
    def update_trade(self, pnl: float, symbol: str, side: str):
        """Record a trade result for risk tracking"""
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self.trade_log.append({
            "time": datetime.now().isoformat(),
            "pnl": pnl, "symbol": symbol, "side": side
        })
    
    def reset_daily(self):
        """Reset daily metrics (call at midnight)"""
        self.daily_pnl = 0.0
        self.trade_log = [t for t in self.trade_log 
                         if datetime.fromisoformat(t["time"]).date() == datetime.now().date()]
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """风控审查 — 检查是否允许交易"""
        config = user_config or {}
        account_balance = config.get("account_balance", 10000)
        current_positions = config.get("positions", [])
        proposed_direction = config.get("proposed_direction", "neutral")
        proposed_margin = config.get("proposed_margin", 0)
        
        # === RISK CHECKS ===
        warnings = []
        vetoed = False
        risk_score = 50  # Start neutral
        
        # Check 1: Daily loss limit (3%)
        daily_loss_pct = abs(self.daily_pnl) / account_balance * 100 if self.daily_pnl < 0 else 0
        if daily_loss_pct >= 3.0:
            warnings.append(f"🚫 日亏 {daily_loss_pct:.1f}% ≥ 3%，今日停止交易")
            vetoed = True
            risk_score = 10
        elif daily_loss_pct >= 2.0:
            warnings.append(f"⚠️ 日亏 {daily_loss_pct:.1f}%，接近3%上限，减半仓位")
            risk_score -= 15
        
        # Check 2: Consecutive losses
        if self.consecutive_losses >= 3:
            pause_duration = timedelta(minutes=30)
            if self.last_pause_time and datetime.now() - self.last_pause_time < pause_duration:
                remaining = (self.last_pause_time + pause_duration - datetime.now()).seconds // 60
                warnings.append(f"🚫 连亏{self.consecutive_losses}单，暂停中（剩余{remaining}分钟）")
                vetoed = True
                risk_score = 15
            else:
                self.last_pause_time = datetime.now()
                warnings.append(f"⚠️ 连亏{self.consecutive_losses}单，触发30分钟冷静期 + 仓位减半")
                risk_score -= 20
        
        # Check 3: Same direction exposure
        same_dir_count = sum(1 for p in current_positions 
                           if p.get("symbol") == symbol and p.get("side") == proposed_direction)
        if same_dir_count >= 2:
            warnings.append(f"🚫 {symbol} 同方向已有{same_dir_count}个仓位，拒绝新建")
            vetoed = True
            risk_score = 20
        
        # Check 4: Total margin exposure
        total_margin = sum(p.get("marginUsed", 0) for p in current_positions)
        exposure_pct = total_margin / account_balance * 100 if account_balance > 0 else 0
        if exposure_pct >= 60:
            warnings.append(f"🚫 总保证金占用 {exposure_pct:.1f}% ≥ 60%，拒绝新仓")
            vetoed = True
            risk_score = 15
        elif exposure_pct >= 40:
            warnings.append(f"⚠️ 总保证金占用 {exposure_pct:.1f}%，接近上限")
            risk_score -= 10
        
        # Check 5: Single trade risk
        if proposed_margin > 0:
            single_risk_pct = proposed_margin / account_balance * 100
            if single_risk_pct > 1.5:
                warnings.append(f"⚠️ 单笔风险 {single_risk_pct:.1f}% > 1.5%，建议减仓")
                risk_score -= 10
        
        if not warnings:
            warnings.append("✅ 风控检查通过")
            risk_score = 70
        
        direction = "neutral" if vetoed else ("bullish" if risk_score >= 60 else "bearish" if risk_score <= 40 else "neutral")
        
        reasoning = (
            f"风控审查: 日亏{daily_loss_pct:.1f}% | 连亏{self.consecutive_losses}单 | "
            f"同向仓{same_dir_count}个 | 总暴露{exposure_pct:.1f}% | "
            f"{'🚫 否决' if vetoed else '✅ 通过'}"
        )
        
        self.current_analysis = AnalysisResult(
            agent_type=AgentType.RISK_MANAGER,
            score=risk_score,
            direction=direction,
            reasoning=reasoning,
            warnings=warnings,
            key_observations=[f"vetoed={vetoed}", f"daily_loss={daily_loss_pct:.1f}%"],
        )
        return self.current_analysis
