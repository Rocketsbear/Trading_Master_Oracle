"""
Backtester — 回测框架
用历史K线回测评分引擎，验证策略效果

功能:
1. 从 Binance 加载历史 K线
2. 逐根 K线模拟评分 + 开仓/平仓
3. 统计: PnL, 胜率, 最大回撤, Sharpe, 盈亏比
"""
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger


class BacktestResult:
    """回测结果"""
    
    def __init__(self):
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []
        self.initial_balance: float = 10000
        self.final_balance: float = 10000
    
    def to_dict(self) -> Dict:
        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        total_pnl = sum(t['pnl'] for t in self.trades)
        
        max_dd = 0
        peak = self.initial_balance
        for eq in self.equity_curve:
            peak = max(peak, eq)
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)
        
        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t['pnl'] for t in losses) / len(losses)) if losses else 1
        
        # Sharpe (simplified daily)
        if len(self.equity_curve) >= 2:
            returns = [(self.equity_curve[i] - self.equity_curve[i-1]) / self.equity_curve[i-1] 
                       for i in range(1, len(self.equity_curve))]
            avg_ret = sum(returns) / len(returns) if returns else 0
            std_ret = (sum((r - avg_ret)**2 for r in returns) / len(returns)) ** 0.5 if returns else 1
            sharpe = round(avg_ret / std_ret * (252 ** 0.5), 2) if std_ret > 0 else 0
        else:
            sharpe = 0
        
        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(self.trades) * 100, 1) if self.trades else 0,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / self.initial_balance * 100, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)), 2) if losses and sum(t['pnl'] for t in losses) != 0 else 999,
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": sharpe,
            "rr_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
            "initial_balance": self.initial_balance,
            "final_balance": round(self.final_balance, 2),
            "trades": self.trades[-50:],  # Last 50 trades
            "equity_curve": self.equity_curve[-200:],  # Sampled
        }


