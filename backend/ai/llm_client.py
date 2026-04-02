"""
LLM Client - 统一的大模型调用封装
支持 Anthropic 协议 (Claude) 和 OpenAI 协议
"""
import asyncio
from typing import List, Dict, Optional
from loguru import logger


class LLMClient:
    """LLM 客户端 — 自动检测协议"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://gpt-agent.cc",
        model: str = "claude-sonnet-4-6",
        max_retries: int = 3,
        retry_delay: float = 2.0,
        protocol: str = "auto",
    ):
        self.model = model
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # 自动检测协议: claude 模型用 Anthropic，其他用 OpenAI
        use_anthropic = (
            protocol == "anthropic"
            or (protocol == "auto" and "claude" in model.lower())
        )
        
        if use_anthropic:
            from anthropic import AsyncAnthropic
            self.protocol = "anthropic"
            self.client = AsyncAnthropic(
                api_key=api_key,
                base_url=base_url,
                timeout=90.0,
            )
        else:
            from openai import AsyncOpenAI
            self.protocol = "openai"
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=90.0,
            )
        
        logger.info(f"LLM Client 初始化: model={model}, protocol={self.protocol}, base_url={base_url}")
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> str:
        """发送对话请求，返回文本回复"""
        
        for attempt in range(self.max_retries):
            try:
                if self.protocol == "anthropic":
                    return await self._chat_anthropic(messages, max_tokens, temperature, system_prompt)
                else:
                    return await self._chat_openai(messages, max_tokens, temperature, system_prompt)
                    
            except Exception as e:
                error_str = str(e)
                is_retryable = any(k in error_str.lower() for k in ['429', 'rate', 'overloaded', '529', '500', '503'])
                
                if is_retryable and attempt < self.max_retries - 1:
                    wait = self.retry_delay * (2 ** attempt)
                    logger.warning(f"LLM 调用失败 ({error_str[:60]}), {wait:.1f}s 后重试 ({attempt+1}/{self.max_retries})")
                    await asyncio.sleep(wait)
                    continue
                elif attempt < self.max_retries - 1:
                    logger.warning(f"LLM 调用失败: {error_str[:80]}，重试 ({attempt+1}/{self.max_retries})")
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    logger.error(f"LLM 调用最终失败: {e}")
                    raise

    async def _chat_anthropic(self, messages, max_tokens, temperature, system_prompt):
        """Anthropic 协议调用"""
        # 分离 system prompt 和 user/assistant messages
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                if not system_prompt:
                    system_prompt = msg["content"]
            else:
                user_messages.append(msg)
        
        if not user_messages:
            user_messages = [{"role": "user", "content": "请回复"}]
        
        kwargs = {
            "model": self.model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        
        response = await self.client.messages.create(**kwargs)
        # Handle ThinkingBlock + TextBlock (extended thinking models)
        # Collect ALL text from text blocks
        text_parts = []
        for block in response.content:
            if getattr(block, 'type', '') == 'text' and getattr(block, 'text', ''):
                text_parts.append(block.text)
        
        content = '\n'.join(text_parts) if text_parts else ''
        
        if not content:
            # Fallback: try any block with text attribute
            for block in response.content:
                t = getattr(block, 'text', None)
                if t:
                    content = t
                    break
        
        if not content:
            # Retry once with slightly different temperature
            logger.warning(f"Anthropic 返回空内容，重试一次...")
            try:
                kwargs['temperature'] = min((kwargs.get('temperature', 0.7) + 0.1), 1.0)
                retry_response = await self.client.messages.create(**kwargs)
                for block in retry_response.content:
                    if getattr(block, 'type', '') == 'text' and getattr(block, 'text', ''):
                        content = block.text
                        break
            except Exception:
                pass
        
        if not content:
            logger.warning(f"Anthropic 返回空内容: {[type(b).__name__ for b in response.content]}")
            content = "暂无分析结果"
        
        logger.debug(f"LLM 回复 ({len(content)} chars): {content[:80]}...")
        return content

    async def _chat_openai(self, messages, max_tokens, temperature, system_prompt):
        """OpenAI 协议调用"""
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        
        # Handle proxy response format issues
        if isinstance(response, str):
            logger.warning(f"OpenAI proxy returned raw string ({len(response)} chars)")
            return response
        
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as e:
            # Try to extract content from response object
            if hasattr(response, 'text'):
                content = response.text
            elif hasattr(response, 'content'):
                content = str(response.content)
            else:
                content = str(response)
            logger.warning(f"OpenAI response format unexpected: {e}, extracted {len(content)} chars")
        
        logger.debug(f"LLM 回复 ({len(content)} chars): {content[:80]}...")
        return content
    
    async def analyze_as_agent(self, agent_name, agent_personality, data_summary, symbol):
        """以特定 Agent 身份进行分析"""
        system_prompt = f"""你是「{agent_name}」，一位专业的加密货币交易分析师。
