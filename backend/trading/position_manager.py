"""
Position Manager — 后端持仓管理核心
所有持仓状态在后端维护，前端只做展示

功能:
1. 开仓/平仓/部分平仓
2. 3级止盈 (TP1=1R 平30%, TP2=2R 平40%, TP3=3R 平30%)
3. 移动止损 (1R盈利→SL移入场价, 2R→SL移+1R)
4. 持久化到 JSON 文件
"""
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from loguru import logger


@dataclass
class TPLevel:
    """单个止盈级别"""
    price: float         # 触发价格
    close_pct: float     # 平仓比例 (0.3 = 30%)
    triggered: bool = False
    triggered_at: str = ""


@dataclass
class ActivePosition:
    """活跃持仓"""
    id: str
    symbol: str
    side: str              # buy / sell
    entry_price: float
    current_price: float
    amount: float          # 当前数量 (部分平仓后会减少)
    original_amount: float # 原始数量
    leverage: int
    
    # TP/SL
    sl_price: float
    original_sl: float     # 初始 SL (trailing 用)
    tp_levels: List[Dict] = field(default_factory=list)  # 3级止盈
    
    # Trailing Stop
    trailing_active: bool = False
    trailing_sl: float = 0.0       # 当前 trailing SL 价格
    highest_price: float = 0.0     # 多单最高价 / 空单最低价
    
    # PnL
    pnl: float = 0.0               # 当前未实现盈亏
    realized_pnl: float = 0.0      # 已实现盈亏 (部分平仓)
    roe: float = 0.0               # ROE %
    
    # Meta
    margin_used: float = 0.0
    liq_price: float = 0.0         # 预估强平价
    source: str = "ai"             # ai / manual
    account_balance: float = 0.0   # 开仓时的账户余额（本金）
    status: str = "open"           # open / partial_closed / closed
    opened_at: str = ""
    closed_at: str = ""
    close_reason: str = ""         # tp1/tp2/tp3/sl/trailing/manual/timeout/circuit_breaker
    max_hold_hours: int = 24       # Auto-close after N hours (0 = disabled)
    
    # Score/reasoning at open
    score: int = 50
    reasoning: str = ""
    
    # Indicator snapshot at open time (for reflection)
    indicator_snapshot: Dict = field(default_factory=dict)
    # {rsi, adx, fng, smc_structure, smc_signals, trend_agreement, breakdown, volume_signal}
    
    # Price watermarks (for reflection)
    max_profit: float = 0.0        # 最大浮盈 $
    max_drawdown: float = 0.0      # 最大浮亏 $
    max_profit_price: float = 0.0  # 浮盈最高时的价格
    max_drawdown_price: float = 0.0 # 浮亏最深时的价格
    
    # DCA / Scaled Entry
    pending_orders: List[Dict] = field(default_factory=list)
    # [{price, amount, filled, created_at}]


