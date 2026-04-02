"""
Evolution Rules Engine — 从交易反思中提炼进化规则
软规则 + 信心衰减 → 影响评分引擎 Layer 7

功能:
1. 从反思记录中自动提取模式
2. 规则带信心值 (confidence)，随时间衰减
3. get_score_adjustment() 给评分引擎用
4. 每 5 笔反思自动重新汇总
"""
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger


# 预定义的进化规则模板 — LLM 提取结果会映射到这些条件
RULE_TEMPLATES = {
    "low_adx": {
        "name": "低ADX谨慎",
        "condition": "adx < 15",
        "check": lambda snap: snap.get('adx', 25) < 15,
        "base_adjustment": -5,
        "category": "market_regime",
    },
    "extreme_greed_long": {
        "name": "极度贪婪做多惩罚",
        "condition": "fng > 75 && side == buy",
        "check": lambda snap: snap.get('fng', 50) > 75 and snap.get('side') == 'buy',
        "base_adjustment": -5,
        "category": "sentiment_trap",
    },
    "extreme_fear_short": {
        "name": "极度恐惧做空惩罚",
        "condition": "fng < 25 && side == sell",
        "check": lambda snap: snap.get('fng', 50) < 25 and snap.get('side') == 'sell',
        "base_adjustment": -5,
        "category": "sentiment_trap",
    },
    "trend_disagree": {
        "name": "趋势不一致警告",
        "condition": "trend_agreement == False",
        "check": lambda snap: snap.get('trend_agreement') == False,
        "base_adjustment": -3,
        "category": "structure",
    },
    "choch_chase": {
        "name": "CHoCH后追涨",
        "condition": "smc has CHoCH && chasing",
        "check": lambda snap: 'CHoCH' in str(snap.get('smc_signals', '')),
        "base_adjustment": -3,
        "category": "structure",
    },
    "low_score_trade": {
        "name": "低评分仍下单",
        "condition": "score < 60",
        "check": lambda snap: snap.get('score', 50) < 60,
        "base_adjustment": -5,
        "category": "discipline",
    },
    "high_leverage_volatile": {
        "name": "高波动高杠杆",
        "condition": "atr_pct > 3 && leverage > 3",
        "check": lambda snap: snap.get('atr_pct', 1) > 3 and snap.get('leverage', 1) > 3,
        "base_adjustment": -4,
        "category": "position",
    },
}


class EvolutionRule:
    """单个进化规则"""
    
    def __init__(self, data: Dict):
        self.id = data.get('id', '')
        self.name = data.get('name', '')
        self.condition = data.get('condition', '')
        self.category = data.get('category', 'other')
        self.base_adjustment = data.get('base_adjustment', 0)
        self.confidence = data.get('confidence', 0.5)
        self.source_trades = data.get('source_trades', [])
        self.times_applied = data.get('times_applied', 0)
        self.times_validated = data.get('times_validated', 0)  # 规则应用后确实有效的次数
        self.status = data.get('status', 'active')  # active / inactive
        self.created_at = data.get('created_at', datetime.now().isoformat())
        self.last_applied = data.get('last_applied', '')
        self.last_decay = data.get('last_decay', datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "condition": self.condition,
            "category": self.category,
            "base_adjustment": self.base_adjustment,
            "confidence": round(self.confidence, 3),
            "source_trades": self.source_trades[-10:],
            "times_applied": self.times_applied,
            "times_validated": self.times_validated,
            "status": self.status,
            "created_at": self.created_at,
            "last_applied": self.last_applied,
            "last_decay": self.last_decay,
        }
    
    @property
    def effective_adjustment(self) -> float:
        """实际调整值 = 基础值 × 信心"""
        return round(self.base_adjustment * self.confidence, 1)