class Backtester:
    """
    回测引擎
    
    Usage:
        bt = Backtester()
        result = await bt.run("BTCUSDT", days=30, score_threshold=65)
    """
    
    def __init__(self, initial_balance: float = 10000):
        self.initial_balance = initial_balance
    
    async def fetch_klines(self, symbol: str, interval: str = "1h", days: int = 30) -> List:
        """从 Binance Futures 获取历史 K线"""
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        
        all_klines = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            current = start_time
            while current < end_time:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={
                        "symbol": symbol, "interval": interval,
                        "startTime": current, "limit": 1000,
                    }
                )
                if resp.status_code != 200:
                    break
                klines = resp.json()
                if not klines:
                    break
                all_klines.extend(klines)
                current = int(klines[-1][0]) + 1
                await asyncio.sleep(0.2)  # Rate limit
        
        return all_klines
    
    def _calc_indicators(self, closes: List[float], highs: List[float], 
                          lows: List[float], volumes: List[float]) -> Dict:
        """计算技术指标"""
        if len(closes) < 30:
            return {}
        
        current = closes[-1]
        ma7 = sum(closes[-7:]) / 7
        ma25 = sum(closes[-25:]) / 25
        
        # RSI
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-14:]]
        loss_vals = [-d if d < 0 else 0 for d in deltas[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(loss_vals) / 14
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = round(100 - (100 / (1 + rs)), 1)
        
        # ATR
        trs = []
        for i in range(-14, 0):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            trs.append(tr)
        atr = sum(trs) / len(trs) if trs else current * 0.01
        
        # Volume ratio
        vol_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
        vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 1
        
        # Changes
        change_1h = round((current - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else 0
        change_4h = round((current - closes[-5]) / closes[-5] * 100, 2) if len(closes) >= 5 else 0
        
        # Simple score
        score = 50
        if current > ma7: score += 5
        if current > ma25: score += 5
        if ma7 > ma25: score += 5
        if rsi < 30: score += 10
        elif rsi > 70: score -= 10
        if vol_ratio > 1.5: score += 5
        if change_4h > 0: score += 3
        
        return {
            "price": current, "score": min(100, max(0, score)),
            "rsi": rsi, "ma7": ma7, "ma25": ma25, "atr": atr,
            "vol_ratio": vol_ratio, "change_1h": change_1h, "change_4h": change_4h,
        }
    
    async def run(self, symbol: str = "BTCUSDT", interval: str = "1h",
                  days: int = 30, score_threshold: int = 65,
                  sl_atr_mult: float = 2.0, tp_atr_mult: float = 3.0,
                  leverage: int = 3, risk_pct: float = 2.0) -> Dict:
        """
        运行回测
        
        Args:
            symbol: 交易对
            days: 回测天数
            score_threshold: 开仓评分阈值
            sl_atr_mult: SL = ATR × 倍数
            tp_atr_mult: TP = ATR × 倍数
            leverage: 杠杆
            risk_pct: 每笔风险占比 (%)
        """
        logger.info(f"🔬 开始回测 {symbol} {interval} 最近{days}天 (阈值={score_threshold})")
        
        klines = await self.fetch_klines(symbol, interval, days)
        if len(klines) < 100:
            return {"error": f"K线数据不足: {len(klines)} 条"}
        
        result = BacktestResult()
        result.initial_balance = self.initial_balance
        balance = self.initial_balance
        
        # State
        position = None  # {side, entry, amount, sl, tp, opened_idx}
        
        closes = []
        highs = []
        lows = []
        volumes = []
        
        for idx, k in enumerate(klines):
            close = float(k[4])
            high = float(k[2])
            low = float(k[3])
            vol = float(k[5])
            ts = datetime.fromtimestamp(int(k[0]) / 1000).isoformat()
            
            closes.append(close)
            highs.append(high)
            lows.append(low)
            volumes.append(vol)
            
            if len(closes) < 30:
                result.equity_curve.append(balance)
                continue
            
            # Check existing position
            if position:
                # Check SL
                sl_hit = (position['side'] == 'buy' and low <= position['sl']) or \
                         (position['side'] == 'sell' and high >= position['sl'])
                tp_hit = (position['side'] == 'buy' and high >= position['tp']) or \
                         (position['side'] == 'sell' and low <= position['tp'])
                
                if sl_hit:
                    # SL hit
                    exit_price = position['sl']
                    if position['side'] == 'buy':
                        pnl = (exit_price - position['entry']) * position['amount']
                    else:
                        pnl = (position['entry'] - exit_price) * position['amount']
                    balance += pnl
                    result.trades.append({
                        "side": position['side'], "entry": position['entry'],
                        "exit": exit_price, "pnl": round(pnl, 2),
                        "reason": "sl", "bars_held": idx - position['opened_idx'],
                        "timestamp": ts,
                    })
                    position = None
                elif tp_hit:
                    exit_price = position['tp']
                    if position['side'] == 'buy':
                        pnl = (exit_price - position['entry']) * position['amount']
                    else:
                        pnl = (position['entry'] - exit_price) * position['amount']
                    balance += pnl
                    result.trades.append({
                        "side": position['side'], "entry": position['entry'],
                        "exit": exit_price, "pnl": round(pnl, 2),
                        "reason": "tp", "bars_held": idx - position['opened_idx'],
                        "timestamp": ts,
                    })
                    position = None
            
            # Try open new position (no existing position)
            if position is None and idx < len(klines) - 5:
                ind = self._calc_indicators(closes, highs, lows, volumes)
                if not ind:
                    result.equity_curve.append(balance)
                    continue
                
                score = ind['score']
                atr = ind['atr']
                
                if score >= score_threshold:
                    # LONG
                    sl = close - atr * sl_atr_mult
                    tp = close + atr * tp_atr_mult
                    risk_amount = balance * (risk_pct / 100)
                    sl_dist = abs(close - sl)
                    amount = risk_amount / sl_dist if sl_dist > 0 else 0
                    position = {
                        "side": "buy", "entry": close, "amount": amount,
                        "sl": sl, "tp": tp, "opened_idx": idx,
                    }
                elif score <= (100 - score_threshold):
                    # SHORT
                    sl = close + atr * sl_atr_mult
                    tp = close - atr * tp_atr_mult
                    risk_amount = balance * (risk_pct / 100)
                    sl_dist = abs(sl - close)
                    amount = risk_amount / sl_dist if sl_dist > 0 else 0
                    position = {
                        "side": "sell", "entry": close, "amount": amount,
                        "sl": sl, "tp": tp, "opened_idx": idx,
                    }
            
            result.equity_curve.append(round(balance, 2))
        
        # Close any remaining position at last price
        if position:
            exit_price = closes[-1]
            if position['side'] == 'buy':
                pnl = (exit_price - position['entry']) * position['amount']
            else:
                pnl = (position['entry'] - exit_price) * position['amount']
            balance += pnl
            result.trades.append({
                "side": position['side'], "entry": position['entry'],
                "exit": exit_price, "pnl": round(pnl, 2),
                "reason": "end", "bars_held": len(klines) - position['opened_idx'],
                "timestamp": datetime.now().isoformat(),
            })
        
        result.final_balance = balance
        result.equity_curve.append(round(balance, 2))
        
        summary = result.to_dict()
        logger.info(
            f"🔬 回测完成 {symbol}: {summary['total_trades']}笔交易 "
            f"| 胜率 {summary['win_rate']}% | PnL ${summary['total_pnl']:+.2f} "
            f"| 最大回撤 {summary['max_drawdown_pct']}% | Sharpe {summary['sharpe_ratio']}"
        )
        
        return summary
