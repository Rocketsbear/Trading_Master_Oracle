"""
AI 合成层
整合所有分析引擎，生成综合分析报告
"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.analysis.technical_engine import TechnicalAnalysisEngine
from backend.analysis.onchain_engine import OnchainAnalysisEngine
from backend.analysis.macro_engine import MacroAnalysisEngine
from backend.analysis.sentiment_engine import SentimentAnalysisEngine
from backend.analysis.metaphysical_engine import MetaphysicalAnalysisEngine


class AISynthesizer:
    """AI 合成层"""
    
    def __init__(
        self,
        binance_api_key: Optional[str] = None,
        binance_api_secret: Optional[str] = None,
        coinank_api_key: Optional[str] = None,
        fred_api_key: Optional[str] = None,
        mcp_path: Optional[str] = None
    ):
        """
        初始化 AI 合成层
        
        Args:
            binance_api_key: Binance API Key
            binance_api_secret: Binance API Secret
            coinank_api_key: CoinAnk API Key
            fred_api_key: FRED API Key
            mcp_path: MCP 路径
        """
        self.technical = TechnicalAnalysisEngine(binance_api_key, binance_api_secret, coinank_api_key)
        self.onchain = OnchainAnalysisEngine(mcp_path)
        self.macro = MacroAnalysisEngine(fred_api_key) if fred_api_key else None
        self.sentiment = SentimentAnalysisEngine(mcp_path)
        self.metaphysical = MetaphysicalAnalysisEngine(mcp_path)
        
        # 默认权重配置（可根据币种调整）
        self.default_weights = {
            "technical": 0.30,
            "onchain": 0.25,
            "macro": 0.20,
            "sentiment": 0.15,
            "metaphysical": 0.10
        }
        
        logger.info("AI 合成层初始化完成")
    
    async def analyze(
        self,
        symbol: str,
        interval: str = "1h",
        weights: Optional[Dict[str, float]] = None,
        birth_date: Optional[str] = None,
        birth_time: Optional[str] = None,
        birth_place: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行完整的综合分析
        
        Args:
            symbol: 交易对（如 BTCUSDT）
            interval: 时间间隔
            weights: 自定义权重
            birth_date: 出生日期（用于玄学分析）
            birth_time: 出生时间
            birth_place: 出生地点
            
        Returns:
            完整的综合分析报告
        """
        try:
            logger.info(f"开始综合分析: {symbol}")
            
            # 使用自定义权重或默认权重
            weights = weights or self._get_symbol_weights(symbol)
            
            # 并行执行所有分析
            results = await asyncio.gather(
                self.technical.analyze(symbol, interval),
                self.onchain.analyze(symbol.replace("USDT", "")),
                self.macro.analyze() if self.macro else self._get_empty_macro(),
                self.sentiment.analyze(symbol.replace("USDT", "")),
                self.metaphysical.analyze(symbol.replace("USDT", ""), birth_date, birth_time, birth_place),
                return_exceptions=True
            )
            
            # 处理结果
            technical_report = results[0] if not isinstance(results[0], Exception) else None
            onchain_report = results[1] if not isinstance(results[1], Exception) else None
            macro_report = results[2] if not isinstance(results[2], Exception) else None
            sentiment_report = results[3] if not isinstance(results[3], Exception) else None
            metaphysical_report = results[4] if not isinstance(results[4], Exception) else None
            
            # 记录错误
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"分析模块 {i} 失败: {result}")
            
            # 计算加权评分
            weighted_score = self._calculate_weighted_score(
                technical_report,
                onchain_report,
                macro_report,
                sentiment_report,
                metaphysical_report,
                weights
            )
            
            # 生成综合分析
            comprehensive_analysis = self._generate_comprehensive_analysis(
                symbol,
                weighted_score,
                technical_report,
                onchain_report,
                macro_report,
                sentiment_report,
                metaphysical_report,
                weights
            )
            
            logger.info(f"综合分析完成，最终评分: {weighted_score}")
            return comprehensive_analysis
            
        except Exception as e:
            logger.error(f"综合分析失败: {e}")
            raise
    
    def _get_symbol_weights(self, symbol: str) -> Dict[str, float]:
        """根据币种获取权重配置"""
        symbol_upper = symbol.upper()
        
        if "BTC" in symbol_upper:
            # BTC: 宏观权重更高
            return {
                "technical": 0.25,
                "onchain": 0.25,
                "macro": 0.25,
                "sentiment": 0.15,
                "metaphysical": 0.10
            }
        elif "ETH" in symbol_upper:
            # ETH: 链上权重更高
            return {
                "technical": 0.25,
                "onchain": 0.30,
                "macro": 0.20,
                "sentiment": 0.15,
                "metaphysical": 0.10
            }
        else:
            # 山寨币: 技术面权重更高
            return {
                "technical": 0.35,
                "onchain": 0.20,
                "macro": 0.15,
                "sentiment": 0.20,
                "metaphysical": 0.10
            }
    
    def _calculate_weighted_score(
        self,
        technical: Optional[Dict],
        onchain: Optional[Dict],
        macro: Optional[Dict],
        sentiment: Optional[Dict],
        metaphysical: Optional[Dict],
        weights: Dict[str, float]
    ) -> float:
        """计算加权评分"""
        total_score = 0
        total_weight = 0
        
        if technical:
            total_score += technical['score'] * weights['technical']
            total_weight += weights['technical']
            logger.info(f"技术面评分: {technical['score']}, 权重: {weights['technical']}")
        
        if onchain:
            total_score += onchain['score'] * weights['onchain']
            total_weight += weights['onchain']
            logger.info(f"链上评分: {onchain['score']}, 权重: {weights['onchain']}")
        
        if macro:
            total_score += macro['score'] * weights['macro']
            total_weight += weights['macro']
            logger.info(f"宏观评分: {macro['score']}, 权重: {weights['macro']}")
        
        if sentiment:
            total_score += sentiment['score'] * weights['sentiment']
            total_weight += weights['sentiment']
            logger.info(f"情绪评分: {sentiment['score']}, 权重: {weights['sentiment']}")
        
        if metaphysical:
            total_score += metaphysical['score'] * weights['metaphysical']
            total_weight += weights['metaphysical']
            logger.info(f"玄学评分: {metaphysical['score']}, 权重: {weights['metaphysical']}")
        
        # 归一化
        if total_weight > 0:
            final_score = total_score / total_weight
        else:
            final_score = 50  # 默认中性
        
        logger.info(f"加权综合评分: {final_score:.1f}")
        return round(final_score, 1)
    
    def _generate_comprehensive_analysis(
        self,
        symbol: str,
        score: float,
        technical: Optional[Dict],
        onchain: Optional[Dict],
        macro: Optional[Dict],
        sentiment: Optional[Dict],
        metaphysical: Optional[Dict],
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """生成综合分析报告"""
        
        # 生成最终建议
        recommendation = self._generate_final_recommendation(
            score, technical, onchain, macro, sentiment, metaphysical
        )
        
        # 生成详细分析
        detailed_analysis = self._generate_detailed_analysis(
            technical, onchain, macro, sentiment, metaphysical
        )
        
        # 生成风险提示
        risk_warnings = self._generate_risk_warnings(
            technical, onchain, macro, sentiment, metaphysical
        )
        
        report = {
            "symbol": symbol,
            "final_score": score,
            "weights": weights,
            "recommendation": recommendation,
            "detailed_analysis": detailed_analysis,
            "risk_warnings": risk_warnings,
            "individual_scores": {
                "technical": technical['score'] if technical else None,
                "onchain": onchain['score'] if onchain else None,
                "macro": macro['score'] if macro else None,
                "sentiment": sentiment['score'] if sentiment else None,
                "metaphysical": metaphysical['score'] if metaphysical else None
            },
            "raw_reports": {
                "technical": technical,
                "onchain": onchain,
                "macro": macro,
                "sentiment": sentiment,
                "metaphysical": metaphysical
            },
            "timestamp": datetime.now(),
            "version": "1.0.0"
        }
        
        return report
    
    def _generate_final_recommendation(
        self,
        score: float,
        technical: Optional[Dict],
        onchain: Optional[Dict],
        macro: Optional[Dict],
        sentiment: Optional[Dict],
        metaphysical: Optional[Dict]
    ) -> Dict[str, Any]:
        """生成最终建议"""
        
        if score >= 70:
            direction = "强烈看多"
            action = "建议做多"
            confidence = "高"
        elif score >= 60:
            direction = "看多"
            action = "可以做多"
            confidence = "中高"
        elif score >= 55:
            direction = "偏多"
            action = "谨慎做多"
            confidence = "中"
        elif score <= 30:
            direction = "强烈看空"
            action = "建议做空或观望"
            confidence = "高"
        elif score <= 40:
            direction = "看空"
            action = "可以做空"
            confidence = "中高"
        elif score <= 45:
            direction = "偏空"
            action = "谨慎做空"
            confidence = "中"
        else:
            direction = "中性"
            action = "观望为主"
            confidence = "低"
        
        # 生成理由
        reasons = []
        if technical:
            reasons.append(f"技术面: {technical['recommendation']['direction']}")
        if onchain:
            reasons.append(f"链上: {onchain['recommendation']['direction']}")
        if macro:
            reasons.append(f"宏观: {macro['recommendation']['direction']}")
        if sentiment:
            reasons.append(f"情绪: {sentiment['recommendation']['direction']}")
        if metaphysical:
            reasons.append(f"玄学: {metaphysical['recommendation']['direction']}")
        
        return {
            "direction": direction,
            "action": action,
            "confidence": confidence,
            "score": score,
            "reasons": reasons
        }
    
    def _generate_detailed_analysis(
        self,
        technical: Optional[Dict],
        onchain: Optional[Dict],
        macro: Optional[Dict],
        sentiment: Optional[Dict],
        metaphysical: Optional[Dict]
    ) -> str:
        """生成详细分析文本"""
        
        analysis_parts = []
        
        if technical:
            analysis_parts.append(
                f"📊 技术面 ({technical['score']}/100): "
                f"{technical['trend_analysis']['overall']}，"
                f"{technical['momentum_analysis']['details']}"
            )
        
        if onchain:
            analysis_parts.append(
                f"⛓️ 链上 ({onchain['score']}/100): "
                f"{onchain['exchange_flows']['details']}，"
                f"{onchain['holder_distribution']['details']}"
            )
        
        if macro:
            analysis_parts.append(
                f"🌍 宏观 ({macro['score']}/100): "
                f"{macro['monetary_policy']['details']}，"
                f"{macro['economic_cycle']['details']}"
            )
        
        if sentiment:
            analysis_parts.append(
                f"💬 情绪 ({sentiment['score']}/100): "
                f"{sentiment['news_sentiment']['details']}，"
                f"{sentiment['twitter_sentiment']['details']}"
            )
        
        if metaphysical:
            analysis_parts.append(
                f"🔮 玄学 ({metaphysical['score']}/100): "
                f"{metaphysical['recommendation']['reason']} "
                f"({metaphysical['note']})"
            )
        
        return "\n\n".join(analysis_parts)
    
    def _generate_risk_warnings(
        self,
        technical: Optional[Dict],
        onchain: Optional[Dict],
        macro: Optional[Dict],
        sentiment: Optional[Dict],
        metaphysical: Optional[Dict]
    ) -> list:
        """生成风险提示"""
        
        warnings = []
        
        # 技术面风险
        if technical:
            if technical['score'] < 40:
                warnings.append("⚠️ 技术面偏空，注意止损")
            if technical.get('momentum_analysis', {}).get('rsi', {}).get('status') == 'overbought':
                warnings.append("⚠️ RSI 超买，可能回调")
        
        # 链上风险
        if onchain:
            if onchain['exchange_flows']['net_flow'] > 5000:
                warnings.append("⚠️ 大量流入交易所，抛压增加")
        
        # 宏观风险
        if macro:
            if macro['monetary_policy']['fed_rate'] > 5.0:
                warnings.append("⚠️ 高利率环境，风险资产承压")
        
        # 情绪风险
        if sentiment:
            if sentiment['score'] > 70:
                warnings.append("⚠️ 情绪过度乐观，警惕顶部")
            elif sentiment['score'] < 30:
                warnings.append("💡 情绪极度悲观，可能是底部机会")
        
        # 玄学风险
        if metaphysical and metaphysical.get('recommendation', {}).get('warnings'):
            for w in metaphysical['recommendation']['warnings']:
                warnings.append(f"🔮 {w}")
        
        return warnings if warnings else ["✅ 暂无明显风险警告"]
    
    def _get_empty_macro(self) -> Dict[str, Any]:
        """返回空的宏观数据"""
        return {
            "score": 50,
            "recommendation": {
                "direction": "宏观数据缺失",
                "confidence": "低",
                "reason": "未配置 FRED API Key"
            }
        }


if __name__ == "__main__":
    import sys
    import io
    import os
    # 设置输出编码为 UTF-8
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    async def test():
        # 从环境变量读取 API Keys
        fred_key = os.environ.get("FRED_API_KEY", "")
        coinank_key = os.environ.get("COINANK_API_KEY", "")
        
        synthesizer = AISynthesizer(
            fred_api_key=fred_key,
            coinank_api_key=coinank_key
        )
        
        report = await synthesizer.analyze("BTCUSDT", "1h")
        
        print(f"\n{'='*60}")
        print(f"综合分析报告: {report['symbol']}")
        print(f"{'='*60}")
        print(f"\n最终评分: {report['final_score']}/100")
        print(f"\n建议: {report['recommendation']['action']}")
        print(f"方向: {report['recommendation']['direction']}")
        print(f"置信度: {report['recommendation']['confidence']}")
        print(f"\n理由:")
        for reason in report['recommendation']['reasons']:
            print(f"  - {reason}")
        print(f"\n详细分析:")
        print(report['detailed_analysis'])
        print(f"\n风险提示:")
        for warning in report['risk_warnings']:
            print(f"  {warning}")
        print(f"\n{'='*60}")
    
    asyncio.run(test())

