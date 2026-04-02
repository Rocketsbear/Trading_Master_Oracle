"""
玄学分析引擎
整合八字、紫微、占星、塔罗数据
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger

from ..data_sources.metaphysical.metaphysical import MetaphysicalDataSource


class MetaphysicalAnalysisEngine:
    """玄学分析引擎"""
    
    def __init__(self, mcp_path: str = None):
        """
        初始化玄学分析引擎
        
        Args:
            mcp_path: MCP 路径
        """
        self.metaphysical = MetaphysicalDataSource(mcp_path)
        logger.info("玄学分析引擎初始化完成")
    
    async def analyze(
        self,
        symbol: str = "BTC",
        birth_date: Optional[str] = None,
        birth_time: Optional[str] = None,
        birth_place: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行完整的玄学分析
        
        Args:
            symbol: 币种
            birth_date: 出生日期（可选，用于个人运势）
            birth_time: 出生时间
            birth_place: 出生地点
            
        Returns:
            完整的玄学分析报告
        """
        try:
            logger.info(f"开始玄学分析: {symbol}")
            
            # 获取综合玄学数据
            data = await self.metaphysical.get_comprehensive_metaphysical_analysis(
                birth_date, birth_time, birth_place
            )
            
            # 分析各个维度
            bazi_analysis = self._analyze_bazi(data.get('bazi')) if data.get('bazi') else None
            ziwei_analysis = self._analyze_ziwei(data.get('ziwei')) if data.get('ziwei') else None
            astrology_analysis = self._analyze_astrology(data.get('astrology')) if data.get('astrology') else None
            tarot_analysis = self._analyze_tarot(data['tarot'])
            
            # 综合评分
            score = data['overall_score']
            
            # 生成建议
            recommendation = self._generate_recommendation(
                score,
                bazi_analysis,
                tarot_analysis,
                data['overall_advice']
            )
            
            report = {
                "symbol": symbol,
                "score": score,
                "bazi_analysis": bazi_analysis,
                "ziwei_analysis": ziwei_analysis,
                "astrology_analysis": astrology_analysis,
                "tarot_analysis": tarot_analysis,
                "recommendation": recommendation,
                "timestamp": datetime.now(),
                "data_source": "metaphysical_mcps",
                "note": "⚠️ 玄学分析仅供娱乐参考，不构成投资建议"
            }
            
            logger.info(f"玄学分析完成，评分: {score}")
            return report
            
        except Exception as e:
            logger.error(f"玄学分析失败: {e}")
            raise
    
    def _analyze_bazi(self, bazi: Dict) -> Dict[str, Any]:
        """分析八字"""
        if not bazi:
            return None
        
        score = bazi['score']
        trading_advice = bazi['trading_advice']
        
        status = ""
        details = []
        
        if score >= 70:
            status = "八字大吉"
            details.append(f"财星旺，日主强，{trading_advice['caution']}")
        elif score >= 50:
            status = "八字平吉"
            details.append(trading_advice['caution'])
        else:
            status = "八字不利"
            details.append(f"日主弱，{trading_advice['caution']}")
        
        # 吉时凶时
        if trading_advice['best_time']:
            details.append(f"吉时: {trading_advice['best_time']}")
        if trading_advice['avoid_time']:
            details.append(f"凶时: {trading_advice['avoid_time']}")
        
        return {
            "score": score,
            "status": status,
            "suitable_for_trading": trading_advice['suitable'],
            "best_time": trading_advice['best_time'],
            "avoid_time": trading_advice['avoid_time'],
            "details": " | ".join(details)
        }
    
    def _analyze_ziwei(self, ziwei: Dict) -> Dict[str, Any]:
        """分析紫微斗数"""
        if not ziwei:
            return None
        
        score = ziwei['score']
        trading_advice = ziwei['trading_advice']
        
        status = ""
        details = []
        
        if score >= 70:
            status = "紫微大吉"
            details.append("命宫、财帛宫、事业宫三吉")
        elif score >= 50:
            status = "紫微平吉"
            details.append(trading_advice['caution'])
        else:
            status = "紫微不利"
            details.append(trading_advice['caution'])
        
        return {
            "score": score,
            "status": status,
            "suitable_for_trading": trading_advice['suitable'],
            "strategy": trading_advice['strategy'],
            "details": " | ".join(details)
        }
    
    def _analyze_astrology(self, astrology: Dict) -> Dict[str, Any]:
        """分析占星"""
        if not astrology:
            return None
        
        score = astrology['score']
        trading_advice = astrology['trading_advice']
        
        status = ""
        details = []
        
        # 水星逆行检查
        if 'mercury' in astrology['planetary_positions']:
            mercury = astrology['planetary_positions']['mercury']
            if mercury == '逆行中':
                status = "水星逆行"
                details.append("⚠️ 水星逆行，容易判断失误")
            else:
                status = "星象正常"
        
        details.append(trading_advice['caution'])
        
        return {
            "score": score,
            "status": status,
            "suitable_for_trading": trading_advice['suitable'],
            "recommendation": trading_advice['recommendation'],
            "details": " | ".join(details)
        }
    
    def _analyze_tarot(self, tarot: Dict) -> Dict[str, Any]:
        """分析塔罗牌"""
        card = tarot['card']
        interpretation = tarot['interpretation']
        advice = tarot['advice']
        
        status = f"{card['name']} ({card['position']})"
        details = [card['meaning'], interpretation, advice]
        
        return {
            "score": tarot['score'],
            "status": status,
            "card_name": card['name'],
            "card_position": card['position'],
            "meaning": card['meaning'],
            "interpretation": interpretation,
            "advice": advice,
            "details": " | ".join(details)
        }
    
    def _generate_recommendation(
        self,
        score: int,
        bazi: Optional[Dict],
        tarot: Dict,
        overall_advice: str
    ) -> Dict[str, Any]:
        """生成玄学建议"""
        if score >= 70:
            direction = "玄学大吉"
            confidence = "高"
            reason = overall_advice
            action = "可以小仓试单，但需谨慎，见好就收"
        elif score >= 55:
            direction = "玄学偏吉"
            confidence = "中"
            reason = overall_advice
            action = "可以观望或小仓操作"
        elif score <= 30:
            direction = "玄学大凶"
            confidence = "高"
            reason = overall_advice
            action = "建议休息，不宜交易"
        elif score <= 45:
            direction = "玄学偏凶"
            confidence = "中"
            reason = overall_advice
            action = "谨慎观望，减少交易"
        else:
            direction = "玄学中性"
            confidence = "低"
            reason = overall_advice
            action = "可以正常交易，但不宜重仓"
        
        # 特殊提示
        warnings = []
        if bazi and not bazi['suitable_for_trading']:
            warnings.append("八字不利交易")
        if tarot['card_name'] in ['塔', '恶魔', '倒吊人']:
            warnings.append(f"塔罗牌 {tarot['card_name']} 需谨慎")
        
        return {
            "direction": direction,
            "confidence": confidence,
            "reason": reason,
            "action": action,
            "warnings": warnings if warnings else None,
            "disclaimer": "⚠️ 玄学分析仅供娱乐，不构成投资建议"
        }


# 测试代码
if __name__ == "__main__":
    async def test():
        engine = MetaphysicalAnalysisEngine()
        
        # 测试通用运势（不提供生辰）
        report = await engine.analyze("BTC")
        
        print(f"玄学分析报告:")
        print(f"  评分: {report['score']}/100")
        print(f"  塔罗牌: {report['tarot_analysis']['status']}")
        print(f"  建议: {report['recommendation']['direction']}")
        print(f"  行动: {report['recommendation']['action']}")
        if report['recommendation']['warnings']:
            print(f"  警告: {', '.join(report['recommendation']['warnings'])}")
    
    asyncio.run(test())
