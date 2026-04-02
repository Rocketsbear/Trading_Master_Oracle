"""
情绪分析数据源 — 6551 OpenNews + OpenTwitter + BlockBeats
获取真实的加密货币新闻和 Twitter/X 社交媒体情绪数据
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None


API_BASE_URL = "https://ai.6551.io"
BLOCKBEATS_API = "https://api.theblockbeats.news/v1"


class SentimentDataSource:
    """情绪数据源 — 6551 REST API (新闻 + Twitter)"""
    
    def __init__(self, jwt_token: str):
        if not httpx:
            raise ImportError("httpx not installed: pip install httpx")
        self.token = jwt_token
        self._client: Optional[httpx.AsyncClient] = None
        logger.info("情绪数据源初始化完成 (6551 OpenNews + Twitter + BlockBeats)")
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client
    
    async def _post(self, path: str, body: dict) -> Optional[dict]:
        """发送 POST 请求"""
        try:
            client = await self._get_client()
            resp = await client.post(f"{API_BASE_URL}{path}", json=body)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"6551 API 调用失败 [{path}]: {e}")
            return None
    
    async def get_crypto_news(self, coins: List[str] = None, limit: int = 15) -> List[Dict]:
        """获取加密货币新闻"""
        body = {
            "limit": limit,
            "page": 1,
            "hasCoin": True,
        }
        if coins:
            body["coins"] = coins
        
        result = await self._post("/open/news_search", body)
        if result and isinstance(result, dict):
            # API 可能返回 {"data": [...]} 或直接列表
            data = result.get("data", result.get("items", result.get("articles", [])))
            if isinstance(data, list):
                return data
        return []
    
    async def search_news(self, query: str, limit: int = 10) -> List[Dict]:
        """搜索特定关键词新闻"""
        body = {"q": query, "limit": limit, "page": 1}
        result = await self._post("/open/news_search", body)
        if result and isinstance(result, dict):
            data = result.get("data", result.get("items", []))
            if isinstance(data, list):
                return data
        return []
    
    async def search_twitter(self, keywords: str, limit: int = 15) -> List[Dict]:
        """搜索 Twitter/X 相关推文"""
        body = {
            "keywords": keywords,
            "maxResults": limit,
            "product": "Top",
            "excludeReplies": True,
            "minLikes": 5,  # 只看有互动的推文
        }
        result = await self._post("/open/twitter_search", body)
        if result and isinstance(result, dict):
            data = result.get("data", result.get("tweets", []))
            if isinstance(data, list):
                return data
        return []
    
    # ==========================================
    # BlockBeats API (public, no auth)
    # ==========================================

    async def get_blockbeats_flash(self, limit: int = 20, lang: str = "en") -> List[Dict]:
        """获取 BlockBeats 快讯 (push = 重要新闻)"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{BLOCKBEATS_API}/open-api/open-flash",
                    params={"size": limit, "page": 1, "type": "push", "lang": lang},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == 0 and data.get("data", {}).get("data"):
                    articles = data["data"]["data"]
                    # Normalize to common format
                    return [
                        {
                            "text": a.get("title", ""),
                            "description": a.get("content", ""),
                            "source": "BlockBeats",
                            "url": a.get("link", ""),
                            "timestamp": a.get("create_time", ""),
                        }
                        for a in articles
                    ]
        except Exception as e:
            logger.warning(f"BlockBeats 快讯获取失败: {e}")
        return []

    async def get_blockbeats_articles(self, limit: int = 10, lang: str = "en") -> List[Dict]:
        """获取 BlockBeats 深度文章"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{BLOCKBEATS_API}/open-api/open-information",
                    params={"size": limit, "page": 1, "lang": lang},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == 0 and data.get("data", {}).get("data"):
                    articles = data["data"]["data"]
                    return [
                        {
                            "text": a.get("title", ""),
                            "description": a.get("description", ""),
                            "source": "BlockBeats",
                            "url": a.get("link", ""),
                            "timestamp": a.get("create_time", ""),
                            "column": a.get("column", ""),
                        }
                        for a in articles
                    ]
        except Exception as e:
            logger.warning(f"BlockBeats 文章获取失败: {e}")
        return []

    async def get_kol_tweets(self, username: str, limit: int = 5) -> List[Dict]:
        """获取 KOL 最新推文"""
        body = {
            "username": username,
            "maxResults": limit,
            "product": "Latest",
            "includeReplies": False,
            "includeRetweets": False,
        }
        result = await self._post("/open/twitter_user_tweets", body)
        if result and isinstance(result, dict):
            data = result.get("data", result.get("tweets", []))
            if isinstance(data, list):
                return data
        return []

    def _analyze_sentiment_from_news(self, articles: List[Dict]) -> Dict:
        """从新闻文章中分析情绪"""
        if not articles:
            return {"score": 50, "positive": 0, "negative": 0, "neutral": 0, "total": 0}
        
        positive_keywords = [
            "bullish", "surge", "rally", "breakout", "soar", "gain", "adoption",
            "approval", "launch", "positive", "growth", "record", "high", "buy",
            "看多", "上涨", "突破", "利好", "创新高", "通过", "采用",
        ]
        negative_keywords = [
            "bearish", "crash", "dump", "plunge", "hack", "scam", "ban",
            "lawsuit", "decline", "fear", "sell", "loss", "warning", "risk",
            "看空", "下跌", "暴跌", "利空", "黑客", "禁止", "诉讼",
        ]
        
        positive = 0
        negative = 0
        neutral = 0
        
        for article in articles:
            text = str(article.get("text", "")) + " " + str(article.get("description", ""))
            text_lower = text.lower()
            
            pos_count = sum(1 for kw in positive_keywords if kw in text_lower)
            neg_count = sum(1 for kw in negative_keywords if kw in text_lower)
            
            if pos_count > neg_count:
                positive += 1
            elif neg_count > pos_count:
                negative += 1
            else:
                neutral += 1
        
        total = positive + negative + neutral
        if total > 0:
            score = round(50 + (positive - negative) / total * 30)
        else:
            score = 50
        
        return {
            "score": max(0, min(100, score)),
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "total": total,
        }
    
    async def get_comprehensive_sentiment(self, symbol: str) -> Dict:
        """获取综合情绪数据 — 全部真实 API"""
        coin = symbol.replace("USDT", "").replace("USD", "")
        
        # 并行获取新闻和 Twitter 数据 (4 sources)
        news_task = self.get_crypto_news(coins=[coin], limit=15)
        twitter_task = self.search_twitter(f"${coin} crypto", limit=15)
        general_news_task = self.search_news(f"{coin} Bitcoin crypto market", limit=10)
        blockbeats_task = self.get_blockbeats_flash(limit=20, lang="en")
        
        news_articles, twitter_data, general_news, bb_flash = await asyncio.gather(
            news_task, twitter_task, general_news_task, blockbeats_task,
            return_exceptions=True,
        )
        
        # 处理异常
        if isinstance(news_articles, Exception):
            logger.warning(f"新闻获取失败: {news_articles}")
            news_articles = []
        if isinstance(twitter_data, Exception):
            logger.warning(f"Twitter获取失败: {twitter_data}")
            twitter_data = []
        if isinstance(general_news, Exception):
            logger.warning(f"通用新闻获取失败: {general_news}")
            general_news = []
        if isinstance(bb_flash, Exception):
            logger.warning(f"BlockBeats获取失败: {bb_flash}")
            bb_flash = []
        
        # 合并新闻并分析情绪 (6551 + BlockBeats)
        all_articles = list(news_articles) + list(general_news) + list(bb_flash)
        news_sentiment = self._analyze_sentiment_from_news(all_articles)
        
        # Twitter 情绪统计
        twitter_count = len(twitter_data) if isinstance(twitter_data, list) else 0
        twitter_engagement = 0
        if isinstance(twitter_data, list):
            for tweet in twitter_data:
                twitter_engagement += int(tweet.get("likeCount", tweet.get("likes", 0)) or 0)
                twitter_engagement += int(tweet.get("retweetCount", tweet.get("retweets", 0)) or 0)
        
        # 综合情绪评分
        overall_score = news_sentiment["score"]
        
        # 提取关键新闻（text 字段）
        top_headlines = []
        for a in all_articles[:5]:
            text = a.get("text", a.get("description", ""))
            if text:
                top_headlines.append(str(text)[:100])
        
        return {
            "source": "6551+blockbeats",
            "overall_sentiment_score": overall_score,
            "news": {
                "total_articles": len(all_articles),
                "positive": news_sentiment["positive"],
                "negative": news_sentiment["negative"],
                "neutral": news_sentiment["neutral"],
                "top_headlines": top_headlines,
            },
            "twitter": {
                "tweet_count": twitter_count,
                "total_engagement": twitter_engagement,
            },
            "coin": coin,
        }
    
    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