你的性格特点：{agent_personality}

你的任务是基于提供的数据，给出专业的市场分析意见。
分析要求：简洁有力，重点突出，给出明确的方向判断（看多/看空/中性），用数据支撑观点，300字以内。"""

        return await self.chat(
            messages=[{"role": "user", "content": f"请分析 {symbol} 的当前市况。以下是你获取到的数据：\n\n{data_summary}"}],
            system_prompt=system_prompt,
            max_tokens=1000,
            temperature=0.7,
        )
    
    async def discuss_as_agent(self, agent_name, agent_personality, own_analysis, other_analyses, symbol):
        """以特定 Agent 身份参与圆桌讨论"""
        others_text = "\n\n".join([
            f"【{a['name']}】评分 {a['score']}/100，方向 {a['direction']}：\n{a['reasoning'][:200]}"
            for a in other_analyses
        ])
        
        system_prompt = f"""你是「{agent_name}」，正在参与一场多专家圆桌讨论。
你的性格特点：{agent_personality}

讨论规则：
- 站在你的专业角度发言
- 如果你和其他专家观点不同，直接指出分歧并解释原因
- 如果某个专家的观点有漏洞，礼貌但直接地指出
- 如果你认同某个观点，也说明为什么
- 150字以内，像真正的讨论一样自然"""

        return await self.chat(
            messages=[{"role": "user", "content": f"当前讨论标的：{symbol}\n\n你的分析结论：\n{own_analysis}\n\n其他专家的观点：\n{others_text}\n\n请发表你的讨论意见："}],
            system_prompt=system_prompt,
            max_tokens=800,
            temperature=0.8,
        )
    
    async def moderate_decision(self, all_analyses, symbol, user_opinion=None, discussion_summary=None):
        """作为主持人综合各方观点做最终决策"""
        analyses_text = "\n\n".join([
            f"【{a['name']}】\n评分：{a['score']}/100\n方向：{a['direction']}\n分析：{a['reasoning'][:300]}"
            + (f"\n入场价：${a.get('entry_price', 'N/A')}, 止盈：${a.get('exit_price', 'N/A')}, 止损：${a.get('stop_loss', 'N/A')}, 杠杆：{a.get('leverage', 'N/A')}x" if a.get('entry_price') else "")
            for a in all_analyses
        ])
        
        user_note = f"\n\n💬 用户自己的交易意见：{user_opinion}\n请在决策中充分考虑用户的意见，但也要保持专业判断。" if user_opinion else ""
        
        # 第二阶段讨论摘要
        discussion_note = ""
        if discussion_summary:
            # 截取前1500字，避免token过长
            truncated = discussion_summary[:1500]
            discussion_note = f"\n\n===== 第二阶段：专家讨论要点 =====\n{truncated}\n===== 讨论结束 ====="
        
        # Calculate weighted score to guide LLM
        weights = {'technical': 0.30, 'onchain': 0.25, 'macro': 0.20, 'sentiment': 0.15, 'metaphysical': 0.10}
        weighted_score = 0
        total_weight = 0
        for a in all_analyses:
            w = weights.get(a['name'], 0.1)
            weighted_score += a['score'] * w
            total_weight += w
        if total_weight > 0:
            weighted_score = round(weighted_score / total_weight, 1)
        
        system_prompt = f"""你是一位果断的交易决策主持人。你必须综合所有专家意见，给出明确的交易决策。

