"""
宏观经济分析引擎
整合宏观经济数据，生成宏观分析报告
"""
import asyncio
from typing import Dict, Any
from datetime import datetime
from loguru import logger

from ..data_sources.macro.fred import FREDDataSource


class MacroAnalysisEngine:
    """宏观经济分析引擎"""
    
    def __init__(self, fred_api_key: str):
        """
        初始化宏观分析引擎
        
        Args:
            fred_api_key: FRED API Key
        """
        self.fred = FREDDataSource(fred_api_key)
        logger.info("宏观分析引擎初始化完成")
    
    async def analyze(self) -> Dict[str, Any]:
        """
        执行完整的宏观分析
        
        Returns:
            完整的宏观分析报告
        """
        try:
            logger.info("开始宏观分析")
            
            # 获取综合宏观数据
            data = await self.fred.get_comprehensive_macro_data()
            
            # 分析各个维度
            monetary_analysis = self._analyze_monetary_policy(data)
            inflation_analysis = self._analyze_inflation(data)
            growth_analysis = self._analyze_economic_growth(data)
            market_analysis = self._analyze_market_conditions(data)
            cycle_analysis = self._analyze_economic_cycle(data)
            
            # 综合评分
            score = self._calculate_macro_score(
                monetary_analysis,
                inflation_analysis,
                growth_analysis,
                market_analysis,
                cycle_analysis
            )
            
            # 生成建议
            recommendation = self._generate_recommendation(
                score,
                monetary_analysis,
                inflation_analysis,
                cycle_analysis
            )
            
            report = {
                "score": score,
                "monetary_policy": monetary_analysis,
                "inflation": inflation_analysis,
                "economic_growth": growth_analysis,
                "market_conditions": market_analysis,
                "economic_cycle": cycle_analysis,
                "recommendation": recommendation,
                "timestamp": datetime.now(),
                "data_source": "fred_api"
            }
            
            logger.info(f"宏观分析完成，评分: {score}")
            return report
            
        except Exception as e:
            logger.error(f"宏观分析失败: {e}")
            raise
    
    def _analyze_monetary_policy(self, data: Dict) -> Dict[str, Any]:
        """分析货币政策"""
        fed_rate = data['fed_funds_rate']['value']
        m2_growth = data['m2_money_supply']['change_yoy']
        
        score = 0
        stance = ""
        details = []
        
        # 利率分析
        if fed_rate < 2.0:
            score += 15
            stance = "极度宽松"
            details.append(f"联邦基金利率 {fed_rate:.2f}%，超低利率环境")
        elif fed_rate < 3.0:
            score += 10
            stance = "宽松"
            details.append(f"联邦基金利率 {fed_rate:.2f}%，低利率环境")
        elif fed_rate > 5.0:
            score -= 15
            stance = "紧缩"
            details.append(f"联邦基金利率 {fed_rate:.2f}%，高利率抑制风险资产")
        else:
            stance = "中性"
            details.append(f"联邦基金利率 {fed_rate:.2f}%")
        
        # M2 增长分析
        if m2_growth > 10:
            score += 10
            details.append(f"M2 增长 +{m2_growth:.1f}%，流动性充裕")
        elif m2_growth < 0:
            score -= 10
            details.append(f"M2 增长 {m2_growth:.1f}%，流动性收紧")
        else:
            details.append(f"M2 增长 {m2_growth:.1f}%")
        
        return {
            "score": score,
            "stance": stance,
            "fed_rate": fed_rate,
            "m2_growth": m2_growth,
            "details": " | ".join(details)
        }
    
    def _analyze_inflation(self, data: Dict) -> Dict[str, Any]:
        """分析通胀"""
        cpi = data['cpi']['change_yoy']
        pce = data['pce']['change_yoy']
        
        score = 0
        status = ""
        details = []
        
        # CPI 分析
        if cpi > 5.0:
            score -= 15
            status = "高通胀"
            details.append(f"CPI {cpi:.1f}%，高通胀压制风险资产")
        elif cpi > 3.0:
            score -= 5
            status = "温和通胀"
            details.append(f"CPI {cpi:.1f}%，通胀略高")
        elif cpi < 1.0:
            score += 5
            status = "低通胀"
            details.append(f"CPI {cpi:.1f}%，通胀受控")
        else:
            status = "正常通胀"
            details.append(f"CPI {cpi:.1f}%")
        
        # PCE 分析
        if pce > 4.0:
            score -= 5
            details.append(f"PCE {pce:.1f}%，核心通胀偏高")
        elif pce < 2.0:
            score += 5
            details.append(f"PCE {pce:.1f}%，核心通胀温和")
        
        return {
            "score": score,
            "status": status,
            "cpi": cpi,
            "pce": pce,
            "details": " | ".join(details)
        }
    
    def _analyze_economic_growth(self, data: Dict) -> Dict[str, Any]:
        """分析经济增长"""
        gdp_growth = data['gdp']['change_yoy']
        unemployment = data['unemployment_rate']['value']
        
        score = 0
        status = ""
        details = []
        
        # GDP 增长分析
        if gdp_growth > 3.0:
            score += 10
            status = "强劲增长"
            details.append(f"GDP 增长 {gdp_growth:.1f}%，经济强劲")
        elif gdp_growth > 2.0:
            score += 5
            status = "温和增长"
            details.append(f"GDP 增长 {gdp_growth:.1f}%")
        elif gdp_growth < 0:
            score -= 10
            status = "衰退"
            details.append(f"GDP 增长 {gdp_growth:.1f}%，经济衰退")
        else:
            status = "缓慢增长"
            details.append(f"GDP 增长 {gdp_growth:.1f}%")
        
        # 失业率分析
        if unemployment < 4.0:
            score += 5
            details.append(f"失业率 {unemployment:.1f}%，充分就业")
        elif unemployment > 6.0:
            score -= 5
            details.append(f"失业率 {unemployment:.1f}%，就业疲软")
        
        return {
            "score": score,
            "status": status,
            "gdp_growth": gdp_growth,
            "unemployment": unemployment,
            "details": " | ".join(details)
        }
    
    def _analyze_market_conditions(self, data: Dict) -> Dict[str, Any]:
        """分析市场状况"""
        vix = data['vix']['value']
        dxy = data['dxy']['value']
        gold = data['gold']['value']
        
        score = 0
        status = ""
        details = []
        
        # VIX 分析
        if vix < 15:
            score += 10
            details.append(f"VIX {vix:.1f}，市场恐慌低，风险偏好高")
        elif vix > 30:
            score -= 10
            details.append(f"VIX {vix:.1f}，市场恐慌高，避险情绪浓")
        else:
            details.append(f"VIX {vix:.1f}，市场情绪正常")
        
        # 美元指数分析
        if dxy > 105:
            score -= 5
            details.append(f"美元指数 {dxy:.1f}，强美元压制加密货币")
        elif dxy < 95:
            score += 5
            details.append(f"美元指数 {dxy:.1f}，弱美元利好加密货币")
        
        # 黄金分析
        if gold > 2000:
            score += 5
            details.append(f"黄金 ${gold:.0f}，避险需求高，利好 BTC")
        
        if score > 10:
            status = "风险偏好高"
        elif score < -10:
            status = "避险情绪浓"
        else:
            status = "市场中性"
        
        return {
            "score": score,
            "status": status,
            "vix": vix,
            "dxy": dxy,
            "gold": gold,
            "details": " | ".join(details)
        }
    
    def _analyze_economic_cycle(self, data: Dict) -> Dict[str, Any]:
        """分析经济周期"""
        cycle = data['economic_cycle']
        
        score = 0
        details = []
        
        if cycle['phase'] == 'expansion':
            score = 15
            details.append("经济扩张期，风险资产表现最佳")
        elif cycle['phase'] == 'peak':
            score = 5
            details.append("经济见顶，需警惕回调")
        elif cycle['phase'] == 'contraction':
            score = -15
            details.append("经济收缩期，风险资产承压")
        elif cycle['phase'] == 'trough':
            score = 10
            details.append("经济触底，可能是买入机会")
        
        return {
            "score": score,
            "phase": cycle['phase'],
            "confidence": cycle['confidence'],
            "details": " | ".join(details)
        }
    
    def _calculate_macro_score(
        self,
        monetary: Dict,
        inflation: Dict,
        growth: Dict,
        market: Dict,
        cycle: Dict
    ) -> int:
        """计算宏观综合评分"""
        score = 50  # 基准分
        
        score += monetary['score']
        score += inflation['score']
        score += growth['score']
        score += market['score']
        score += cycle['score']
        
        return max(0, min(100, score))
    
    def _generate_recommendation(
        self,
        score: int,
        monetary: Dict,
        inflation: Dict,
        cycle: Dict
    ) -> Dict[str, Any]:
        """生成宏观建议"""
        if score >= 70:
            direction = "宏观利好"
            confidence = "高"
            reason = f"{monetary['stance']}货币政策，{cycle['phase']}阶段"
        elif score >= 55:
            direction = "宏观偏好"
            confidence = "中"
            reason = "宏观环境偏好但不强"
        elif score <= 30:
            direction = "宏观利空"
            confidence = "高"
            reason = f"{inflation['status']}，{cycle['phase']}阶段"
        elif score <= 45:
            direction = "宏观偏空"
            confidence = "中"
            reason = "宏观环境偏空但不强"
        else:
            direction = "宏观中性"
            confidence = "低"
            reason = "宏观环境中性"
        
        return {
            "direction": direction,
            "confidence": confidence,
            "reason": reason
        }


# 测试代码
if __name__ == "__main__":
    async def test():
        # 使用提供的 FRED API Key
        fred_key = "c4b29c554a3e0e6e5e5f5e5e5e5e5e5e"
        
        engine = MacroAnalysisEngine(fred_key)
        
        report = await engine.analyze()
        
        print(f"宏观分析报告:")
        print(f"  评分: {report['score']}/100")
        print(f"  货币政策: {report['monetary_policy']['stance']}")
        print(f"  通胀状况: {report['inflation']['status']}")
        print(f"  经济周期: {report['economic_cycle']['phase']}")
        print(f"  建议: {report['recommendation']['direction']} (置信度: {report['recommendation']['confidence']})")
    
    asyncio.run(test())