class PositionManager:
    """
    后端持仓管理器 — 所有持仓的 Single Source of Truth
    """
    
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.join(os.path.dirname(__file__), '../../data')
        self.positions_file = os.path.join(self.data_dir, 'active_positions.json')
        self.history_file = os.path.join(self.data_dir, 'position_history.json')
        self.positions: Dict[str, ActivePosition] = {}  # id -> position
        self.history: List[Dict] = []
        self._load()
        logger.info(f"✅ PositionManager 初始化: {len(self.positions)} 个活跃持仓")
    
    # ==========================================
    # 开仓
    # ==========================================
    
    def open_position(self, trade: Dict) -> ActivePosition:
        """
        开仓 — 创建活跃持仓，计算 3 级止盈
        
        trade: {symbol, side, entry_price, amount, leverage, sl_price, tp_price, score, reasoning, source}
        """
        pos_id = f"{trade['symbol']}_{int(time.time() * 1000)}"
        
        entry = trade['entry_price']
        sl = trade.get('sl_price', 0)
        tp = trade.get('tp_price', 0)
        side = trade['side']
        lev = trade.get('leverage', 1)
        amount = trade['amount']
        
        # Calculate SL distance for R-multiples
        sl_distance = abs(entry - sl) if sl else entry * 0.015  # Fallback 1.5%
        
        # V4: 2-level TP — 60% at target, 40% runner at +50% extension
        if side == 'buy':
            tp_base = tp if tp else round(entry + sl_distance * 2.0, 2)
            tp_extension = abs(tp_base - entry) * 0.5
            tp_levels = [
                {"price": tp_base, "close_pct": 0.6, "triggered": False, "triggered_at": ""},  # TP1: 60% at target
                {"price": round(tp_base + tp_extension, 2), "close_pct": 0.4, "triggered": False, "triggered_at": ""},  # TP2: 40% runner
            ]
            liq_price = round(entry * (1 - 1/lev * 0.9), 2)
        else:  # sell
            tp_base = tp if tp else round(entry - sl_distance * 2.0, 2)
            tp_extension = abs(entry - tp_base) * 0.5
            tp_levels = [
                {"price": tp_base, "close_pct": 0.6, "triggered": False, "triggered_at": ""},
                {"price": round(tp_base - tp_extension, 2), "close_pct": 0.4, "triggered": False, "triggered_at": ""},
            ]
            liq_price = round(entry * (1 + 1/lev * 0.9), 2)
        
        margin = amount * entry / lev
        
        pos = ActivePosition(
            id=pos_id,
            symbol=trade['symbol'],
            side=side,
            entry_price=entry,
            current_price=entry,
            amount=amount,
            original_amount=amount,
            leverage=lev,
            sl_price=sl if sl else round(entry * (0.985 if side == 'buy' else 1.015), 2),
            original_sl=sl if sl else round(entry * (0.985 if side == 'buy' else 1.015), 2),
            tp_levels=tp_levels,
            trailing_active=False,
            trailing_sl=0.0,
            highest_price=entry,
            margin_used=round(margin, 2),
            liq_price=liq_price,
            source=trade.get('source', 'ai'),
            account_balance=trade.get('account_balance', 0),
            status='open',
            opened_at=datetime.now().isoformat(),
            score=trade.get('score', 50),
            reasoning=trade.get('reasoning', ''),
            indicator_snapshot=trade.get('indicator_snapshot', {}),
        )
        
        self.positions[pos_id] = pos
        
        # DCA: If scale_in, add second tranche pending order at better price
        if trade.get('scale_in') and sl_distance > 0:
            dca_offset = sl_distance * 0.5
            if side == 'buy':
                dca_price = round(entry - dca_offset, 2)  # Buy lower
            else:
                dca_price = round(entry + dca_offset, 2)  # Sell higher
            
            dca_amount = round(amount * 0.4 / 0.6, 6)  # 60/40 split: initial was 60%, this is the 40%
            pos.pending_orders = [{
                "price": dca_price,
                "amount": dca_amount,
                "filled": False,
                "created_at": datetime.now().isoformat(),
            }]
            # Reduce initial to 60%
            pos.amount = round(amount * 0.6, 6)
            pos.original_amount = round(amount * 0.6, 6)
            logger.info(f"📊 DCA: 首仓60% ({pos.amount}) @ ${entry:,.2f} + 挂单40% ({dca_amount}) @ ${dca_price:,.2f}")
        
        self._save()
        
        tp_labels = " / ".join(f"TP{i+1} ${tp['price']:,.2f}" for i, tp in enumerate(tp_levels))
        logger.info(
            f"📈 开仓 [{side.upper()}] {trade['symbol']} "
            f"@ ${entry:,.2f} × {amount} ({lev}x) "
            f"| SL ${pos.sl_price:,.2f} "
            f"| {tp_labels}"
        )
        
        return pos
    
    # ==========================================
    # 平仓
    # ==========================================
    
    def close_position(self, pos_id: str, close_price: float = None, 
                       reason: str = "manual", pct: float = 1.0) -> Optional[Dict]:
        """
        平仓（全部或部分）
        pct: 0.0~1.0 平仓比例
        Returns: {pnl, roe, closed_amount, remaining_amount}
        """
        if pos_id not in self.positions:
            logger.warning(f"⚠️ 持仓 {pos_id} 不存在")
            return None
        
        pos = self.positions[pos_id]
        price = close_price or pos.current_price
        close_amount = pos.amount * pct
        
        # Calculate PnL for this close
        if pos.side == 'buy':
            pnl = (price - pos.entry_price) * close_amount
        else:
            pnl = (pos.entry_price - price) * close_amount
        
        roe = (pnl / (close_amount * pos.entry_price / pos.leverage)) * 100 if close_amount > 0 else 0
        
        pos.realized_pnl += pnl
        pos.amount -= close_amount
        pos.amount = round(pos.amount, 8)
        
        result = {
            "position_id": pos_id,
            "symbol": pos.symbol,
            "side": pos.side,
            "close_price": price,
            "close_amount": close_amount,
            "remaining_amount": pos.amount,
            "pnl": round(pnl, 2),
            "roe": round(roe, 2),
            "reason": reason,
            "total_realized_pnl": round(pos.realized_pnl, 2),
        }
        
        if pos.amount <= 0.000001:  # Fully closed
            pos.status = "closed"
            pos.closed_at = datetime.now().isoformat()
            pos.close_reason = reason
            pos.pnl = pos.realized_pnl
            pos.roe = roe
            
            # Move to history — add computed fields
            history_record = asdict(pos)
            history_record['position_value'] = round(pos.entry_price * pos.original_amount, 2)
            history_record['account_balance'] = pos.account_balance
            history_record['close_price'] = price
            self.history.append(history_record)
            del self.positions[pos_id]
            
            logger.info(
                f"📊 全平 [{pos.side.upper()}] {pos.symbol} @ ${price:,.2f} "
                f"| PnL: {'+'if pnl>=0 else ''}${pnl:.2f} ({roe:+.1f}%) "
                f"| 原因: {reason}"
            )
        else:
            pos.status = "partial_closed"
            logger.info(
                f"📊 部分平仓 [{pos.side.upper()}] {pos.symbol} "
                f"| 平{close_amount:.6f} 剩{pos.amount:.6f} "
                f"| PnL: {'+'if pnl>=0 else ''}${pnl:.2f} | 原因: {reason}"
            )
        
        self._save()
        self._save_history()
        return result
    
    # ==========================================
    # 价格更新 + TP/SL/Trailing 检查
    # ==========================================
    
    def update_price(self, symbol: str, price: float) -> List[Dict]:
        """
        更新价格并检查所有持仓的 TP/SL/Trailing
        Returns: 触发的平仓事件列表
        """
        events = []
        positions_to_check = [p for p in self.positions.values() if p.symbol == symbol]
        
        for pos in positions_to_check:
            pos.current_price = price
            
            # Update PnL
            if pos.side == 'buy':
                pos.pnl = round((price - pos.entry_price) * pos.amount + pos.realized_pnl, 2)
                pos.roe = round((price - pos.entry_price) / pos.entry_price * pos.leverage * 100, 2)
            else:
                pos.pnl = round((pos.entry_price - price) * pos.amount + pos.realized_pnl, 2)
                pos.roe = round((pos.entry_price - price) / pos.entry_price * pos.leverage * 100, 2)
            
            # Update highest/lowest price for trailing
            if pos.side == 'buy':
                pos.highest_price = max(pos.highest_price, price)
            else:
                pos.highest_price = min(pos.highest_price, price) if pos.highest_price > 0 else price
            
            # === UPDATE PRICE WATERMARKS (for reflection) ===
            current_profit = pos.pnl - pos.realized_pnl  # Unrealized only
            if current_profit > pos.max_profit:
                pos.max_profit = round(current_profit, 2)
                pos.max_profit_price = price
            if current_profit < -pos.max_drawdown:
                pos.max_drawdown = round(abs(current_profit), 2)
                pos.max_drawdown_price = price
            
            # === CHECK PENDING ORDERS (DCA fill) ===
            for order in pos.pending_orders:
                if order.get('filled'):
                    continue
                fill_hit = (pos.side == 'buy' and price <= order['price']) or \
                           (pos.side == 'sell' and price >= order['price'])
                if fill_hit:
                    old_amount = pos.amount
                    old_cost = pos.amount * pos.entry_price
                    new_cost = order['amount'] * order['price']
                    pos.amount = round(pos.amount + order['amount'], 6)
                    pos.original_amount = round(pos.original_amount + order['amount'], 6)
                    # Weighted average entry price
                    pos.entry_price = round((old_cost + new_cost) / pos.amount, 2)
                    pos.margin_used = round(pos.amount * pos.entry_price / pos.leverage, 2)
                    order['filled'] = True
                    order['filled_at'] = datetime.now().isoformat()
                    logger.info(
                        f"📊 DCA 加仓 [{pos.symbol}] +{order['amount']} @ ${order['price']:,.2f} "
                        f"→ 均价 ${pos.entry_price:,.2f} (总量 {pos.amount})"
                    )
            
            # === CHECK STOP LOSS ===
            sl_hit = (pos.side == 'buy' and price <= pos.sl_price) or \
                     (pos.side == 'sell' and price >= pos.sl_price)
            
            # Check trailing SL if active
            trailing_sl_hit = False
            if pos.trailing_active and pos.trailing_sl > 0:
                trailing_sl_hit = (pos.side == 'buy' and price <= pos.trailing_sl) or \
                                  (pos.side == 'sell' and price >= pos.trailing_sl)
            
            if sl_hit or trailing_sl_hit:
                reason = "trailing_sl" if trailing_sl_hit else "sl"
                result = self.close_position(pos.id, price, reason=reason)
                if result:
                    events.append({"type": "close", "reason": reason, **result})
                continue
            
            # === CHECK LIQUIDATION PROXIMITY ===
            if pos.liq_price > 0:
                liq_distance = abs(price - pos.liq_price) / price
                if liq_distance < 0.01:  # Within 1% of liquidation
                    result = self.close_position(pos.id, price, reason="liq_protect")
                    if result:
                        events.append({"type": "close", "reason": "liq_protect", **result})
                    continue
            
            # === CHECK TAKE PROFIT (V4: 2-level 60/40) ===
            for i, tp in enumerate(pos.tp_levels):
                if tp["triggered"]:
                    continue
                
                tp_hit = (pos.side == 'buy' and price >= tp["price"]) or \
                         (pos.side == 'sell' and price <= tp["price"])
                
                if tp_hit:
                    tp["triggered"] = True
                    tp["triggered_at"] = datetime.now().isoformat()
                    
                    close_pct = tp["close_pct"]
                    reason = f"tp{i+1}"
                    result = self.close_position(pos.id, price, reason=reason, pct=close_pct)
                    
                    if result:
                        events.append({"type": "partial_close", "reason": reason, "tp_level": i+1, **result})
                    
                    # V4: TP1 (60%) → move SL to breakeven + activate trailing
                    if i == 0 and pos.id in self.positions:
                        pos.sl_price = pos.entry_price
                        pos.trailing_active = True
                        pos.trailing_sl = pos.entry_price
                        logger.info(f"🔒 V4 TP1(60%)触发 → SL移至入场价 ${pos.entry_price:,.2f} (保本+trailing)")
                    
                    # V4: TP2 (40% runner) → final close, trailing handles the rest
                    if i == 1 and pos.id in self.positions:
                        logger.info(f"🎯 V4 TP2(40% runner)触发 → 全部平仓")
                    
                    break  # Only trigger one TP level per update
            
            # === UPDATE TRAILING STOP ===
            if pos.trailing_active and pos.id in self.positions:
                sl_distance = abs(pos.entry_price - pos.original_sl)
                if pos.side == 'buy':
                    new_trailing = pos.highest_price - sl_distance
                    if new_trailing > pos.trailing_sl:
                        pos.trailing_sl = round(new_trailing, 2)
                        pos.sl_price = pos.trailing_sl
                else:
                    new_trailing = pos.highest_price + sl_distance
                    if new_trailing < pos.trailing_sl:
                        pos.trailing_sl = round(new_trailing, 2)
                        pos.sl_price = pos.trailing_sl
        
        if events:
            self._save()
        
        return events
    
    # ==========================================
    # 查询
    # ==========================================
    
    def get_all_positions(self) -> List[Dict]:
        """获取所有活跃持仓"""
        return [asdict(p) for p in self.positions.values()]
    
    def get_symbols(self) -> List[str]:
        """获取所有有持仓的交易对"""
        return list(set(p.symbol for p in self.positions.values()))
    
    def get_total_margin(self) -> float:
        """获取总保证金占用"""
        return sum(p.margin_used for p in self.positions.values())
    
    def get_position_count(self, symbol: str = None, side: str = None) -> int:
        """获取持仓数量"""
        positions = self.positions.values()
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]
        if side:
            positions = [p for p in positions if p.side == side]
        return len(list(positions))
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """获取交易历史"""
        return self.history[-limit:]
    
    def get_stats(self) -> Dict:
        """获取交易统计"""
        closed = self.history
        if not closed:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}
        
        wins = [t for t in closed if t.get("realized_pnl", 0) > 0 or t.get("pnl", 0) > 0]
        pnls = [t.get("realized_pnl", 0) or t.get("pnl", 0) for t in closed]
        total_pnl = sum(pnls)
        
        return {
            "total": len(closed),
            "wins": len(wins),
            "losses": len(closed) - len(wins),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / len(closed), 2),
            "active_positions": len(self.positions),
            "total_margin": round(self.get_total_margin(), 2),
        }
    
    # ==========================================
    # 持久化
    # ==========================================
    
    def _save(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            data = {p_id: asdict(p) for p_id, p in self.positions.items()}
            with open(self.positions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存持仓失败: {e}")
    
    def _save_history(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history[-500:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史失败: {e}")
    
    def _load(self):
        try:
            if os.path.exists(self.positions_file):
                with open(self.positions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for p_id, p_data in data.items():
                        # Handle tp_levels that might be stored as list of dicts
                        self.positions[p_id] = ActivePosition(**p_data)
                    logger.info(f"📂 加载 {len(self.positions)} 个活跃持仓")
        except Exception as e:
            logger.warning(f"加载持仓失败: {e}")
        
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
                    logger.info(f"📂 加载 {len(self.history)} 条历史交易")
        except Exception as e:
            logger.warning(f"加载历史失败: {e}")