重要规则：
1. 不要简单平均各专家评分！技术分析权重30%，链上分析权重25%，宏观分析权重20%，情绪分析权重15%，玄学分析权重10%
2. 加权参考评分约为 {weighted_score}/100，你的最终评分应该在此基础上根据分析质量调整
3. 如果有任何专家评分>70或<30，说明存在强信号，最终评分应该倾向该方向，不能简单给50-55中性
4. 只有当各方真正势均力敌、且没有任何突出信号时，才可以给neutral
5. 如果最终方向是neutral，必须提供震荡区间交易策略
6. ⚠️ 你必须同时参考"第一阶段独立分析"和"第二阶段专家讨论"。讨论中专家可能提出了新的论据、质疑或补充信息，这些都应该影响你的最终判断

严格按以下JSON格式返回（不要markdown标记）：
{{"score": 数字0-100, "direction": "bullish或bearish或neutral", "reasoning": "100字以内的决策理由", "range_high": 数字或null, "range_low": 数字或null}}"""

        response = await self.chat(
            messages=[{"role": "user", "content": f"标的：{symbol}\n\n===== 第一阶段：各专家独立分析 =====\n{analyses_text}{discussion_note}{user_note}\n\n请综合第一阶段分析和第二阶段讨论内容，给出最终决策："}],
            system_prompt=system_prompt,
            max_tokens=500,
            temperature=0.3,
        )
        return self._parse_decision(response)
    
    def _parse_decision(self, text):
        """解析主持人决策 — 支持JSON和文本格式"""
        import re
        
        # Try JSON first (new format)
        json_match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if json_match:
            try:
                import json as _json
                data = _json.loads(json_match.group())
                score = float(data.get('score', 50))
                score = max(0, min(100, score))
                direction = data.get('direction', 'neutral')
                if direction not in ('bullish', 'bearish', 'neutral'):
                    if score >= 60: direction = 'bullish'
                    elif score <= 40: direction = 'bearish'
                    else: direction = 'neutral'
                result = {
                    "score": score,
                    "direction": direction,
                    "reasoning": data.get('reasoning', text[:200]),
                }
                if data.get('range_high'):
                    result['range_high'] = data['range_high']
                if data.get('range_low'):
                    result['range_low'] = data['range_low']
                return result
            except Exception:
                pass
        
        # Fallback: regex parsing (old text format)
        score_match = re.search(r'(?:最终)?评分[：:\s]*(\d+(?:\.\d+)?)', text)
        score = float(score_match.group(1)) if score_match else 50.0
        score = max(0, min(100, score))
        
        direction = "neutral"
        dir_match = re.search(r'(?:最终)?方向[：:\s]*(bullish|bearish|neutral|看多|看空|中性)', text, re.IGNORECASE)
        if dir_match:
            d = dir_match.group(1).lower()
            if d in ('bullish', '看多'): direction = 'bullish'
            elif d in ('bearish', '看空'): direction = 'bearish'
        elif score >= 60:
            direction = "bullish"
        elif score <= 40:
            direction = "bearish"
        
        reason_match = re.search(r'(?:决策)?理由[：:\s]*(.+)', text, re.DOTALL)
        reasoning = reason_match.group(1).strip()[:200] if reason_match else text[:200]
        
        return {"score": score, "direction": direction, "reasoning": reasoning}