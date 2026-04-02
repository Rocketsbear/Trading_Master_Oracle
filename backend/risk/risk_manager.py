"""
风险管理引擎 — Risk Manager
提供仓位管理、动态止盈止损、连续亏损保护、每日风控限额
"""
import json
import os
from datetime import datetime, date
from typing import Dict, Optional, List
from dataclasses import dataclass, field, asdict
from loguru import logger


@dataclass
class TradeRecord:
    """单笔交易记录"""
    id: str
    symbol: str
    side: str              # buy / sell
    entry_price: float
    exit_price: Optional[float] = None
    amount: float = 0.0
    leverage: int = 1
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    trailing_stop: Optional[float] = None
    pnl: float = 0.0
    roe: float = 0.0       # Return on Equity (%)
    status: str = "open"   # open / closed / stopped
    source: str = "ai"     # ai / manual
    opened_at: str = ""
    closed_at: str = ""
    close_reason: str = "" # tp / sl / trailing / manual / timeout / circuit_breaker


class RiskManager:
    """
    风险管理核心模块
    
    职责:
    1. 仓位计算 — 基于账户余额和止损距离
    2. 杠杆限制 — 波动率反向调节
    3. 每日亏损限制 — 熔断保护
    4. 连续亏损保护 — 降仓机制
    5. 动态止盈止损 — ATR-based
    6. 交易记录 — 持久化到本地
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # === 风控参数（可配置）===
        self.max_risk_per_trade = self.config.get("max_risk_per_trade", 0.02)    # 单笔最大风险 2%
        self.max_daily_loss = self.config.get("max_daily_loss", 0.05)            # 每日最大亏损 5%
        self.max_leverage = self.config.get("max_leverage", 5)                   # 最大杠杆 5x
        self.min_rr_ratio = self.config.get("min_rr_ratio", 1.5)                # 最小盈亏比 1.5:1
        self.consecutive_loss_threshold = self.config.get("consecutive_loss_threshold", 3)  # 连败阈值
        self.consecutive_loss_reduction = self.config.get("consecutive_loss_reduction", 0.5) # 降仓比例
        self.trailing_stop_trigger = self.config.get("trailing_stop_trigger", 1.0)  # 触发移动止损的R倍数
        self.atr_sl_multiplier = self.config.get("atr_sl_multiplier", 2.0)       # 止损ATR倍数
        self.atr_tp_multiplier = self.config.get("atr_tp_multiplier", 3.0)       # 止盈ATR倍数
        
        # === 状态追踪 ===
        self.account_balance = self.config.get("account_balance", 10000)   # 默认模拟盘 $10,000
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.today_trade_count = 0
        self.circuit_breaker_active = False
        self.today = date.today().isoformat()
        
        # === Hybrid AI (System 2) Control Flags ===
        self.macro_regime_is_high_risk = False
        self.macro_regime_reason = ""
        self.dynamic_max_kelly_fraction = self.max_risk_per_trade
        
        # === 交易记录 ===
        self.trades: List[TradeRecord] = []
        self.trade_log_path = self.config.get(
            "trade_log_path",
            os.path.join(os.path.dirname(__file__), '../../data/trade_history.json')
        )
        self._load_trades()
        
        logger.info(f"✅ 风险管理引擎初始化: 单笔风险{self.max_risk_per_trade*100}%, "
                     f"日亏损限额{self.max_daily_loss*100}%, 最大杠杆{self.max_leverage}x")
    
    def update_balance(self, balance: float):
        """同步用户设置的账户余额"""
        if balance > 0:
            self.account_balance = balance
            logger.info(f"💰 RiskManager 余额同步: ${balance:,.0f}")
            
    # ========================================
    # System 2 控制接口 (Hybrid AI)
    # ========================================
    
    def set_macro_regime(self, is_high_risk: bool, reason: str = ""):
        """System 2 宏观监控更新（Veto Power）"""
        self.macro_regime_is_high_risk = is_high_risk
        self.macro_regime_reason = reason
        if is_high_risk:
            logger.warning(f"🚨 [System 2 覆盖] 触发宏观一票否决权: {reason} — 已禁止 XGBoost 开单")
        else:
            logger.info(f"🟢 [System 2 更新] 宏观静默期解除")
            
    def set_dynamic_risk_limit(self, max_risk: float, reason: str = ""):
        """System 2 动态风险上限（伸缩防线）"""
        self.dynamic_max_kelly_fraction = max_risk
        logger.info(f"🛡️ [System 2 覆盖] 动态防线调整: 凯利上限设为 {max_risk*100:.1f}% ({reason})")
    
    # ========================================
    # 1. 动态仓位计算 (Kelly Criterion)
    # ========================================
    
    def calculate_kelly_fraction(self, win_probability: float, rr_ratio: float, kelly_multiplier: float = 0.5) -> float:
        """
        计算凯利准则下的最佳风控比例
        K% = W - [(1 - W) / R]
        
        参数:
        - win_probability: 预估胜率 (0.0 ~ 1.0)
        - rr_ratio: 盈亏比 (Reward / Risk)
        - kelly_multiplier: 分数凯利乘数 (如 0.5 代表半凯利, 降低回撤)
        
        返回: 0.0 ~ 1.0 的资金暴露百分比
        """
        if rr_ratio <= 0 or win_probability <= 0:
            return 0.0
            
        q = 1.0 - win_probability
        k_fraction = win_probability - (q / rr_ratio)
        
        # 必须大于 0 才有交易价值 (数学期望为正)
        if k_fraction <= 0:
            return 0.0
            
        return k_fraction * kelly_multiplier

    def calculate_kelly_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        ml_win_probability: float = 0.50,
        leverage: int = 1,
        balance: float = None,
        account_balance: float = None,
        base_risk_pct: float = None,
    ) -> Dict:
        """
        基于凯利公式(Kelly Criterion)动态调仓
        替代以前固定 2% 风险的机械逻辑
        """
        self._check_daily_reset()
        balance = account_balance or balance or self.account_balance
        
        sl_distance = abs(entry_price - stop_loss)
        tp_distance = abs(target_price - entry_price)
        
        if sl_distance <= 0:
            sl_distance = entry_price * 0.01  # Fallback 1%
            
        rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 1.0
        
        # 1. 计算理论 Kelly 风险比例
        kelly_risk_pct = self.calculate_kelly_fraction(ml_win_probability, rr_ratio, kelly_multiplier=0.5)
        
        # 2. 最高风控墙拦截
        # 假如用户设定最大单笔风险是 5%，但受 System 2 动态防线控制，取两者最小值
        base_max_risk = (base_risk_pct / 100.0) if base_risk_pct else self.max_risk_per_trade
        max_allowed_risk = min(base_max_risk, self.dynamic_max_kelly_fraction)
        final_risk_pct = min(kelly_risk_pct, max_allowed_risk)
        
        # 如果模型极其不看好 (Kelly <= 0), 强制降为极小仓位 (0.2%) 测试
        if final_risk_pct <= 0:
            final_risk_pct = 0.002
            
        # 3. 连续亏损阶梯降仓拦截
        if self.consecutive_losses >= self.consecutive_loss_threshold:
            final_risk_pct *= self.consecutive_loss_reduction
            logger.warning(f"⚠️ 凯利风控拦截: 连续{self.consecutive_losses}次亏损，仓位降至{final_risk_pct*100:.2f}%风险")
            
        max_risk_amount = balance * final_risk_pct
        
        # 仓位（以标的计价）
        position_size = max_risk_amount / sl_distance
        # 所需保证金
        margin_required = position_size * entry_price / leverage
        # 仓位价值
        position_value = position_size * entry_price
        
        # 破产/熔断上限拦截: 保证金不超过余额的 30%
        max_margin = min(balance * 0.3, balance)
        if margin_required > max_margin:
            position_size = max_margin * leverage / entry_price
            margin_required = max_margin
            position_value = position_size * entry_price
        
        logger.info(f"📊 凯利公式: P(Win)={ml_win_probability:.1%}, R:R={rr_ratio:.2f} -> 理论 Kelly: {kelly_risk_pct*100:.2f}% | 实际下注: {final_risk_pct*100:.2f}%")
        
        return {
            "position_size": round(position_size, 6),
            "position_value_usd": round(position_value, 2),
            "margin_required": round(margin_required, 2),
            "max_risk_amount": round(max_risk_amount, 2),
            "risk_pct": round(final_risk_pct * 100, 2),
            "kelly_pct": round(kelly_risk_pct * 100, 2),
            "win_probability": round(ml_win_probability * 100, 1),
            "sl_distance": round(sl_distance, 2),
            "sl_distance_pct": round(sl_distance / entry_price * 100, 3),
            "consecutive_losses": self.consecutive_losses,
            "position_reduced": self.consecutive_losses >= self.consecutive_loss_threshold,
        }
        
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        leverage: int = 1,
        balance: float = None,
        account_balance: float = None,
        risk_pct: float = None,
    ) -> Dict:
        """
        基于固定百分比风险模型计算仓位大小
        
        公式: position_size = max_risk_amount / abs(entry - sl)
        支持 account_balance / risk_pct 覆盖 (来自前端用户设置)
        """
        self._check_daily_reset()
        
        balance = account_balance or balance or self.account_balance
        
        # 连续亏损降仓
        base_risk = (risk_pct / 100.0) if risk_pct else self.max_risk_per_trade
        trade_risk_pct = base_risk
        if self.consecutive_losses >= self.consecutive_loss_threshold:
            trade_risk_pct *= self.consecutive_loss_reduction
            logger.warning(f"⚠️ 连续{self.consecutive_losses}次亏损，仓位降至{trade_risk_pct*100:.1f}%风险")
        
        max_risk_amount = balance * trade_risk_pct  # 最多亏多少钱
        sl_distance = abs(entry_price - stop_loss)
        
        if sl_distance <= 0:
            sl_distance = entry_price * 0.01  # 兜底: 1%
        
        # 仓位（以标的计价）
        position_size = max_risk_amount / sl_distance
        # 所需保证金
        margin_required = position_size * entry_price / leverage
        # 仓位价值
        position_value = position_size * entry_price
        
        # 安全检查: 保证金不超过余额的 30%，且绝对不超过余额
        max_margin = min(balance * 0.3, balance)
        if margin_required > max_margin:
            position_size = max_margin * leverage / entry_price
            margin_required = max_margin
            position_value = position_size * entry_price
        
        return {
            "position_size": round(position_size, 6),
            "position_value_usd": round(position_value, 2),
            "margin_required": round(margin_required, 2),
            "max_risk_amount": round(max_risk_amount, 2),
            "risk_pct": round(trade_risk_pct * 100, 2),
            "sl_distance": round(sl_distance, 2),
            "sl_distance_pct": round(sl_distance / entry_price * 100, 3),
            "consecutive_losses": self.consecutive_losses,
            "position_reduced": self.consecutive_losses >= self.consecutive_loss_threshold,
        }
    
    def calculate_signal_scaled_position(
        self,
        entry_price: float,
        stop_loss: float,
        leverage: int = 1,
        score: int = 50,
        balance: float = None,
    ) -> Dict:
        """
        基于信号强度的动态仓位计算
        
        信号强度 = abs(score - 50)，范围 0~50
        映射到余额使用比例：
          弱信号 (15-20) → 5-10%
          中等   (20-30) → 15-20%
          强信号 (30-40) → 25-35%
          极强   (40-50) → 40-50%
        """
        self._check_daily_reset()
        balance = balance or self.account_balance
        
        # Signal strength: how far from neutral (50)
        signal_strength = abs(score - 50)  # 0~50
        
        # Map signal_strength to position percentage of balance
        # Using a piecewise linear mapping:
        if signal_strength <= 15:
            # Threshold zone (65-35 border) — minimal position
            position_pct = 0.05  # 5%
            tier = '🟡 试探'
        elif signal_strength <= 20:
            # Weak signal — 5-10%
            t = (signal_strength - 15) / 5  # 0~1
            position_pct = 0.05 + t * 0.05  # 5% → 10%
            tier = '🟡 弱'
        elif signal_strength <= 30:
            # Medium signal — 10-20%
            t = (signal_strength - 20) / 10  # 0~1
            position_pct = 0.10 + t * 0.10  # 10% → 20%
            tier = '🟠 中等'
        elif signal_strength <= 40:
            # Strong signal — 20-35%
            t = (signal_strength - 30) / 10  # 0~1
            position_pct = 0.20 + t * 0.15  # 20% → 35%
            tier = '🔴 强'
        else:
            # Extreme signal — 35-50%
            t = min(1.0, (signal_strength - 40) / 10)  # 0~1
            position_pct = 0.35 + t * 0.15  # 35% → 50%
            tier = '🔥 极强'
        
        # Apply consecutive loss reduction
        if self.consecutive_losses >= self.consecutive_loss_threshold:
            position_pct *= self.consecutive_loss_reduction
            logger.warning(f"⚠️ 连续{self.consecutive_losses}次亏损，仓位从{tier}进一步降低")
        
        # Calculate margin (how much of balance to use as margin)
        margin = balance * position_pct
        
        # Position size in coin units
        position_size = margin * leverage / entry_price
        position_value = position_size * entry_price
        
        # Calculate risk metrics
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            sl_distance = entry_price * 0.01
        risk_amount = position_size * sl_distance  # How much we lose if SL hit
        risk_of_balance = risk_amount / balance * 100  # Risk as % of balance
        
        # Safety cap: risk per trade should not exceed max_risk_per_trade * 3
        # (even for extreme signals, absolute risk capped)
        max_allowed_risk = balance * self.max_risk_per_trade * 3
        if risk_amount > max_allowed_risk:
            scale_down = max_allowed_risk / risk_amount
            position_size *= scale_down
            margin *= scale_down
            position_value *= scale_down
            risk_amount = max_allowed_risk
            position_pct *= scale_down
            risk_of_balance = risk_amount / balance * 100
        
        # Safety cap: margin <= 30% of balance (same as calculate_position_size)
        max_margin = balance * 0.3
        if margin > max_margin:
            scale_down = max_margin / margin
            position_size *= scale_down
            margin = max_margin
            position_value *= scale_down
            risk_amount *= scale_down
            position_pct *= scale_down
            risk_of_balance = risk_amount / balance * 100
            logger.info(f"⚠️ 信号仓位保证金超限 → 缩放至余额30% (${max_margin:,.0f})")
        
        return {
            "position_size": round(position_size, 6),
            "position_value_usd": round(position_value, 2),
            "margin_required": round(margin, 2),
            "max_risk_amount": round(risk_amount, 2),
            "risk_pct": round(risk_of_balance, 2),
            "position_pct": round(position_pct * 100, 1),
            "signal_strength": signal_strength,
            "signal_tier": tier,
            "sl_distance": round(sl_distance, 2),
            "sl_distance_pct": round(sl_distance / entry_price * 100, 3),
            "consecutive_losses": self.consecutive_losses,
            "position_reduced": self.consecutive_losses >= self.consecutive_loss_threshold,
        }
    
    def calculate_multi_tp(self, entry_price: float, direction: str, atr: float, 
                           score: int = 50) -> Dict:
        """
        分批止盈计算 — TP1/TP2/TP3
        
        TP1 (50% position): 1.0× ATR — 保守目标
        TP2 (30% position): 1.5× ATR — 标准目标
        TP3 (20% position): 2.5× ATR — 激进目标
        
        强信号(score>70)时目标更远, 弱信号时更近
        """
        # 信号强度调整目标距离
        strength = abs(score - 50) / 50  # 0~1
        distance_mult = 0.7 + strength * 0.6  # 0.7x ~ 1.3x
        
        if direction == "bullish":
            tp1 = round(entry_price + atr * 1.0 * distance_mult, 2)
            tp2 = round(entry_price + atr * 1.5 * distance_mult, 2)
            tp3 = round(entry_price + atr * 2.5 * distance_mult, 2)
            sl = round(entry_price - atr * 1.2, 2)
        elif direction == "bearish":
            tp1 = round(entry_price - atr * 1.0 * distance_mult, 2)
            tp2 = round(entry_price - atr * 1.5 * distance_mult, 2)
            tp3 = round(entry_price - atr * 2.5 * distance_mult, 2)
            sl = round(entry_price + atr * 1.2, 2)
        else:
            # Neutral — range targets
            tp1 = round(entry_price + atr * 0.5, 2)
            tp2 = round(entry_price + atr * 1.0, 2)
            tp3 = round(entry_price + atr * 1.5, 2)
            sl = round(entry_price - atr * 0.8, 2)
        
        return {
            "tp_levels": [
                {"level": 1, "price": tp1, "pct": 50, "label": "TP1 (50%)"},
                {"level": 2, "price": tp2, "pct": 30, "label": "TP2 (30%)"},
                {"level": 3, "price": tp3, "pct": 20, "label": "TP3 (20%)"},
            ],
            "stop_loss": sl,
            "direction": direction,
            "atr_used": round(atr, 2),
            "distance_multiplier": round(distance_mult, 2),
        }
    
    def calculate_trailing_stop(self, entry_price: float, current_price: float,
                                 direction: str, atr: float,
                                 tp1_hit: bool = False, tp2_hit: bool = False) -> Dict:
        """
        Trailing Stop 计算
        
        规则:
        - 未到 TP1: 初始 SL = entry - 1.2×ATR
        - TP1 达到: SL 上移至入场价 (保本)
        - TP2 达到: SL 上移至 TP1
        - 持续追踪: SL = current_high - 1×ATR (做多)
        """
        if direction == "bullish":
            initial_sl = round(entry_price - atr * 1.2, 2)
            tp1_price = round(entry_price + atr * 1.0, 2)
            
            if tp2_hit:
                trailing_sl = max(tp1_price, round(current_price - atr * 0.8, 2))
            elif tp1_hit:
                trailing_sl = max(entry_price, round(current_price - atr * 1.0, 2))
            else:
                trailing_sl = initial_sl
        else:
            initial_sl = round(entry_price + atr * 1.2, 2)
            tp1_price = round(entry_price - atr * 1.0, 2)
            
            if tp2_hit:
                trailing_sl = min(tp1_price, round(current_price + atr * 0.8, 2))
            elif tp1_hit:
                trailing_sl = min(entry_price, round(current_price + atr * 1.0, 2))
            else:
                trailing_sl = initial_sl
        
        return {
            "trailing_stop": round(trailing_sl, 2),
            "initial_stop": initial_sl,
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "mode": "trailing_tp2" if tp2_hit else "breakeven" if tp1_hit else "initial",
        }
    
    def kelly_position_size(self, entry_price: float, stop_loss: float, leverage: int = 1,
                            balance: float = None) -> Dict:
        """
        Kelly Criterion 仓位计算
        
        half-Kelly: f* = 0.5 × (W×R - L) / R
        - W = 胜率, L = 败率, R = 平均盈利/平均亏损
        
        Requires 20+ trade history. Falls back to fixed % if insufficient data.
        """
        balance = balance or self.account_balance
        
        # Need at least 20 trades for meaningful stats
        closed_trades = [t for t in self.trades if t.status == 'closed' and t.pnl != 0]
        if len(closed_trades) < 20:
            return self.calculate_position_size(entry_price, stop_loss, leverage, balance=balance)
        
        wins = [t for t in closed_trades if t.pnl > 0]
        losses = [t for t in closed_trades if t.pnl < 0]
        
        win_rate = len(wins) / len(closed_trades) if closed_trades else 0.5
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 1
        avg_loss = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 1
        
        R = avg_win / avg_loss if avg_loss > 0 else 1
        
        # Kelly formula: f* = (W × R - L) / R
        L = 1 - win_rate
        kelly_f = (win_rate * R - L) / R if R > 0 else 0
        
        # Use half-Kelly (conservative)
        half_kelly = kelly_f / 2
        
        # Cap between 0.5% and 5%
        risk_pct = max(0.005, min(0.05, half_kelly))
        
        max_risk_amount = balance * risk_pct
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance <= 0:
            sl_distance = entry_price * 0.01
        
        position_size = max_risk_amount / sl_distance
        margin_required = position_size * entry_price / leverage
        position_value = position_size * entry_price
        
        # Safety cap: margin <= 30% of balance
        max_margin = balance * 0.3
        if margin_required > max_margin:
            position_size = max_margin * leverage / entry_price
            margin_required = max_margin
            position_value = position_size * entry_price
        
        return {
            "position_size": round(position_size, 6),
            "position_value_usd": round(position_value, 2),
            "margin_required": round(margin_required, 2),
            "max_risk_amount": round(max_risk_amount, 2),
            "risk_pct": round(risk_pct * 100, 2),
            "sl_distance": round(sl_distance, 2),
            "sl_distance_pct": round(sl_distance / entry_price * 100, 3),
            "consecutive_losses": self.consecutive_losses,
            "position_reduced": self.consecutive_losses >= self.consecutive_loss_threshold,
            "kelly_info": {
                "win_rate": round(win_rate * 100, 1),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "rr_ratio": round(R, 2),
                "kelly_f": round(kelly_f * 100, 2),
                "half_kelly": round(half_kelly * 100, 2),
                "trades_analyzed": len(closed_trades),
            },
        }
    
    # ========================================
    # 2. 动态止盈止损（ATR-based）
    # ========================================
    
    def calculate_dynamic_sl_tp(
        self,
        entry_price: float,
        direction: str,         # bullish / bearish
        atr: float,
        current_score: int = 50,
    ) -> Dict:
        """
        基于 ATR 的动态止盈止损
        
        - 止损 = ATR × sl_multiplier（默认2x，保证在噪音之外）
        - 止盈 = ATR × tp_multiplier（默认3x，保证盈亏比≥1.5:1）
        - 高信心度 → TP可更远（score越极端，TP倍数越大）
        """
        # 根据评分信心度调节 TP 倍数
        confidence = abs(current_score - 50) / 50  # 0~1
        tp_mult = self.atr_tp_multiplier + confidence * 1.0  # 3.0 ~ 4.0
        sl_mult = self.atr_sl_multiplier                      # 固定 2.0
        
        # 最小止损保护（至少 0.5% 距离）
        min_sl = entry_price * 0.005
        sl_distance = max(atr * sl_mult, min_sl)
        tp_distance = atr * tp_mult
        
        if direction == "bullish":
            sl_price = round(entry_price - sl_distance, 2)
            tp_price = round(entry_price + tp_distance, 2)
            # Trailing stop: 盈利超 1R 时移动到成本价
            trailing_trigger = round(entry_price + sl_distance * self.trailing_stop_trigger, 2)
        else:  # bearish
            sl_price = round(entry_price + sl_distance, 2)
            tp_price = round(entry_price - tp_distance, 2)
            trailing_trigger = round(entry_price - sl_distance * self.trailing_stop_trigger, 2)
        
        rr_ratio = round(tp_distance / sl_distance, 2) if sl_distance > 0 else 0
        
        return {
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "sl_distance": round(sl_distance, 2),
            "tp_distance": round(tp_distance, 2),
            "rr_ratio": rr_ratio,
            "trailing_trigger": trailing_trigger,
            "trailing_new_sl": entry_price,  # 触发后SL移到入场价
            "atr": round(atr, 2),
            "sl_multiplier": sl_mult,
            "tp_multiplier": round(tp_mult, 2),
        }
    
    # ========================================
    # 3. 杠杆计算（波动率反向调节）
    # ========================================
    
    def calculate_leverage(
        self,
        score: int,
        atr: float,
        current_price: float,
        direction: str,
    ) -> Dict:
        """
        智能杠杆计算
        
        规则:
        - 基础杠杆由信号强度决定
        - 高波动率反向降低杠杆
        - 硬上限 max_leverage (默认5x)
        """
        confidence = abs(score - 50) / 50  # 0~1
        
        # 基础杠杆: 1x ~ max_leverage
        if score >= 80 or score <= 20:
            base_leverage = min(5, self.max_leverage)     # 极强信号
        elif score >= 70 or score <= 30:
            base_leverage = min(3, self.max_leverage)     # 强信号
        elif score >= 60 or score <= 40:
            base_leverage = min(2, self.max_leverage)     # 中等信号
        else:
            base_leverage = 1                              # 弱信号
        
        # 波动率调节: ATR 占价格比例越大，杠杆越低
        atr_pct = atr / current_price * 100 if current_price > 0 else 1
        if atr_pct > 3.0:       # 高波动 (>3%)
            vol_factor = 0.5
        elif atr_pct > 2.0:     # 中波动
            vol_factor = 0.7
        elif atr_pct > 1.0:     # 正常波动
            vol_factor = 0.85
        else:                    # 低波动
            vol_factor = 1.0
        
        final_leverage = max(1, min(self.max_leverage, int(base_leverage * vol_factor)))
        
        return {
            "leverage": final_leverage,
            "base_leverage": base_leverage,
            "vol_factor": vol_factor,
            "atr_pct": round(atr_pct, 3),
            "signal_strength": "极强" if confidence > 0.6 else "强" if confidence > 0.4 else "中等" if confidence > 0.2 else "弱",
            "max_leverage": self.max_leverage,
        }
    
    # ========================================
    # 4. 每日亏损保护 & 熔断
    # ========================================
    
    def can_trade(self) -> Dict:
        """检查是否允许交易"""
        self._check_daily_reset()
        
        max_loss = self.account_balance * self.max_daily_loss
        
        # System 2 Veto Power
        if getattr(self, "macro_regime_is_high_risk", False):
            return {
                "allowed": False,
                "reason": f"🔴 宏观静默期: {self.macro_regime_reason}",
                "daily_pnl": self.daily_pnl,
                "max_daily_loss": max_loss,
            }
        
        if self.circuit_breaker_active:
            return {
                "allowed": False,
                "reason": f"🔴 熔断中: 今日亏损 ${abs(self.daily_pnl):.2f} 已触及限额 ${max_loss:.2f}",
                "daily_pnl": self.daily_pnl,
                "max_daily_loss": max_loss,
            }
        
        if self.daily_pnl <= -max_loss:
            self.circuit_breaker_active = True
            logger.error(f"🔴 触发熔断! 日亏损 ${abs(self.daily_pnl):.2f} ≥ 限额 ${max_loss:.2f}")
            return {
                "allowed": False,
                "reason": f"🔴 触发每日亏损熔断: ${abs(self.daily_pnl):.2f} / ${max_loss:.2f}",
                "daily_pnl": self.daily_pnl,
                "max_daily_loss": max_loss,
            }
        
        return {
            "allowed": True,
            "reason": "✅ 可交易",
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": round(self.daily_pnl / self.account_balance * 100, 2) if self.account_balance > 0 else 0,
            "remaining_risk": round(max_loss + self.daily_pnl, 2),
            "consecutive_losses": self.consecutive_losses,
            "today_trades": self.today_trade_count,
        }
    
    def record_trade_result(self, pnl: float, trade_id: str = None):
        """记录交易PnL结果"""
        self._check_daily_reset()
        self.daily_pnl += pnl
        self.today_trade_count += 1
        
        if pnl < 0:
            self.consecutive_losses += 1
            logger.info(f"📉 亏损 ${pnl:.2f} | 连续亏损 {self.consecutive_losses}次 | 日PnL: ${self.daily_pnl:.2f}")
        else:
            self.consecutive_losses = 0  # 盈利重置连败计数
            logger.info(f"📈 盈利 ${pnl:.2f} | 连败归零 | 日PnL: ${self.daily_pnl:.2f}")
        
        # 更新交易记录
        if trade_id:
            for trade in self.trades:
                if trade.id == trade_id:
                    trade.pnl = pnl
                    trade.status = "closed"
                    trade.closed_at = datetime.now().isoformat()
                    break
        
        self._save_trades()
    
    # ========================================
    # 5. 交易记录持久化
    # ========================================
    
    def open_trade(self, trade: Dict) -> TradeRecord:
        """开仓记录"""
        record = TradeRecord(
            id=trade.get("id", str(datetime.now().timestamp())),
            symbol=trade.get("symbol", "BTCUSDT"),
            side=trade.get("side", "buy"),
            entry_price=trade.get("entry_price", 0),
            amount=trade.get("amount", 0),
            leverage=trade.get("leverage", 1),
            tp_price=trade.get("tp_price"),
            sl_price=trade.get("sl_price"),
            trailing_stop=trade.get("trailing_stop"),
            source=trade.get("source", "ai"),
            opened_at=datetime.now().isoformat(),
            status="open",
        )
        self.trades.append(record)
        self._save_trades()
        return record
    
    def get_stats(self) -> Dict:
        """获取交易统计"""
        closed = [t for t in self.trades if t.status == "closed"]
        if not closed:
            return {
                "total_trades": 0, "win_rate": 0, "avg_pnl": 0,
                "total_pnl": 0, "max_drawdown": 0, "profit_factor": 0,
                "avg_rr": 0, "consecutive_losses": self.consecutive_losses,
            }
        
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl < 0]
        total_profit = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        
        # Max drawdown
        equity_curve = []
        running_pnl = 0
        for t in closed:
            running_pnl += t.pnl
            equity_curve.append(running_pnl)
        
        max_dd = 0
        peak = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
        
        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "total_pnl": round(sum(t.pnl for t in closed), 2),
            "avg_pnl": round(sum(t.pnl for t in closed) / len(closed), 2),
            "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else 9999.0,
            "max_drawdown": round(max_dd, 2),
            "consecutive_losses": self.consecutive_losses,
            "daily_pnl": round(self.daily_pnl, 2),
            "account_balance": self.account_balance,
        }
    
    # ========================================
    # Internal
    # ========================================
    
    def _check_daily_reset(self):
        """每日重置检查"""
        today = date.today().isoformat()
        if today != self.today:
            logger.info(f"📅 新交易日 {today}，重置日统计")
            self.today = today
            self.daily_pnl = 0.0
            self.today_trade_count = 0
            self.circuit_breaker_active = False
    
    def _load_trades(self):
        """加载交易历史"""
        try:
            if os.path.exists(self.trade_log_path):
                with open(self.trade_log_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trades = [TradeRecord(**t) for t in data.get("trades", [])]
                    logger.info(f"📂 加载 {len(self.trades)} 条历史交易记录")
        except Exception as e:
            logger.warning(f"加载交易记录失败: {e}")
            self.trades = []
    
    def _save_trades(self):
        """保存交易历史"""
        try:
            os.makedirs(os.path.dirname(self.trade_log_path), exist_ok=True)
            data = {
                "trades": [asdict(t) for t in self.trades[-500:]],  # 最多保留500条
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.trade_log_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存交易记录失败: {e}")
