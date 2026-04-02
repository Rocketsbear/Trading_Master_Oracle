"""
玄学顾问Agent — 使用 DeepSeek LLM 进行八字、星座、运势、塔罗分析
用户提供出生年月日，结合当天日期生成个性化交易建议
"""
import asyncio
import re
from typing import Dict, Any, Optional
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.agents.base_agent import BaseAgent, AgentType, AnalysisResult
from loguru import logger


class MetaphysicalAgent(BaseAgent):
    """玄学顾问 — 使用 DeepSeek AI 进行命理分析"""
    
    def __init__(self, deepseek_config: Dict = None):
        super().__init__(
            name="量化玄学师 📐🔮",
            agent_type=AgentType.METAPHYSICAL,
            personality=(
                "我是量化与玄学的融合体。一方面用统计概率和波动率分析市场，"
                "另一方面用天干地支、星象和塔罗感知市场能量。"
                "波动率处于历史20-80百分位时才交易。"
                "极低波动=假突破陷阱，极高波动=尾部风险。"
                "数据和直觉，缺一不可。"
            )
        )
        self.deepseek_client = None
        if deepseek_config and deepseek_config.get('api_key'):
            try:
                from openai import AsyncOpenAI
                self.deepseek_client = AsyncOpenAI(
                    api_key=deepseek_config['api_key'],
                    base_url=deepseek_config.get('base_url', 'https://openrouter.fans/v1'),
                )
                self.deepseek_model = deepseek_config.get('model', 'deepseek-chat')
                logger.info(f"✅ 玄学顾问 DeepSeek LLM 初始化成功: {self.deepseek_model}")
            except Exception as e:
                logger.warning(f"⚠️ DeepSeek 初始化失败: {e}")
    
    async def analyze(self, symbol: str, interval: str, user_config: Dict = None) -> AnalysisResult:
        """执行玄学分析"""
        try:
            birth_date = user_config.get('birth_date') if user_config else None
            today = datetime.now().strftime("%Y年%m月%d日")
            today_weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()]
            
            if self.deepseek_client:
                return await self._deepseek_analysis(symbol, birth_date, today, today_weekday)
            else:
                return self._fallback_analysis(symbol, birth_date, today)
                
        except Exception as e:
            logger.error(f"玄学分析出错: {e}")
            return AnalysisResult(
                agent_type=AgentType.METAPHYSICAL,
                score=50,
                direction="neutral",
                reasoning=f"玄学分析出错：{str(e)}",
                key_observations=["分析出错"],
                data_sources=["DeepSeek AI"]
            )
    
    async def _deepseek_analysis(self, symbol: str, birth_date: str, today: str, weekday: str) -> AnalysisResult:
        """使用 DeepSeek 进行 AI 玄学分析"""
        
        # 构建系统提示
        system_prompt = """你是一位精通东西方命理学的资深玄学大师，专攻金融市场运势分析。
你精通以下领域：
- 八字命理（天干地支、五行生克）
- 西方占星术（星座、行星相位）
- 塔罗牌占卜（大阿尔卡纳、小阿尔卡纳）
- 紫微斗数
- 易经卦象
- 数字命理学

你的任务是结合用户的生辰和当天的天时，给出综合的交易运势分析。

回复格式要求（严格遵守）：
玄学评分：[0-100的数字]
交易方向：[bullish/bearish/neutral]

🔮 八字分析：
[基于用户生辰和今日天干地支的分析，2-3句话]

⭐ 星座运势：
[基于用户星座和今日星象的分析，2-3句话]

🃏 塔罗指引：
[抽取一张塔罗牌并解读，2-3句话]

📿 综合运势：
[综合所有维度给出交易建议，2-3句话]

⚠️ 吉凶时段：
[今日交易的有利和不利时段]

注意：
- 分析要结合真实的天干地支和星象知识
- 给出具体的数字评分和方向判断
- 内容既专业又通俗易懂
- 末尾加一句免责声明"""
        
        # 构建用户消息
        if birth_date:
            user_msg = f"""请为以下用户进行今日交易运势分析：

交易标的：{symbol}
用户生日：{birth_date}
今日日期：{today}（{weekday}）

请结合用户的八字、星座、以及今日的天干地支和星象，给出综合的交易建议。"""
        else:
            user_msg = f"""请进行今日交易运势分析（用户未提供生日，请基于今日天象通用分析）：

交易标的：{symbol}
今日日期：{today}（{weekday}）

请基于今日的天干地支、星象和塔罗，给出通用的交易运势分析。"""
        
        try:
            response = await self.deepseek_client.chat.completions.create(
                model=self.deepseek_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=800,
                temperature=0.8,
            )
            
            content = response.choices[0].message.content
            logger.debug(f"DeepSeek 玄学回复 ({len(content)} chars)")
            
            # 解析评分和方向
            score = 50
            direction = "neutral"
            
            score_match = re.search(r'玄学评分[：:]\s*(\d+)', content)
            if score_match:
                score = int(score_match.group(1))
                score = max(0, min(100, score))
            
            if re.search(r'交易方向[：:]\s*(bullish|看多)', content, re.IGNORECASE):
                direction = "bullish"
            elif re.search(r'交易方向[：:]\s*(bearish|看空)', content, re.IGNORECASE):
                direction = "bearish"
            elif score >= 60:
                direction = "bullish"
            elif score <= 40:
                direction = "bearish"
            
            # 提取关键观察
            observations = []
            if birth_date:
                observations.append(f"用户生日: {birth_date}")
            
            bazi_match = re.search(r'八字分析[：:]\s*\n(.+?)(?=\n\n|⭐|$)', content, re.DOTALL)
            if bazi_match:
                observations.append(f"八字: {bazi_match.group(1).strip()[:60]}")
            
            tarot_match = re.search(r'塔罗指引[：:]\s*\n(.+?)(?=\n\n|📿|$)', content, re.DOTALL)
            if tarot_match:
                observations.append(f"塔罗: {tarot_match.group(1).strip()[:60]}")
            
            # 添加数据来源标记
            reasoning = content + f"\n\n📡 数据来源：DeepSeek AI 玄学分析（真实 AI 生成，非模拟）"
            
            self.current_analysis = AnalysisResult(
                agent_type=AgentType.METAPHYSICAL,
                score=score,
                direction=direction,
                reasoning=reasoning,
                key_observations=observations,
                data_sources=["DeepSeek AI (玄学分析)"]
            )
            
            return self.current_analysis
            
        except Exception as e:
            logger.error(f"DeepSeek 调用失败: {e}")
            return self._fallback_analysis(symbol, birth_date, today)
    
    def _fallback_analysis(self, symbol: str, birth_date: str, today: str) -> AnalysisResult:
        """兜底分析（DeepSeek 不可用时）"""
        import hashlib
        seed = hashlib.md5(f"{today}{symbol}".encode()).hexdigest()
        score = 35 + int(seed[:2], 16) % 30  # 35-64
        direction = "bullish" if score >= 55 else "bearish" if score <= 42 else "neutral"
        
        reasoning = f"""基于{today}天象的通用分析 (DeepSeek 不可用)：

📊 运势评分：{score}/100 ({direction})

⚠️ DeepSeek AI 暂时不可用，使用简化算法。
建议稍后重试获取完整的 AI 玄学分析。

⚠️ 免责声明：玄学分析仅供娱乐参考，不构成投资建议。"""
        
        return AnalysisResult(
            agent_type=AgentType.METAPHYSICAL,
            score=score,
            direction=direction,
            reasoning=reasoning,
            key_observations=["DeepSeek 不可用，使用简化算法"],
            data_sources=["算法生成 (兜底)"]
        )
