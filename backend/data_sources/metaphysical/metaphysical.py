"""
玄学数据源 — 使用 DeepSeek AI 生成真实分析
替代之前的硬编码假数据
"""
import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger


class MetaphysicalDataSource:
    """玄学数据源 — DeepSeek AI 驱动"""
    
    def __init__(self, deepseek_config: Dict = None):
        self.client = None
        self.model = "deepseek-chat"
        if deepseek_config and deepseek_config.get("api_key"):
            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(
                    api_key=deepseek_config["api_key"],
                    base_url=deepseek_config.get("base_url", "https://openrouter.fans/v1"),
                )
                self.model = deepseek_config.get("model", "deepseek-chat")
                logger.info(f"✅ 玄学数据源 DeepSeek 初始化: {self.model}")
            except Exception as e:
                logger.warning(f"DeepSeek 初始化失败: {e}")
        else:
            logger.info("⚠️ 玄学数据源: 未配置 DeepSeek，数据将不可用")
    
    async def _ask_deepseek(self, system: str, user: str, max_tokens: int = 600) -> str:
        """调用 DeepSeek AI"""
        if not self.client:
            return ""
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.8,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.warning(f"DeepSeek 调用失败: {e}")
            return ""
    
    async def get_bazi_analysis(self, birth_date: str, birth_time: str, birth_place: str) -> Dict[str, Any]:
        """八字分析 — DeepSeek AI"""
        today = datetime.now().strftime("%Y年%m月%d日")
        
        content = await self._ask_deepseek(
            system="你是精通八字命理的大师。用JSON回复，包含: today_ganzhis(年月日时), wuxing_strength(金木水火土1-5), daily_fortune(wealth/career/health: 吉/平/凶), trading_advice(suitable:bool, caution:str, best_time:str), score(0-100)。",
            user=f"生日:{birth_date}, 时辰:{birth_time}, 地点:{birth_place}, 今日:{today}。请分析今日八字交易运势。",
        )
        
        if not content:
            return {"score": 50, "data_source": "unavailable", "note": "DeepSeek 不可用"}
        
        try:
            # 尝试解析JSON
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                data["data_source"] = "DeepSeek AI (八字)"
                data["timestamp"] = datetime.now().isoformat()
                return data
        except Exception:
            pass
        
        return {"score": 50, "raw": content, "data_source": "DeepSeek AI (八字)", "timestamp": datetime.now().isoformat()}
    
    async def get_ziwei_analysis(self, birth_date: str, birth_time: str) -> Dict[str, Any]:
        """紫微斗数 — DeepSeek AI"""
        today = datetime.now().strftime("%Y年%m月%d日")
        
        content = await self._ask_deepseek(
            system="你是紫微斗数大师。用JSON回复，包含: main_stars(命宫/财帛宫/事业宫), today_fortune(wealth/career/health), trading_advice(suitable:bool, caution:str, strategy:str), score(0-100)。",
            user=f"生日:{birth_date}, 时辰:{birth_time}, 今日:{today}。请分析紫微斗数交易运势。",
        )
        
        if not content:
            return {"score": 50, "data_source": "unavailable"}
        
        try:
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                data["data_source"] = "DeepSeek AI (紫微)"
                data["timestamp"] = datetime.now().isoformat()
                return data
        except Exception:
            pass
        
        return {"score": 50, "raw": content, "data_source": "DeepSeek AI (紫微)", "timestamp": datetime.now().isoformat()}
    
    async def get_astrology_analysis(self, birth_date: str, birth_time: str, birth_place: str) -> Dict[str, Any]:
        """西方占星 — DeepSeek AI"""
        today = datetime.now().strftime("%Y年%m月%d日")
        
        content = await self._ask_deepseek(
            system="你是西方占星术大师。用JSON回复，包含: sun_sign, moon_sign, planetary_positions(mercury/venus/mars状态), today_aspects, trading_advice(suitable:bool, caution:str), lucky_elements, score(0-100)。",
            user=f"生日:{birth_date}, 时辰:{birth_time}, 地点:{birth_place}, 今日:{today}。请分析占星交易运势。",
        )
        
        if not content:
            return {"score": 50, "data_source": "unavailable"}
        
        try:
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                data["data_source"] = "DeepSeek AI (占星)"
                data["timestamp"] = datetime.now().isoformat()
                return data
        except Exception:
            pass
        
        return {"score": 50, "raw": content, "data_source": "DeepSeek AI (占星)", "timestamp": datetime.now().isoformat()}
    
    async def draw_tarot(self, question: str = None) -> Dict[str, Any]:
        """塔罗牌 — DeepSeek AI"""
        content = await self._ask_deepseek(
            system="你是塔罗牌大师。请为用户抽取一张大阿尔卡纳牌并解读。用JSON回复，包含: card(name, position:正位/逆位, meaning), interpretation, advice, score(0-100)。",
            user=f"问题: {question or '今日交易运势如何？'}",
            max_tokens=400,
        )
        
        if not content:
            return {"score": 50, "data_source": "unavailable"}
        
        try:
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                data["question"] = question or "今日交易运势如何？"
                data["data_source"] = "DeepSeek AI (塔罗)"
                data["timestamp"] = datetime.now().isoformat()
                return data
        except Exception:
            pass
        
        return {"score": 50, "raw": content, "question": question, "data_source": "DeepSeek AI (塔罗)", "timestamp": datetime.now().isoformat()}
    
    async def get_comprehensive_metaphysical_analysis(
        self, birth_date: str = None, birth_time: str = None, birth_place: str = None
    ) -> Dict[str, Any]:
        """综合玄学分析 — 全部由 DeepSeek AI 驱动"""
        results = {}
        
        if birth_date and birth_time:
            bazi, ziwei, astrology = await asyncio.gather(
                self.get_bazi_analysis(birth_date, birth_time, birth_place or "未知"),
                self.get_ziwei_analysis(birth_date, birth_time),
                self.get_astrology_analysis(birth_date, birth_time, birth_place or "未知"),
                return_exceptions=True,
            )
            results["bazi"] = bazi if not isinstance(bazi, Exception) else None
            results["ziwei"] = ziwei if not isinstance(ziwei, Exception) else None
            results["astrology"] = astrology if not isinstance(astrology, Exception) else None
        
        tarot = await self.draw_tarot("今日交易运势如何？")
        results["tarot"] = tarot
        
        scores = [r.get("score", 50) for r in [results.get("bazi"), results.get("ziwei"), results.get("astrology"), results.get("tarot")] if r]
        overall = sum(scores) / len(scores) if scores else 50
        
        results["overall_score"] = overall
        results["timestamp"] = datetime.now().isoformat()
        results["data_source"] = "DeepSeek AI"
        
        return results
