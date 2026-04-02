"""
逆向交易者 Agent 🔄 — Fear & Greed Index + 6551 OpenNews + Twitter
"""
import asyncio
import httpx
from typing import Dict, Any
from loguru import logger
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from backend.data_sources.macro.sentiment import SentimentDataSource


class SentimentAgent(BaseAgent):
    """逆向交易者 🔄 — 当所有人恐惧时贪婪，当所有人贪婪时恐惧"""
    
    def __init__(self, jwt_token: str = None):
        super().__init__(
            name="逆向交易者 🔄",
            agent_type=AgentType.SENTIMENT,
            personality=(
                "当所有人恐惧时我贪婪，当所有人贪婪时我恐惧。"
                "恐贪指数<15我看多，>85我看空。"
                "多空比极端偏向一方时，大概率反转。"
                "市场情绪是最好的反向指标——但只在极端时有效。"
                "非极端区间(15-85)我选择沉默，不给噪音信号。"
            )
        )
        self.sentiment_source = SentimentDataSource(jwt_token) if jwt_token else None
        self._fng_cache = None  # Cache to avoid hitting API too frequently
        self._fng_cache_ts = 0
    
    async def _fetch_fear_greed(self) -> Dict:
        """获取 Fear & Greed Index (alternative.me, 免费无需Key)"""
        import time
        # Cache for 10 minutes
        if self._fng_cache and time.time() - self._fng_cache_ts < 600:
            return self._fng_cache
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://api.alternative.me/fng/?limit=7")
                data = resp.json()
                if data.get("data"):
                    result = {
                        "current": int(data["data"][0]["value"]),
                        "label": data["data"][0]["value_classification"],
                        "history": [
                            {"value": int(d["value"]), "label": d["value_classification"]}
                            for d in data["data"][:7]
                        ],
                        "avg_7d": round(sum(int(d["value"]) for d in data["data"][:7]) / len(data["data"][:7]), 1),
                        "trend": "rising" if int(data["data"][0]["value"]) > int(data["data"][-1]["value"]) else "falling",
                    }
                    self._fng_cache = result
                    self._fng_cache_ts = time.time()
                    return result
        except Exception as e:
            logger.warning(f"Fear & Greed Index 获取失败: {e}")
        
        return {"current": 50, "label": "Neutral", "history": [], "avg_7d": 50, "trend": "flat"}
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """执行情绪分析 — Fear & Greed + 新闻 + Twitter"""
        try:
            # === 并行获取所有数据 ===
            fng_task = self._fetch_fear_greed()
            news_task = self.sentiment_source.get_comprehensive_sentiment(symbol) if self.sentiment_source else asyncio.coroutine(lambda: {})()
            
            results = await asyncio.gather(fng_task, news_task, return_exceptions=True)
            fng = results[0] if not isinstance(results[0], Exception) else {"current": 50, "label": "Neutral", "history": [], "avg_7d": 50, "trend": "flat"}
            data = results[1] if not isinstance(results[1], Exception) else {}
            
            score = 50
            observations = []
            
            # === 1. FEAR & GREED INDEX (核心信号, 权重最大) ===
            fng_value = fng["current"]
            fng_label = fng["label"]
            fng_avg = fng["avg_7d"]
            fng_trend = fng["trend"]
            
            # 逆向逻辑: 极度恐惧 = 做多，极度贪婪 = 做空
            if fng_value <= 10:
                score += 25  # 极度恐惧 → 强烈做多
                fng_signal = f"🟢 极度恐惧({fng_value}) → 强烈逆向做多"
            elif fng_value <= 25:
                score += 15  # 恐惧 → 做多
                fng_signal = f"🟢 恐惧({fng_value}) → 逆向做多"
            elif fng_value <= 40:
                score += 5   # 轻微恐惧
                fng_signal = f"🟡 偏恐惧({fng_value}) → 轻微看多"
            elif fng_value >= 90:
                score -= 25  # 极度贪婪 → 强烈做空
                fng_signal = f"🔴 极度贪婪({fng_value}) → 强烈逆向做空"
            elif fng_value >= 75:
                score -= 15  # 贪婪 → 做空
                fng_signal = f"🔴 贪婪({fng_value}) → 逆向做空"
            elif fng_value >= 60:
                score -= 5   # 轻微贪婪
                fng_signal = f"🟡 偏贪婪({fng_value}) → 轻微看空"
            else:
                fng_signal = f"⚪ 中性({fng_value}) → 不给信号"
            
            # 7日趋势加成
            if fng_trend == "falling" and fng_value < 30:
                score += 5  # 恐惧在加深 → 更强做多
                fng_signal += " (恐惧加深↓)"
            elif fng_trend == "rising" and fng_value > 70:
                score -= 5  # 贪婪在加剧 → 更强做空
                fng_signal += " (贪婪加剧↑)"
            
            observations.append(f"恐贪指数: {fng_value}/100 ({fng_label}), 7日均值: {fng_avg}")
            
            # === 2. 新闻情绪 ===
            news = data.get('news', {})
            news_total = news.get('total_articles', 0)
            news_positive = news.get('positive', 0)
            news_negative = news.get('negative', 0)
            news_neutral = news.get('neutral', 0)
            
            if news_total > 0:
                pos_ratio = news_positive / news_total * 100
                neg_ratio = news_negative / news_total * 100
                
                if pos_ratio > 60:
                    score += 10
                    news_signal = f"新闻极度乐观 ({news_positive}正/{news_negative}负)"
                elif pos_ratio > 40:
                    score += 5
                    news_signal = f"新闻偏乐观 ({news_positive}正/{news_negative}负)"
                elif neg_ratio > 60:
                    score -= 10
                    news_signal = f"新闻极度悲观 ({news_positive}正/{news_negative}负)"
                elif neg_ratio > 40:
                    score -= 5
                    news_signal = f"新闻偏悲观 ({news_positive}正/{news_negative}负)"
                else:
                    news_signal = f"新闻情绪中性 ({news_positive}正/{news_negative}负)"
                
                observations.append(f"新闻: {news_total}篇, {news_signal}")
            else:
                news_signal = "暂无新闻数据"
            
            # === 3. Twitter/社交媒体 ===
            twitter = data.get('twitter', {})
            tweet_count = twitter.get('tweet_count', 0)
            engagement = twitter.get('total_engagement', 0)
            
            if tweet_count > 0:
                if tweet_count > 10:
                    score += 3
                    twitter_signal = f"社交媒体讨论活跃 ({tweet_count}条推文)"
                else:
                    twitter_signal = f"社交媒体有讨论 ({tweet_count}条推文)"
                observations.append(f"Twitter: {tweet_count}条, 互动{engagement}")
            else:
                twitter_signal = "社交媒体讨论较少"
            
            # === 最终评分 ===
            score = max(0, min(100, score))
            direction = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"
            
            # 历史数据条
            fng_history_bar = " ".join(
                f"{'🟢' if h['value']<=25 else '🔴' if h['value']>=75 else '⚪'}{h['value']}"
                for h in fng.get("history", [])[:7]
            )
            
            # 关键新闻
            headlines = news.get('top_headlines', [])
            headlines_text = ""
            if headlines:
                headlines_text = "\n📰 关键新闻:\n" + "\n".join(f"   • {h}" for h in headlines[:5])
            
            reasoning = f"""逆向交易者分析 — 恐惧时贪婪，贪婪时恐惧：

🎯 Fear & Greed Index: {fng_value}/100 ({fng_label})
   7日趋势: {fng_history_bar}
   7日均值: {fng_avg} | 趋势: {'↑回暖' if fng_trend == 'rising' else '↓恶化' if fng_trend == 'falling' else '→持平'}
   信号: {fng_signal}

📊 情绪评分: {score}/100 ({direction})

📈 新闻情绪: {news_signal}
   正面{news_positive} | 负面{news_negative} | 中性{news_neutral} | 共{news_total}篇

🐦 社交媒体: {twitter_signal}
{headlines_text}

⚠️ 数据来源: Alternative.me Fear & Greed Index + 6551 OpenNews + Twitter + BlockBeats"""
            
            self.current_analysis = AnalysisResult(
                agent_type=AgentType.SENTIMENT,
                score=score,
                direction=direction,
                reasoning=reasoning,
                key_observations=observations,
                data_sources=["Alternative.me Fear & Greed Index", "6551 OpenNews", "6551 OpenTwitter", "BlockBeats"]
            )
            
            return self.current_analysis
            
        except Exception as e:
            logger.error(f"情绪分析出错: {e}")
            return self._no_data_result(f"情绪分析失败: {str(e)}")
    
    def _no_data_result(self, reason: str) -> AnalysisResult:
        return AnalysisResult(
            agent_type=AgentType.SENTIMENT,
            score=50,
            direction="neutral",
            reasoning=f"情绪分析无法完成: {reason}",
            key_observations=[reason],
            data_sources=["无数据"]
        )
