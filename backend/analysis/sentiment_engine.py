"""
情绪分析引擎
整合新闻、Twitter、社交媒体情绪数据
"""
import asyncio
from typing import Dict, Any
from datetime import datetime
from loguru import logger

from ..data_sources.macro.sentiment import SentimentDataSource


class SentimentAnalysisEngine:
    """情绪分析引擎"""
    
    def __init__(self, mcp_path: str = None):
        """
        初始化情绪分析引擎
        
        Args:
            mcp_path: 6551 MCP 路径
        """
        self.sentiment = SentimentDataSource(mcp_path)
        logger.info("情绪分析引擎初始化完成")
    
    async def analyze(self, symbol: str = "BTC") -> Dict[str, Any]:
        """
        执行完整的情绪分析
        
        Args:
            symbol: 币种
            
        Returns:
            完整的情绪分析报告
        """
        try:
            logger.info(f"开始情绪分析: {symbol}")
            
            # 获取综合情绪数据
            data = await self.sentiment.get_comprehensive_sentiment(symbol)
            
            # 分析各个维度
            news_analysis = self._analyze_news_sentiment(data['news_sentiment'])
            twitter_analysis = self._analyze_twitter_sentiment(data['twitter_sentiment'])
            social_analysis = self._analyze_social_sentiment(data['social_media'])
            
            # 综合评分
            score = self._calculate_sentiment_score(
                news_analysis,
                twitter_analysis,
                social_analysis
            )
            
            # 生成建议
            recommendation = self._generate_recommendation(
                score,
                news_analysis,
                twitter_analysis
            )
            
            report = {
                "symbol": symbol,
                "score": score,
                "news_sentiment": news_analysis,
                "twitter_sentiment": twitter_analysis,
                "social_sentiment": social_analysis,
                "recommendation": recommendation,
                "timestamp": datetime.now(),
                "data_source": "6551_mcp"
            }
            
            logger.info(f"情绪分析完成，评分: {score}")
            return report
            
        except Exception as e:
            logger.error(f"情绪分析失败: {e}")
            raise
    
    def _analyze_news_sentiment(self, news: Dict) -> Dict[str, Any]:
        """分析新闻情绪"""
        sentiment_score = news.get('sentiment_score', 50)
        positive = news.get('positive_count', 0)
        negative = news.get('negative_count', 0)
        total = news.get('total_news', 0)
        
        score = 0
        status = ""
        details = []
        
        # 情绪评分分析
        if sentiment_score > 0.3:
            score = 15
            status = "极度乐观"
            details.append(f"新闻情绪 {sentiment_score:.2f}，正面新闻占主导")
        elif sentiment_score > 0.1:
            score = 10
            status = "乐观"
            details.append(f"新闻情绪 {sentiment_score:.2f}，偏正面")
        elif sentiment_score < -0.3:
            score = -15
            status = "极度悲观"
            details.append(f"新闻情绪 {sentiment_score:.2f}，负面新闻占主导")
        elif sentiment_score < -0.1:
            score = -10
            status = "悲观"
            details.append(f"新闻情绪 {sentiment_score:.2f}，偏负面")
        else:
            status = "中性"
            details.append(f"新闻情绪 {sentiment_score:.2f}，中性")
        
        # 新闻数量分析
        if total > 100:
            details.append(f"新闻量 {total} 篇，关注度高")
        elif total < 20:
            details.append(f"新闻量 {total} 篇，关注度低")
        
        return {
            "score": score,
            "status": status,
            "sentiment_score": sentiment_score,
            "positive_count": positive,
            "negative_count": negative,
            "total_count": total,
            "details": " | ".join(details)
        }
    
    def _analyze_twitter_sentiment(self, twitter: Dict) -> Dict[str, Any]:
        """分析 Twitter 情绪"""
        sentiment_score = twitter['sentiment_score']
        mentions = twitter['mentions_24h']
        engagement = twitter['engagement_rate']
        
        score = 0
        status = ""
        details = []
        
        # 情绪评分分析
        if sentiment_score > 0.4:
            score = 15
            status = "极度看多"
            details.append(f"Twitter 情绪 {sentiment_score:.2f}，社区极度乐观")
        elif sentiment_score > 0.2:
            score = 10
            status = "看多"
            details.append(f"Twitter 情绪 {sentiment_score:.2f}，社区偏乐观")
        elif sentiment_score < -0.4:
            score = -15
            status = "极度看空"
            details.append(f"Twitter 情绪 {sentiment_score:.2f}，社区极度悲观")
        elif sentiment_score < -0.2:
            score = -10
            status = "看空"
            details.append(f"Twitter 情绪 {sentiment_score:.2f}，社区偏悲观")
        else:
            status = "中性"
            details.append(f"Twitter 情绪 {sentiment_score:.2f}，中性")
        
        # 提及量分析
        if mentions > 50000:
            details.append(f"提及量 {mentions:,}，热度极高")
            # 过度热度可能是反向指标
            if sentiment_score > 0.5:
                score -= 5
                details.append("⚠️ 过度乐观，警惕回调")
        elif mentions > 20000:
            details.append(f"提及量 {mentions:,}，热度高")
        elif mentions < 5000:
            details.append(f"提及量 {mentions:,}，热度低")
        
        # 互动率分析
        if engagement > 5.0:
            details.append(f"互动率 {engagement:.1f}%，社区活跃")
        
        return {
            "score": score,
            "status": status,
            "sentiment_score": sentiment_score,
            "mentions": mentions,
            "engagement_rate": engagement,
            "details": " | ".join(details)
        }
    
    def _analyze_social_sentiment(self, social: Dict) -> Dict[str, Any]:
        """分析社交媒体情绪"""
        reddit_score = social['reddit_sentiment']
        telegram_score = social['telegram_sentiment']
        
        score = 0
        status = ""
        details = []
        
        avg_score = (reddit_score + telegram_score) / 2
        
        if avg_score > 0.3:
            score = 10
            status = "社区乐观"
            details.append(f"Reddit {reddit_score:.2f}, Telegram {telegram_score:.2f}")
        elif avg_score < -0.3:
            score = -10
            status = "社区悲观"
            details.append(f"Reddit {reddit_score:.2f}, Telegram {telegram_score:.2f}")
        else:
            status = "社区中性"
            details.append(f"Reddit {reddit_score:.2f}, Telegram {telegram_score:.2f}")
        
        return {
            "score": score,
            "status": status,
            "reddit_sentiment": reddit_score,
            "telegram_sentiment": telegram_score,
            "details": " | ".join(details)
        }
    
    def _calculate_sentiment_score(
        self,
        news: Dict,
        twitter: Dict,
        social: Dict
    ) -> int:
        """计算情绪综合评分"""
        score = 50  # 基准分
        
        # 新闻权重 40%
        score += news['score'] * 0.4
        
        # Twitter 权重 40%
        score += twitter['score'] * 0.4
        
        # 社交媒体权重 20%
        score += social['score'] * 0.2
        
        return max(0, min(100, int(score)))
    
    def _generate_recommendation(
        self,
        score: int,
        news: Dict,
        twitter: Dict
    ) -> Dict[str, Any]:
        """生成情绪建议"""
        if score >= 70:
            direction = "情绪极度乐观"
            confidence = "高"
            reason = f"{news['status']}，{twitter['status']}"
            warning = "⚠️ 过度乐观可能是顶部信号，注意风险"
        elif score >= 55:
            direction = "情绪偏乐观"
            confidence = "中"
            reason = "市场情绪偏好"
            warning = None
        elif score <= 30:
            direction = "情绪极度悲观"
            confidence = "高"
            reason = f"{news['status']}，{twitter['status']}"
            warning = "💡 极度悲观可能是底部信号，可以关注"
        elif score <= 45:
            direction = "情绪偏悲观"
            confidence = "中"
            reason = "市场情绪偏空"
            warning = None
        else:
            direction = "情绪中性"
            confidence = "低"
            reason = "市场情绪中性"
            warning = None
        
        return {
            "direction": direction,
            "confidence": confidence,
            "reason": reason,
            "warning": warning
        }


# 测试代码
if __name__ == "__main__":
    async def test():
        engine = SentimentAnalysisEngine()
        
        report = await engine.analyze("BTC")
        
        print(f"情绪分析报告:")
        print(f"  评分: {report['score']}/100")
        print(f"  新闻情绪: {report['news_sentiment']['status']}")
        print(f"  Twitter 情绪: {report['twitter_sentiment']['status']}")
        print(f"  建议: {report['recommendation']['direction']}")
        if report['recommendation']['warning']:
            print(f"  警告: {report['recommendation']['warning']}")
    
    asyncio.run(test())