class EvolutionEngine:
    """
    进化引擎 — 从反思中提取规则，应用到评分
    """
    
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.join(os.path.dirname(__file__), '../../data/reflections')
        self.rules_file = os.path.join(self.data_dir, 'evolution_rules.json')
        self.rules: Dict[str, EvolutionRule] = {}
        self._load()
        self._apply_decay()
        logger.info(f"⚡ EvolutionEngine 初始化: {len(self.rules)} 条进化规则")
    
    # ==========================================
    # 核心: 获取评分调整 (Layer 7)
    # ==========================================
    
    def get_score_adjustment(self, indicators: Dict, side: str = None, score: int = 50) -> Dict:
        """
        根据当前指标返回评分调整
        
        indicators: {rsi, adx, fng, smc_structure, smc_signals, trend_agreement, atr_pct, ...}
        Returns: {adjustment: float, reasons: list, rules_applied: list}
        """
        total_adj = 0.0
        reasons = []
        rules_applied = []
        
        # Merge side and score into indicators for rule checking
        check_data = {**indicators, 'side': side, 'score': score}
        
        for rule_id, rule in self.rules.items():
            if rule.status != 'active' or rule.confidence < 0.3:
                continue
            
            # Check if this rule's condition matches
            try:
                template = RULE_TEMPLATES.get(rule_id)
                if template and template['check'](check_data):
                    adj = rule.effective_adjustment
                    total_adj += adj
                    reasons.append(f"{rule.name}({adj:+.1f}, 信心{rule.confidence:.0%})")
                    rules_applied.append(rule_id)
                    
                    # Track usage
                    rule.times_applied += 1
                    rule.last_applied = datetime.now().isoformat()
            except Exception:
                continue
        
        # Cap total adjustment at ±5
        total_adj = max(-5, min(5, total_adj))
        
        if rules_applied:
            self._save()
        
        return {
            "adjustment": round(total_adj, 1),
            "reasons": reasons,
            "rules_applied": rules_applied,
        }
    
    # ==========================================
    # 从反思中提取/更新规则
    # ==========================================
    
    def update_from_reflection(self, reflection: Dict):
        """
        从一条反思记录中更新进化规则
        
        1. 根据反思的 pattern 和 indicator_snapshot 匹配预定义模板
        2. 亏损 → 增加对应规则的信心
        3. 盈利 → 如果命中了规则但还是赚钱，降低规则信心
        """
        trade_id = reflection.get('trade_id', '')
        is_loss = reflection.get('is_loss', False)
        snap = reflection.get('indicator_snapshot', {})
        snap['side'] = reflection.get('side', '')
        snap['score'] = reflection.get('score', 50)
        snap['leverage'] = reflection.get('leverage', 1)
        
        for rule_id, template in RULE_TEMPLATES.items():
            try:
                if template['check'](snap):
                    if rule_id not in self.rules:
                        # Create new rule
                        self.rules[rule_id] = EvolutionRule({
                            'id': rule_id,
                            'name': template['name'],
                            'condition': template['condition'],
                            'category': template['category'],
                            'base_adjustment': template['base_adjustment'],
                            'confidence': 0.3,  # Start low
                            'source_trades': [trade_id],
                        })
                        logger.info(f"📝 新规则: {template['name']} (初始信心 30%)")
                    
                    rule = self.rules[rule_id]
                    
                    if is_loss:
                        # Loss validates the rule → increase confidence
                        rule.confidence = min(0.95, rule.confidence + 0.1)
                        rule.times_validated += 1
                        if trade_id not in rule.source_trades:
                            rule.source_trades.append(trade_id)
                        logger.info(f"📈 规则 '{rule.name}' 被验证 → 信心 {rule.confidence:.0%}")
                    else:
                        # Win despite rule trigger → decrease confidence slightly
                        rule.confidence = max(0.1, rule.confidence - 0.05)
                        logger.info(f"📉 规则 '{rule.name}' 被反驳 → 信心 {rule.confidence:.0%}")
            except Exception:
                continue
        
        self._save()
    
    # ==========================================
    # 信心衰减
    # ==========================================
    
    def _apply_decay(self):
        """
        信心衰减 — 每周 -10%
        市场在变，旧规则应该逐渐失效
        """
        now = datetime.now()
        
        for rule in self.rules.values():
            try:
                last = datetime.fromisoformat(rule.last_decay)
                days_since = (now - last).days
                
                if days_since >= 7:
                    weeks = days_since // 7
                    old_conf = rule.confidence
                    rule.confidence *= (0.9 ** weeks)
                    rule.last_decay = now.isoformat()
                    
                    if rule.confidence < 0.3 and rule.status == 'active':
                        rule.status = 'inactive'
                        logger.info(f"💤 规则 '{rule.name}' 信心过低 ({rule.confidence:.0%})，已停用")
                    elif old_conf != rule.confidence:
                        logger.debug(f"⏬ 规则 '{rule.name}' 衰减: {old_conf:.0%} → {rule.confidence:.0%}")
            except Exception:
                continue
        
        self._save()
    
    # ==========================================
    # 查询
    # ==========================================
    
    def get_all_rules(self) -> List[Dict]:
        """获取所有规则"""
        return [r.to_dict() for r in self.rules.values()]
    
    def get_active_rules(self) -> List[Dict]:
        """获取活跃规则"""
        return [r.to_dict() for r in self.rules.values() if r.status == 'active']
    
    def get_stats(self) -> Dict:
        """获取规则统计"""
        active = [r for r in self.rules.values() if r.status == 'active']
        return {
            "total_rules": len(self.rules),
            "active_rules": len(active),
            "avg_confidence": round(sum(r.confidence for r in active) / len(active), 2) if active else 0,
            "categories": list(set(r.category for r in self.rules.values())),
        }
    
    # ==========================================
    # 持久化
    # ==========================================
    
    def _save(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            data = {rid: r.to_dict() for rid, r in self.rules.items()}
            with open(self.rules_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存规则失败: {e}")
    
    def _load(self):
        try:
            if os.path.exists(self.rules_file):
                with open(self.rules_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for rid, rdata in data.items():
                        self.rules[rid] = EvolutionRule(rdata)
                    logger.info(f"📂 加载 {len(self.rules)} 条进化规则")
        except Exception as e:
            logger.warning(f"加载规则失败: {e}")
