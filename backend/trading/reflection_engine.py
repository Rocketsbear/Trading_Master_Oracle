"""
Reflection Engine — LLM 驱动的交易反思系统
每笔交易结束后自动分析，提取教训

功能:
1. 结构化 LLM 反思 (root_cause, red_flags, lessons, suggestions)
2. 历史教训喂入新反思 → 识别重复犯错
3. 盈利/亏损都反思，提取成功模式和失败模式
4. 持久化到 JSON
"""
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger


class ReflectionEngine:
    """
    交易反思引擎 — 每笔交易结束后用 LLM 分析
    """
    
    def __init__(self, llm_client=None, data_dir: str = None):
        self.llm = llm_client
        self.data_dir = data_dir or os.path.join(os.path.dirname(__file__), '../../data/reflections')
        self.reflections_file = os.path.join(self.data_dir, 'trade_reflections.json')
        self.summary_file = os.path.join(self.data_dir, 'strategy_summary.json')
        self.reflections: List[Dict] = []
        self._load()
        logger.info(f"🧠 ReflectionEngine 初始化: {len(self.reflections)} 条反思记录")
    
    async def reflect_on_trade(self, trade: Dict) -> Optional[Dict]:
        """
        对一笔已平仓交易进行反思分析
        
        trade: 从 position_history 中的完整交易记录
        """
        if not self.llm:
            logger.warning("⚠️ LLM 未配置，跳过反思")
            return None
        
        pnl = trade.get('realized_pnl', 0) or trade.get('pnl', 0)
        is_loss = pnl < 0
        
        # Build reflection prompt
        prompt = self._build_prompt(trade, is_loss)
        
        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.3,  # Analytical, not creative
                system_prompt="你是一位拥有10年经验的顶级加密货币合约交易员。你的任务是分析交易记录，找出根本原因和可执行的教训。请用中文回答，保持简洁专业。"
            )
            
            # Parse structured response
            reflection = self._parse_reflection(response, trade, pnl)
            
            # Save
            self.reflections.append(reflection)
            self._save()
            
            # Log
            emoji = "🔴" if is_loss else "🟢"
            logger.info(
                f"{emoji} 反思完成 [{trade.get('symbol')}] "
                f"PnL: {'+'if pnl>=0 else ''}${pnl:.2f} | "
                f"原因: {reflection.get('root_cause', 'N/A')[:50]}"
            )
            
            return reflection
            
        except Exception as e:
            logger.error(f"反思分析失败: {e}")
            # Still save basic info without LLM analysis
            basic = {
                "trade_id": trade.get('id', ''),
                "symbol": trade.get('symbol', ''),
                "side": trade.get('side', ''),
                "pnl": pnl,
                "is_loss": is_loss,
                "close_reason": trade.get('close_reason', ''),
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
            self.reflections.append(basic)
            self._save()
            return basic
    
    def _build_prompt(self, trade: Dict, is_loss: bool) -> str:
        """构建反思 prompt"""
        
        side_label = "做多" if trade.get('side') == 'buy' else "做空"
        pnl = trade.get('realized_pnl', 0) or trade.get('pnl', 0)
        
        # Parse duration
        opened = trade.get('opened_at', '')
        closed = trade.get('closed_at', '')
        duration_str = "未知"
        if opened and closed:
            try:
                t1 = datetime.fromisoformat(opened)
                t2 = datetime.fromisoformat(closed)
                mins = (t2 - t1).total_seconds() / 60
                duration_str = f"{mins:.0f}分钟" if mins < 60 else f"{mins/60:.1f}小时"
            except:
                pass
        
        # Indicator snapshot
        snap = trade.get('indicator_snapshot', {})
        snap_text = "无指标快照"
        if snap:
            parts = []
            if 'rsi' in snap: parts.append(f"RSI={snap['rsi']}")
            if 'adx' in snap: parts.append(f"ADX={snap['adx']}")
            if 'fng' in snap: parts.append(f"恐贪={snap['fng']}")
            if 'smc_structure' in snap: parts.append(f"SMC={snap['smc_structure']}")
            if 'trend_agreement' in snap: parts.append(f"趋势一致={snap['trend_agreement']}")
            if 'breakdown' in snap: parts.append(f"评分明细: {snap['breakdown']}")
            snap_text = " | ".join(parts)
        
        # Previous lessons (last 5)
        recent_lessons = self._get_recent_lessons(5)
        lessons_text = "无历史教训" if not recent_lessons else "\n".join(
            f"- [{l['symbol']}] PnL ${l['pnl']:+.2f}: {l.get('root_cause', 'N/A')}" 
            for l in recent_lessons
        )
        
        trade_type = "亏损" if is_loss else "盈利"
        
        prompt = f"""## {trade_type}交易分析

### 交易信息
- 方向: {side_label} {trade.get('symbol', '')}
- 入场: ${trade.get('entry_price', 0):,.2f} → 出场: ${trade.get('current_price', 0):,.2f}
- PnL: ${pnl:+.2f} ({trade.get('roe', 0):+.1f}%)
- 杠杆: {trade.get('leverage', 1)}x | 持仓时间: {duration_str}
- 平仓原因: {trade.get('close_reason', '未知')}
- AI评分: {trade.get('score', 50)}/100

### 开仓时市场指标
{snap_text}

### 持仓期间价格水位
- 最大浮盈: +${trade.get('max_profit', 0):.2f} (价格 ${trade.get('max_profit_price', 0):,.2f})
- 最大浮亏: -${trade.get('max_drawdown', 0):.2f} (价格 ${trade.get('max_drawdown_price', 0):,.2f})

### 历史教训
{lessons_text}

请按以下格式分析:

[ROOT_CAUSE]
(一句话总结根本原因)

[RED_FLAGS]
(开仓时有哪些应该注意但被忽略的信号，列举2-3个)

[LESSON]
(从此交易中学到的核心教训，一句话)

[SUGGESTION]
(对评分引擎或交易策略的具体改进建议，要可执行)

[PATTERN]
(这笔交易属于什么模式？如: 追涨杀跌/逆势/震荡中做单/TP太早/SL太紧等)
"""
        return prompt
    
    def _parse_reflection(self, response: str, trade: Dict, pnl: float) -> Dict:
        """解析 LLM 反思结果"""
        
        def extract(tag: str) -> str:
            pattern = rf'\[{tag}\]\s*\n?(.*?)(?=\[|$)'
            match = re.search(pattern, response, re.DOTALL)
            return match.group(1).strip() if match else ""
        
        return {
            "trade_id": trade.get('id', ''),
            "symbol": trade.get('symbol', ''),
            "side": trade.get('side', ''),
            "entry_price": trade.get('entry_price', 0),
            "close_price": trade.get('current_price', 0),
            "pnl": pnl,
            "roe": trade.get('roe', 0),
            "is_loss": pnl < 0,
            "close_reason": trade.get('close_reason', ''),
            "score": trade.get('score', 50),
            "leverage": trade.get('leverage', 1),
            "duration_mins": self._calc_duration(trade),
            "max_profit": trade.get('max_profit', 0),
            "max_drawdown": trade.get('max_drawdown', 0),
            "indicator_snapshot": trade.get('indicator_snapshot', {}),
            
            # LLM analysis
            "root_cause": extract("ROOT_CAUSE"),
            "red_flags": extract("RED_FLAGS"),
            "lesson": extract("LESSON"),
            "suggestion": extract("SUGGESTION"),
            "pattern": extract("PATTERN"),
            "full_analysis": response,
            
            "timestamp": datetime.now().isoformat(),
        }
    
    def _calc_duration(self, trade: Dict) -> float:
        """计算持仓时长（分钟）"""
        try:
            t1 = datetime.fromisoformat(trade.get('opened_at', ''))
            t2 = datetime.fromisoformat(trade.get('closed_at', ''))
            return round((t2 - t1).total_seconds() / 60, 1)
        except:
            return 0
    
    def _get_recent_lessons(self, n: int = 5) -> List[Dict]:
        """获取最近 N 条有教训的反思"""
        with_lessons = [r for r in self.reflections if r.get('root_cause')]
        return with_lessons[-n:]
    
    # ==========================================
    # 查询 & 统计
    # ==========================================
    
    def get_all(self, limit: int = 50) -> List[Dict]:
        """获取所有反思（不含 full_analysis 以节省带宽）"""
        result = []
        for r in self.reflections[-limit:]:
            compact = {k: v for k, v in r.items() if k != 'full_analysis'}
            result.append(compact)
        return result
    
    def get_loss_patterns(self) -> Dict:
        """统计亏损模式"""
        losses = [r for r in self.reflections if r.get('is_loss')]
        patterns = {}
        for r in losses:
            p = r.get('pattern', '未分类')
            if p:
                patterns[p] = patterns.get(p, 0) + 1
        return dict(sorted(patterns.items(), key=lambda x: -x[1]))
    
    def get_strategy_summary(self) -> Dict:
        """获取当前策略总结"""
        total = len(self.reflections)
        losses = [r for r in self.reflections if r.get('is_loss')]
        wins = [r for r in self.reflections if not r.get('is_loss')]
        
        recent = self.reflections[-10:]
        recent_lessons = [r.get('lesson', '') for r in recent if r.get('lesson')]
        recent_suggestions = [r.get('suggestion', '') for r in recent if r.get('suggestion')]
        
        return {
            "total_reflections": total,
            "loss_count": len(losses),
            "win_count": len(wins),
            "loss_patterns": self.get_loss_patterns(),
            "recent_lessons": recent_lessons[-5:],
            "recent_suggestions": recent_suggestions[-5:],
            "last_updated": self.reflections[-1].get('timestamp', '') if self.reflections else '',
        }
    
    # ==========================================
    # 持久化
    # ==========================================
    
    def _save(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self.reflections_file, 'w', encoding='utf-8') as f:
                json.dump(self.reflections[-200:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存反思记录失败: {e}")
    
    def _load(self):
        try:
            if os.path.exists(self.reflections_file):
                with open(self.reflections_file, 'r', encoding='utf-8') as f:
                    self.reflections = json.load(f)
        except Exception as e:
            logger.warning(f"加载反思记录失败: {e}")
