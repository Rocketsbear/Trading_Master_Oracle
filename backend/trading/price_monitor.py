"""
Price Monitor — 后端 24/7 实时价格监控 + 自动 TP/SL 执行
独立 asyncio 后台任务，每 3 秒检查一次

功能:
1. 从 Binance 拉实时价格
2. 检查所有活跃持仓的 TP/SL/Trailing/清算
3. 触发自动平仓
4. 通过 WebSocket 推送事件到前端
"""
import asyncio
import httpx
from datetime import datetime
from typing import Optional, Callable
from loguru import logger


class PriceMonitor:
    """
    后台价格监控服务
    
    Usage:
        monitor = PriceMonitor(position_manager, risk_manager, ws_broadcast)
        asyncio.create_task(monitor.start())
    """
    
    def __init__(self, position_manager, risk_manager=None, ws_broadcast=None, on_close=None):
        self.pm = position_manager
        self.rm = risk_manager
        self.ws_broadcast = ws_broadcast  # async func to broadcast via WebSocket
        self.on_close = on_close          # async callback for reflection on close
        self.running = False
        self.check_interval = 3  # seconds
        self.price_cache = {}    # symbol -> price
        self._error_count = 0
    
    async def start(self):
        """启动监控循环"""
        self.running = True
        logger.info("🔍 PriceMonitor 启动 — 每3秒检查 TP/SL/Trailing")
        
        while self.running:
            try:
                await self._check_cycle()
                self._error_count = 0
            except Exception as e:
                self._error_count += 1
                if self._error_count <= 3:
                    logger.warning(f"⚠️ PriceMonitor 错误 ({self._error_count}/3): {e}")
                elif self._error_count == 4:
                    logger.error(f"🔴 PriceMonitor 连续出错，降低检查频率")
            
            # Adaptive interval: slow down if errors persist
            interval = self.check_interval if self._error_count <= 3 else 10
            await asyncio.sleep(interval)
    
    def stop(self):
        """停止监控"""
        self.running = False
        logger.info("🛑 PriceMonitor 停止")
    
    async def _check_cycle(self):
        """单次检查循环"""
        symbols = self.pm.get_symbols()
        if not symbols:
            return  # No positions to monitor
        
        # Fetch prices for all symbols in one batch
        prices = await self._fetch_prices(symbols)
        
        if not prices:
            return
        
        # Update each symbol and check TP/SL
        all_events = []
        for symbol, price in prices.items():
            self.price_cache[symbol] = price
            events = self.pm.update_price(symbol, price)
            all_events.extend(events)
        
        # Process events
        for event in all_events:
            await self._handle_event(event)
        
        # Check time-based stop (timeout)
        now = datetime.now()
        for pos_id, pos in list(self.pm.positions.items()):
            if pos.max_hold_hours <= 0 or pos.status != 'open':
                continue
            try:
                opened = datetime.fromisoformat(pos.opened_at)
                held_hours = (now - opened).total_seconds() / 3600
                if held_hours >= pos.max_hold_hours:
                    # Only auto-close if NOT clearly winning (ROE < +0.5%)
                    if pos.roe < 0.5:
                        price = prices.get(pos.symbol, pos.current_price)
                        result = self.pm.close_position(pos_id, close_price=price, reason="timeout")
                        if result:
                            logger.info(f"⏰ 超时平仓 [{pos.symbol}] 持仓{held_hours:.1f}h > {pos.max_hold_hours}h | PnL ${result['pnl']:.2f}")
                            await self._handle_event(result)
            except Exception:
                pass
        
        # Broadcast position updates to frontend via WebSocket
        if self.ws_broadcast and symbols:
            positions = self.pm.get_all_positions()
            try:
                await self.ws_broadcast({
                    "type": "positions_update",
                    "positions": positions,
                    "prices": self.price_cache,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass  # WebSocket might not be connected
    
    async def _fetch_prices(self, symbols: list) -> dict:
        """从 OKX 优先，Binance 兜底 批量获取实时价格"""
        from backend.main import _exchange_data
        try:
            prices = await _exchange_data.get_prices_batch(symbols)
            return prices or {}
        except Exception as e:
            logger.warning(f"价格获取失败: {e}")
            return {}
    
    async def _handle_event(self, event: dict):
        """处理平仓事件"""
        reason_labels = {
            "sl": "🛑 止损触发",
            "trailing_sl": "🔄 移动止损触发",
            "tp1": "🎯 止盈1 (30%)",
            "tp2": "🎯 止盈2 (40%)",
            "tp3": "🎯 止盈3 (30%)",
            "liq_protect": "⚠️ 清算保护",
            "timeout": "⏰ 超时平仓",
            "manual": "✋ 手动平仓",
        }
        
        reason = event.get("reason", "unknown")
        label = reason_labels.get(reason, f"📊 {reason}")
        pnl = event.get("pnl", 0)
        symbol = event.get("symbol", "")
        
        log_msg = (
            f"{label} | {symbol} "
            f"@ ${event.get('close_price', 0):,.2f} "
            f"| PnL: {'+'if pnl>=0 else ''}${pnl:.2f} "
            f"| 剩余: {event.get('remaining_amount', 0):.6f}"
        )
        logger.info(log_msg)
        
        # Record PnL in risk manager
        if self.rm and event.get("type") == "close":
            self.rm.record_trade_result(pnl, event.get("position_id"))
        
        # Trigger reflection on full close
        if self.on_close and event.get("remaining_amount", 1) <= 0:
            try:
                await self.on_close(event)
            except Exception as e:
                logger.warning(f"反思回调失败: {e}")
        
        # Broadcast event to frontend
        if self.ws_broadcast:
            try:
                await self.ws_broadcast({
                    "type": "trade_event",
                    "event": event,
                    "label": label,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass
    
    def get_price(self, symbol: str) -> float:
        """获取缓存的最新价格"""
        return self.price_cache.get(symbol, 0)
