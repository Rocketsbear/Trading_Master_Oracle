"""
FastAPI 主入口 - V2.0
多Agent协作系统 + WebSocket实时推送
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import asyncio
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import uvicorn

from backend.agents import AgentOrchestrator
from backend.risk.risk_manager import RiskManager
from backend.trading.position_manager import PositionManager
from backend.trading.price_monitor import PriceMonitor
from backend.trading.reflection_engine import ReflectionEngine
from backend.trading.evolution_rules import EvolutionEngine
from backend.ai.llm_client import LLMClient
from backend.trading.crisis_scorer import detect_crisis_mode, run_crisis_cycle


# 初始化 FastAPI 应用
app = FastAPI(
    title="Trading Oracle API",
    description="AI 驱动的多Agent协作交易决策系统",
    version="2.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 加载配置
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), '../config/api_keys.json')
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"无法加载配置文件: {e}")
    return {}

config = load_config()

# 初始化 Agent Orchestrator
orchestrator = AgentOrchestrator(config={
    'fred_api_key': config.get('fred', {}).get('api_key'),
    'jwt_token': config.get('6551', {}).get('jwt_token'),
    'agent_llm': config.get('agent_llm', {}),
    'deepseek': config.get('deepseek', {}),
    'onchainos': config.get('onchainos', {}),
})

# 初始化风险管理引擎
paper_balance = config.get('paper_trading', {}).get('balance', 10000)
risk_manager = RiskManager(config={
    'max_risk_per_trade': 0.02,    # 单笔最大风险 2%
    'max_daily_loss': 0.05,        # 每日最大亏损 5%
    'max_leverage': 5,             # 最大杠杆 5x
    'min_rr_ratio': 1.5,           # 最小盈亏比 1.5:1
    'account_balance': paper_balance,  # 从config读取，默认10000
})

# 初始化持仓管理器 + 价格监控
position_manager = PositionManager()
price_monitor = PriceMonitor(
    position_manager=position_manager,
    risk_manager=risk_manager,
    ws_broadcast=None,  # Will be set after manager is available
    on_close=None,  # Will be set after reflection engine is available
)

# 初始化自我进化系统
try:
    agent_llm_cfg = config.get('agent_llm', {})
    reflection_base_url = agent_llm_cfg.get('base_url', 'https://gpt-agent.cc')
    # Ensure /v1 suffix for OpenAI-compatible APIs
    if not reflection_base_url.endswith('/v1'):
        reflection_base_url = reflection_base_url.rstrip('/') + '/v1'
    
    reflection_llm = LLMClient(
        api_key=agent_llm_cfg.get('api_key', ''),
        base_url=reflection_base_url,
        model=agent_llm_cfg.get('model', 'MiniMax-M2.5-highspeed'),
        protocol=agent_llm_cfg.get('protocol', 'anthropic'),
    )
except Exception as e:
    logger.warning(f"反思 LLM 初始化失败: {e}")
    reflection_llm = None

reflection_engine = ReflectionEngine(llm_client=reflection_llm)
evolution_engine = EvolutionEngine()


# 交易关闭时自动触发反思
async def on_trade_close(event: dict):
    """持仓关闭时自动触发 LLM 反思 + 进化规则更新"""
    try:
        # Get full trade data from history
        pos_id = event.get('position_id', '')
        history = position_manager.get_history(10)
        trade = None
        for t in reversed(history):
            if t.get('id') == pos_id:
                trade = t
                break
        
        if not trade:
            trade = event  # Fallback to event data
        
        # Run LLM reflection
        reflection = await reflection_engine.reflect_on_trade(trade)
        
        if reflection:
            # Update evolution rules based on reflection
            evolution_engine.update_from_reflection(reflection)
            
            # Broadcast reflection to frontend
            try:
                await manager.broadcast({
                    "type": "reflection",
                    "reflection": {
                        "trade_id": reflection.get('trade_id'),
                        "symbol": reflection.get('symbol'),
                        "pnl": reflection.get('pnl'),
                        "root_cause": reflection.get('root_cause'),
                        "lesson": reflection.get('lesson'),
                        "pattern": reflection.get('pattern'),
                    },
                    "timestamp": datetime.now().isoformat(),
                })
                # Also push evolution rule updates
                evo_stats = evolution_engine.get_stats()
                await manager.broadcast({
                    "type": "evolution_update",
                    "active_rules": [r.to_dict() for r in evolution_engine.rules if r.confidence >= 0.3],
                    "stats": evo_stats,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"反思处理失败: {e}")


# 请求模型
class AnalyzeRequest(BaseModel):
    symbol: str
    interval: str = "1h"
    birth_date: Optional[str] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    user_config: Optional[Dict] = None


# WebSocket连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket连接数: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket连接数: {len(self.active_connections)}")
    
    async def send_message(self, message: Dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
    
    async def broadcast(self, message: Dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()


@app.on_event("startup")
async def startup_event():
    """应用启动时启动价格监控"""
    # Set WebSocket broadcast function
    price_monitor.ws_broadcast = manager.broadcast
    # Set reflection callback
    price_monitor.on_close = on_trade_close
    # Start background price monitor
    asyncio.create_task(price_monitor.start())
    logger.info("✅ 后台价格监控已启动 (每3秒检查 TP/SL/Trailing)")
    logger.info(f"🧠 自我进化系统: {len(reflection_engine.reflections)}条反思, {len(evolution_engine.rules)}条规则")
    
    # 🔄 自动恢复托管循环
    if managed_state.get("running") and managed_state.get("task") is None:
        logger.info(f"🔄 检测到未完成的托管会话，自动恢复: {managed_state.get('symbol')} | 周期{managed_state.get('cycles')}")
        managed_state["task"] = asyncio.create_task(_managed_loop())
        risk_manager.update_balance(managed_state.get("account_balance", 10000))


@app.get("/")
async def root():
    """API 根端点"""
    return {
        "name": "Trading Oracle API",
        "status": "online",
        "version": "2.0.0",
        "agents": [agent['name'] for agent in orchestrator.get_agent_status()]
    }


@app.get("/api/health")
async def health_check():
    """系统健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "agents": orchestrator.get_agent_status(),
        "services": {
            "technical": "ok",
            "onchain": "ok", 
            "macro": "ok" if config.get('fred', {}).get('api_key') else "simulated",
            "sentiment": "ok",
            "metaphysical": "ok"
        }
    }


@app.get("/api/agents/status")
async def get_agent_status():
    """获取所有Agent状态"""
    return {
        "success": True,
        "agents": orchestrator.get_agent_status()
    }


# 多交易所数据源（全局复用）
from backend.data_sources.market.exchange_data import ExchangeDataSource
_exchange_data = ExchangeDataSource()


@app.get("/api/long-short")
async def get_long_short_data(symbol: str = "BTCUSDT"):
    """获取实时多空比 + OI + 资金费率 (前端轮询)"""
    try:
        data = await _exchange_data.get_comprehensive_exchange_data(symbol)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"获取多空比数据失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/settings")
async def save_settings(settings: Dict):
    """保存用户设置 (交易所 API Key 等)"""
    import json
    config_path = os.path.join(os.path.dirname(__file__), '../config/api_keys.json')
    try:
        # 读取现有配置
        with open(config_path, 'r', encoding='utf-8') as f:
            current = json.load(f)
        
        # 更新交易所配置
        for exchange in ['binance', 'okx', 'bybit', 'hyperliquid']:
            if exchange in settings:
                current[exchange] = {**current.get(exchange, {}), **settings[exchange]}
        
        # 保存模拟交易设置
        if 'paper_trading' in settings:
            current['paper_trading'] = settings['paper_trading']
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        
        return {"success": True, "message": "设置已保存"}
    except Exception as e:
        logger.error(f"保存设置失败: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/settings")
async def get_settings():
    """获取当前设置 (API Key 做脱敏)"""
    masked = {}
    for exchange in ['binance', 'okx', 'bybit', 'hyperliquid']:
        ex_cfg = config.get(exchange, {})
        masked[exchange] = {}
        for k, v in ex_cfg.items():
            if 'key' in k.lower() or 'secret' in k.lower() or 'pass' in k.lower():
                masked[exchange][k] = f"{'*' * 6}{v[-4:]}" if v and len(v) > 4 else ""
            else:
                masked[exchange][k] = v
    masked['paper_trading'] = config.get('paper_trading', {'enabled': True, 'balance': 10000})
    return {"success": True, "data": masked}


@app.get("/api/klines")
async def get_klines(exchange: str = "binance", symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200, market_type: str = "spot"):
    """获取K线数据 — 支持多交易所 + 现货/合约 (binance/okx/bybit/hyperliquid)"""
    try:
        data = await _exchange_data.get_klines(exchange, symbol, interval, limit, market_type)
        if data:
            return {"success": True, "exchange": exchange, "market_type": market_type, "count": len(data), "data": data}
        return {"success": False, "error": f"无法从 {exchange} 获取 {market_type} K线数据"}
    except Exception as e:
        logger.error(f"获取K线失败 [{exchange}/{market_type}]: {e}")
        return {"success": False, "error": str(e)}


from pydantic import BaseModel
from typing import Optional as Opt

class ChatRequest(BaseModel):
    message: str
    history: list = []

class ReDeliberateRequest(BaseModel):
    opinion: str

class TradeRequest(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTCUSDT"
    side: str = "buy"  # buy/sell
    amount: float = 0.001
    leverage: int = 1
    paper: bool = True


@app.post("/api/chat")
async def chat_with_llm(req: ChatRequest):
    """与 AI 对话 — 自动路由到对应专家 Agent"""
    try:
        msg_lower = req.message.lower()
        
        # 检测用户是否想与特定 agent 对话
        AGENT_KEYWORDS = {
            "metaphysical": ["玄学", "命理", "塔罗", "八字", "星座", "运势", "占卜", "风水"],
            "technical": ["技术", "k线", "macd", "rsi", "布林", "均线", "指标"],
            "onchain": ["链上", "巨鲸", "聪明钱", "dex", "whale", "链上分析"],
            "macro": ["宏观", "经济", "gdp", "通胀", "利率", "fed", "美联储"],
            "sentiment": ["情绪", "新闻", "舆情", "twitter", "社交", "news"],
        }
        
        routed_agent = None
        for agent_key, keywords in AGENT_KEYWORDS.items():
            if any(kw in msg_lower for kw in keywords):
                routed_agent = agent_key
                break
        
        # 路由到玄学专家 (使用 DeepSeek)
        if routed_agent == "metaphysical":
            from backend.agents.base_agent import AgentType
            meta_agent = orchestrator.agents.get(AgentType.METAPHYSICAL)
            if meta_agent and meta_agent.deepseek_client:
                # 用 DeepSeek 直接对话
                analysis_ctx = ""
                if meta_agent.current_analysis:
                    r = meta_agent.current_analysis
                    analysis_ctx = f"\n\n你之前的分析：评分{r.score}, 方向{r.direction}\n{r.reasoning[:200]}"
                
                msgs = [{"role": "system", "content": f"""你是「玄学顾问」，精通八字、星座、塔罗牌、运势命理。
你正在与用户进行一对一交流，帮助他们从玄学角度理解交易时机。
用你的玄学知识给出建议，保持神秘而专业的风格。用中文回复。{analysis_ctx}"""}]
                for h in req.history[-10:]:
                    msgs.append({"role": h.get("role", "user"), "content": h.get("content", "")})
                msgs.append({"role": "user", "content": req.message})
                
                resp = await meta_agent.deepseek_client.chat.completions.create(
                    model=meta_agent.deepseek_model,
                    messages=msgs,
                    max_tokens=800,
                    temperature=0.8,
                )
                response = resp.choices[0].message.content
                return {"success": True, "response": f"🔮 **玄学顾问频道**\n\n{response}", "agent": "metaphysical"}
            else:
                return {"success": False, "error": "玄学顾问 DeepSeek 未配置"}
        
        # 路由到其他专家 (使用默认 LLM + 专家人格)
        if routed_agent and routed_agent != "metaphysical":
            from backend.agents.base_agent import AgentType
            agent_type_map = {
                "technical": AgentType.TECHNICAL,
                "onchain": AgentType.ONCHAIN,
                "macro": AgentType.MACRO,
                "sentiment": AgentType.SENTIMENT,
            }
            agent_type = agent_type_map.get(routed_agent)
            agent = orchestrator.agents.get(agent_type)
            
            if agent:
                llm = orchestrator.llm or (agent.llm if hasattr(agent, 'llm') else None)
                if llm:
                    analysis_ctx = ""
                    if agent.current_analysis:
                        r = agent.current_analysis
                        analysis_ctx = f"\n\n你之前的分析：评分{r.score}, 方向{r.direction}\n{r.reasoning[:200]}"
                    
                    agent_icons = {"technical": "📊", "onchain": "⛓️", "macro": "🌍", "sentiment": "💬"}
                    messages = [
                        {"role": "system", "content": f"""你是「{agent.name}」，{agent.personality}。
你正在与用户进行专业对话。用中文回复，简洁专业。{analysis_ctx}"""},
                    ]
                    for h in req.history[-10:]:
                        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
                    messages.append({"role": "user", "content": req.message})
                    
                    response = await llm.chat(messages)
                    icon = agent_icons.get(routed_agent, "🤖")
                    return {"success": True, "response": f"{icon} **{agent.name}频道**\n\n{response}", "agent": routed_agent}
        
        # 默认：通用 AI 助手
        llm = orchestrator.llm
        if not llm:
            return {"success": False, "error": "LLM 未配置"}
        
        context_parts = []
        for agent_type, agent in orchestrator.agents.items():
            if agent.current_analysis:
                r = agent.current_analysis
                ctx = f"{agent.name}: 评分{r.score}, {r.direction}"
                if r.entry_price:
                    ctx += f", 入场${r.entry_price:,.2f}, 止盈${r.exit_price:,.2f}, 止损${r.stop_loss:,.2f}, 杠杆{r.leverage}x"
                context_parts.append(ctx)
        
        context = "\n".join(context_parts) if context_parts else "暂无分析数据"
        
        messages = [
            {"role": "system", "content": f"""你是 Trading Oracle 的交易AI助手。你可以帮用户分析市场、讨论交易策略。
当前系统中各专家的分析结果：
{context}

用户可以说"转接玄学专家"、"问问技术分析师"等来切换到特定专家频道。
请根据用户的问题给出专业、简洁的回答。用中文回复。"""},
        ]
        
        for h in req.history[-10:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": req.message})
        
        response = await llm.chat(messages)
        return {"success": True, "response": response}
    except Exception as e:
        logger.error(f"Chat 失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/re-deliberate")
async def re_deliberate(req: ReDeliberateRequest):
    """用户注入意见 → 重新评议"""
    try:
        result = await orchestrator.run_re_deliberation(req.opinion)
        return result
    except Exception as e:
        logger.error(f"重新评议失败: {e}")
        return {"success": False, "error": str(e)}


# Old /api/trade/execute removed — see comprehensive version below (line ~892)


@app.websocket("/ws/analyze")
async def websocket_analyze(websocket: WebSocket):
    """WebSocket端点 - 实时分析"""
    await manager.connect(websocket)
    
    try:
        # 等待客户端发送请求
        data = await websocket.receive_json()
        
        symbol = data.get('symbol', 'BTCUSDT')
        interval = data.get('interval', '1h')
        user_config = data.get('user_config', {})
        
        logger.info(f"收到WebSocket分析请求: {symbol} {interval}")
        
        # 运行分析
        result = await orchestrator.run_analysis(
            symbol=symbol,
            interval=interval,
            user_config=user_config,
            websocket=websocket
        )
        
        # 存储深度分析结果到 managed_state，使托管循环能参考圆桌结论
        if result.get("success") and result.get("final_decision"):
            fd = result["final_decision"]
            managed_state["deep_bias"] = {
                "direction": fd.get("direction", "neutral"),
                "score": fd.get("score", 50),
                "entry_price": fd.get("entry_price"),
                "exit_price": fd.get("exit_price"),
                "stop_loss": fd.get("stop_loss"),
                "leverage": fd.get("leverage"),
                "reasoning": fd.get("reasoning", "")[:200],
                "timestamp": datetime.now().isoformat(),
            }
            logger.info(f"🎯 深度分析结果已保存到托管状态: {fd.get('direction')} {fd.get('score')}/100")
        
        # 发送完成消息
        await websocket.send_json({
            "type": "complete",
            "data": result
        })
        
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        await websocket.send_json({
            "type": "error",
            "message": str(e)
        })
        manager.disconnect(websocket)


class QuickAnalyzeRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "15m"
    use_llm: bool = True
    deep_bias: Optional[Dict] = None  # Last deep analysis result
    account_balance: Optional[float] = None  # User's paper trading balance
    risk_pct: Optional[float] = None  # User's risk % per trade


@app.post("/api/quick-analyze")
async def quick_analyze(req: QuickAnalyzeRequest):
    """快速分析端点 — 技术指标 + 可选单次LLM，<10秒返回"""
    try:
        import httpx
        
        # 1. Fetch MULTI-TIMEFRAME K-line data in parallel
        symbol = req.symbol.upper()
        # 1. Fetch MULTI-TIMEFRAME K-line data + Fear Greed Index
        symbol = req.symbol.upper()
        
        # Parallel fetch from unifying OKX-first source
        kline_15m_task = _exchange_data.get_klines_with_fallback(symbol, req.interval, 100)
        kline_1h_task = _exchange_data.get_klines_with_fallback(symbol, "1h", 50)
        kline_4h_task = _exchange_data.get_klines_with_fallback(symbol, "4h", 30)
        
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            fng_task = client.get("https://api.alternative.me/fng/?limit=1")
            
            klines_raw, klines_1h, klines_4h, fng_resp = await asyncio.gather(
                kline_15m_task, kline_1h_task, kline_4h_task, fng_task, return_exceptions=True
            )
        
        klines_raw = klines_raw if not isinstance(klines_raw, Exception) else []
        klines_1h = klines_1h if not isinstance(klines_1h, Exception) else []
        klines_4h = klines_4h if not isinstance(klines_4h, Exception) else []
        
        # Parse Fear & Greed Index
        fng_value = 50
        fng_label = "Neutral"
        try:
            if not isinstance(fng_resp, Exception):
                fng_data = fng_resp.json()
                if fng_data.get("data"):
                    fng_value = int(fng_data["data"][0]["value"])
                    fng_label = fng_data["data"][0]["value_classification"]
        except Exception:
            pass
        
        if not klines_raw or not isinstance(klines_raw, list):
            return {"success": False, "error": "无法获取K线数据"}
        
        # 2. Parse price data
        opens = [float(k[1]) for k in klines_raw]
        closes = [float(k[4]) for k in klines_raw]
        highs = [float(k[2]) for k in klines_raw]
        lows = [float(k[3]) for k in klines_raw]
        volumes = [float(k[5]) for k in klines_raw]
        current_price = closes[-1]
        
        closes_1h = [float(k[4]) for k in klines_1h] if klines_1h else closes
        closes_4h = [float(k[4]) for k in klines_4h] if klines_4h else closes
        
        # === HELPER FUNCTIONS ===
        def calc_rsi(prices, period=14):
            if len(prices) < period + 1: return 50
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d if d > 0 else 0 for d in deltas[-period:]]
            losses = [-d if d < 0 else 0 for d in deltas[-period:]]
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0: return 100
            return 100 - (100 / (1 + avg_gain / avg_loss))
        
        def calc_ema(prices, period):
            if len(prices) < period: return prices[-1]
            ema = sum(prices[:period]) / period
            multiplier = 2 / (period + 1)
            for p in prices[period:]:
                ema = (p - ema) * multiplier + ema
            return ema
        
        def calc_adx(highs, lows, closes, period=14):
            """ADX: trend strength indicator. >25 = trending, <20 = ranging"""
            if len(highs) < period + 2: return 20
            plus_dm, minus_dm, tr_list = [], [], []
            for i in range(1, len(highs)):
                high_diff = highs[i] - highs[i-1]
                low_diff = lows[i-1] - lows[i]
                plus_dm.append(max(high_diff, 0) if high_diff > low_diff else 0)
                minus_dm.append(max(low_diff, 0) if low_diff > high_diff else 0)
                tr_list.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
            if len(tr_list) < period: return 20
            atr = sum(tr_list[-period:]) / period
            if atr == 0: return 20
            plus_di = 100 * sum(plus_dm[-period:]) / period / atr
            minus_di = 100 * sum(minus_dm[-period:]) / period / atr
            dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
            return round(dx, 1)
        
        def trend_direction(prices, ema_short=20, ema_long=50):
            """Returns: 1 = bullish, -1 = bearish, 0 = neutral"""
            if len(prices) < ema_long: return 0
            ema_s = calc_ema(prices, ema_short)
            ema_l = calc_ema(prices, ema_long)
            if ema_s > ema_l * 1.001: return 1
            elif ema_s < ema_l * 0.999: return -1
            return 0
        
        # === CALCULATE ALL INDICATORS ===
        rsi = round(calc_rsi(closes), 1)
        ema12 = calc_ema(closes, 12)
        ema26 = calc_ema(closes, 26)
        macd_line = ema12 - ema26
        
        # MACD histogram (approximate signal line)
        macd_values = []
        for i in range(max(26, 1), len(closes)):
            e12 = calc_ema(closes[:i+1], 12)
            e26 = calc_ema(closes[:i+1], 26)
            macd_values.append(e12 - e26)
        macd_signal = calc_ema(macd_values, 9) if len(macd_values) >= 9 else macd_line
        macd_histogram = macd_line - macd_signal
        macd_hist_growing = len(macd_values) >= 2 and abs(macd_values[-1]) > abs(macd_values[-2])
        
        ma7 = sum(closes[-7:]) / 7
        ma25 = sum(closes[-25:]) / 25 if len(closes) >= 25 else ma7
        ma99 = sum(closes[-99:]) / 99 if len(closes) >= 99 else ma25
        
        # Bollinger Bands
        bb_period = min(20, len(closes))
        bb_closes = closes[-bb_period:]
        bb_sma = sum(bb_closes) / bb_period
        bb_std = (sum((c - bb_sma)**2 for c in bb_closes) / bb_period) ** 0.5
        bb_upper = bb_sma + 2 * bb_std
        bb_lower = bb_sma - 2 * bb_std
        bb_position = round((current_price - bb_lower) / (bb_upper - bb_lower) * 100, 1) if bb_upper != bb_lower else 50
        
        # ADX (trend strength)
        adx = calc_adx(highs, lows, closes)
        
        # Multi-timeframe trends
        trend_15m = trend_direction(closes, 20, 50)
        trend_1h = trend_direction(closes_1h, 20, 50)
        trend_4h = trend_direction(closes_4h, 20, 50)
        
        # Volume
        vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
        vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 1
        
        # Price changes
        price_change_1h = round((closes[-1] / closes[-5] - 1) * 100, 2) if len(closes) >= 5 else 0
        price_change_4h = round((closes[-1] / closes[-17] - 1) * 100, 2) if len(closes) >= 17 else 0
        
        # ATR
        atr_approx = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
        
        # === NEW SCORING ENGINE: Triple Confirmation ===
        tech_score = 50  # Start neutral
        score_breakdown = []
        
        # --- LAYER 1: TREND (±20 max) — V4: 4H dominant weighting ---
        trend_score = 0
        # V4: Top traders weight higher timeframes more: 4H is king, 1H confirms, 15m is noise
        trend_score += trend_15m * 4   # 15m: noise, low weight
        trend_score += trend_1h * 6    # 1h: confirmation
        trend_score += trend_4h * 10   # 4h: dominant signal
        
        # V4: Cross-timeframe analysis (improved: only penalize true bull/bear conflicts)
        non_zero_trends = [t for t in [trend_15m, trend_1h, trend_4h] if t != 0]
        trends_agree = len(non_zero_trends) >= 2 and len(set(non_zero_trends)) == 1
        has_conflict = (1 in [trend_15m, trend_1h, trend_4h]) and (-1 in [trend_15m, trend_1h, trend_4h])
        
        if trends_agree and len(non_zero_trends) == 3:
            trend_score = int(trend_score * 1.2)  # V4: Full 3-way alignment bonus
            score_breakdown.append(f"三框架共振x1.2")
        elif has_conflict and abs(trend_score) > 5:
            penalty = int(abs(trend_score) * 0.4)
            trend_score = trend_score - penalty if trend_score > 0 else trend_score + penalty
            score_breakdown.append(f"时间框架冲突(-{penalty})")
        
        trend_score = max(-20, min(20, trend_score))
        tech_score += trend_score
        if trend_score > 0:
            score_breakdown.append(f"趋势层+{trend_score}(15m:{'+' if trend_15m>0 else '-' if trend_15m<0 else '='},1h:{'+' if trend_1h>0 else '-' if trend_1h<0 else '='},4h:{'+' if trend_4h>0 else '-' if trend_4h<0 else '='})")
        elif trend_score < 0:
            score_breakdown.append(f"趋势层{trend_score}")
        
        # --- V4: PRICE STRUCTURE ANALYSIS (HH/HL/LL/LH, ±5) ---
        swing_lookback = min(60, len(closes))
        recent_highs = [highs[-i] for i in range(1, swing_lookback, 4)]
        recent_lows = [lows[-i] for i in range(1, swing_lookback, 4)]
        hh_count, ll_count = 0, 0
        for i in range(1, min(5, len(recent_highs))):
            if recent_highs[i - 1] > recent_highs[i]:
                hh_count += 1  # Higher high
            if recent_lows[i - 1] < recent_lows[i]:
                ll_count += 1  # Lower low
        if hh_count >= 3:
            tech_score += 5
            score_breakdown.append(f"V4价格结构+5(HH={hh_count})")
        elif ll_count >= 3:
            tech_score -= 5
            score_breakdown.append(f"V4价格结构-5(LL={ll_count})")
        
        # --- LAYER 2: MOMENTUM (±15 max) ---
        momentum_score = 0
        # RSI — only score in confirming direction, not contrarian
        if rsi < 30 and trend_15m >= 0:
            momentum_score += 5  # Oversold in uptrend = buy dip
            score_breakdown.append(f"RSI超卖+趋势,+5")
        elif rsi > 70 and trend_15m <= 0:
            momentum_score -= 5  # Overbought in downtrend = sell rally
            score_breakdown.append(f"RSI超买+下跌,-5")
        elif rsi < 40 and trend_15m > 0:
            momentum_score += 3
        elif rsi > 60 and trend_15m < 0:
            momentum_score -= 3
        
        # MACD direction must confirm trend
        if macd_line > 0 and trend_15m > 0:
            momentum_score += 5
            score_breakdown.append(f"MACD多头确认+5")
        elif macd_line < 0 and trend_15m < 0:
            momentum_score -= 5
            score_breakdown.append(f"MACD空头确认-5")
        
        # MACD histogram growing (momentum accelerating)
        if macd_hist_growing and macd_histogram > 0:
            momentum_score += 5
            score_breakdown.append(f"动量加速+5")
        elif macd_hist_growing and macd_histogram < 0:
            momentum_score -= 5
            score_breakdown.append(f"动量加速-5")
        
        tech_score += momentum_score
        
        # --- LAYER 3: VOLUME (±10 max) ---
        vol_score = 0
        if vol_ratio > 1.5 and price_change_1h > 0.1:
            vol_score += 5
            score_breakdown.append(f"放量上涨+5")
        elif vol_ratio > 1.5 and price_change_1h < -0.1:
            vol_score -= 5
            score_breakdown.append(f"放量下跌-5")
        
        # OBV direction (simplified)
        obv_trend = sum(1 if closes[i] > closes[i-1] else -1 for i in range(-10, 0))
        if obv_trend > 5 and trend_15m > 0:
            vol_score += 5
            score_breakdown.append(f"OBV确认+5")
        elif obv_trend < -5 and trend_15m < 0:
            vol_score -= 5
            score_breakdown.append(f"OBV确认-5")
        
        tech_score += vol_score
        
        # --- LAYER 4: MARKET STRUCTURE (±5 max) ---
        struct_score = 0
        if bb_position < 15 and trend_15m >= 0:
            struct_score += 3
        elif bb_position > 85 and trend_15m <= 0:
            struct_score -= 3
        
        tech_score += struct_score
        
        # --- LAYER 5: SENTIMENT — Fear & Greed Index (±10 max, contrarian) ---
        sentiment_score = 0
        if fng_value <= 10:
            sentiment_score += 10
            score_breakdown.append(f"恐贪={fng_value}极度恐惧→逆向+10")
        elif fng_value <= 25:
            sentiment_score += 5
            score_breakdown.append(f"恐贪={fng_value}恐惧→逆向+5")
        elif fng_value >= 90:
            sentiment_score -= 10
            score_breakdown.append(f"恐贪={fng_value}极度贪婪→逆向-10")
        elif fng_value >= 75:
            sentiment_score -= 5
            score_breakdown.append(f"恐贪={fng_value}贪婪→逆向-5")
        
        tech_score += sentiment_score
        
        # --- LAYER 6: SMART MONEY CONCEPTS (±10 max) ---
        try:
            from backend.analysis.smart_money import analyze_smc
            smc_result = analyze_smc(opens, closes, highs, lows, volumes, current_price)
            smc_adj = smc_result["score_adjustment"]
            tech_score += smc_adj
            if smc_adj != 0:
                smc_signals_str = ', '.join(smc_result['signals'][:3])
                score_breakdown.append(f"SMC{'+' if smc_adj > 0 else ''}{smc_adj}({smc_signals_str})")
        except Exception as e:
            smc_result = {"score_adjustment": 0, "market_structure": "unknown", "signals": [], "order_blocks": [], "fvgs": []}
        
        # --- LAYER 7: EVOLUTION RULES (experience-based, ±5 max) ---
        evo_indicators = {
            'rsi': rsi, 'adx': adx, 'fng': fng_value,
            'smc_structure': smc_result.get('market_structure', ''),
            'smc_signals': ', '.join(smc_result.get('signals', [])),
            'trend_agreement': (trend_15m >= 0 and trend_1h >= 0 and trend_4h >= 0) or (trend_15m <= 0 and trend_1h <= 0 and trend_4h <= 0),
            'atr_pct': round(atr_approx / current_price * 100, 2) if current_price else 0,
        }
        evo_side = 'buy' if tech_score >= 60 else 'sell' if tech_score <= 40 else None
        evo_result = evolution_engine.get_score_adjustment(evo_indicators, side=evo_side, score=tech_score)
        if evo_result['adjustment'] != 0:
            tech_score += int(evo_result['adjustment'])
            evo_reasons = '; '.join(evo_result['reasons'])
            score_breakdown.append(f"进化{'+' if evo_result['adjustment'] > 0 else ''}{evo_result['adjustment']:.0f}({evo_reasons})")
        
        # --- LAYER 8: FUNDING RATE FILTER (±5 max) ---
        funding_rate = 0.0
        funding_adj = 0
        try:
            fr_data = await _exchange_data.get_funding_rate_with_fallback(symbol)
            if fr_data and "funding_rate" in fr_data:
                funding_rate = float(fr_data["funding_rate"]) * 100  # Convert to %
                
                src_label = fr_data.get("source", "unknown")
                
                # High positive funding + going long = crowded trade → penalty
                if funding_rate > 0.05 and tech_score >= 60:
                    funding_adj = -5
                    score_breakdown.append(f"资金({src_label})={funding_rate:.3f}%>0.05%做多惩罚-5")
                elif funding_rate < -0.05 and tech_score <= 40:
                    funding_adj = -5
                    score_breakdown.append(f"资金({src_label})={funding_rate:.3f}%<-0.05%做空惩罚-5")
                elif abs(funding_rate) > 0.1:
                    funding_adj = -3
                    score_breakdown.append(f"资金率异常={funding_rate:.3f}%>0.1%谨慎-3")
                
                tech_score += funding_adj
        except Exception:
            pass  # Funding rate fetch is non-critical
        
        # --- LAYER 9: ENHANCED INDICATORS (±10 max) ---
        enhanced_score = 0
        stoch_rsi_k = 50  # Default, updated below
        try:
            # Stochastic RSI (inline computation)
            rsi_values = []
            for i in range(14, len(closes)):
                gains = [max(0, closes[j] - closes[j-1]) for j in range(i-13, i+1)]
                losses_arr = [max(0, closes[j-1] - closes[j]) for j in range(i-13, i+1)]
                avg_g = sum(gains) / 14
                avg_l = sum(losses_arr) / 14
                rsi_values.append(100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100)
            
            if len(rsi_values) >= 14:
                rsi_window = rsi_values[-14:]
                rsi_min = min(rsi_window)
                rsi_max = max(rsi_window)
                stoch_rsi_k = ((rsi_values[-1] - rsi_min) / (rsi_max - rsi_min) * 100) if rsi_max != rsi_min else 50
                
                if stoch_rsi_k < 20 and trend_15m >= 0:
                    enhanced_score += 5
                    score_breakdown.append(f"StochRSI={stoch_rsi_k:.0f}<20超卖+趋势确认+5")
                elif stoch_rsi_k > 80 and trend_15m <= 0:
                    enhanced_score -= 5
                    score_breakdown.append(f"StochRSI={stoch_rsi_k:.0f}>80超买+趋势确认-5")
            else:
                stoch_rsi_k = 50
            
            # EMA(8/21) cross
            if len(closes) >= 21:
                ema8 = calc_ema(closes, 8)
                ema21 = calc_ema(closes, 21)
                ema8_prev = calc_ema(closes[:-1], 8)
                ema21_prev = calc_ema(closes[:-1], 21)
                
                ema_cross_up = ema8 > ema21 and ema8_prev <= ema21_prev
                ema_cross_down = ema8 < ema21 and ema8_prev >= ema21_prev
                
                if ema_cross_up:
                    enhanced_score += 5
                    score_breakdown.append(f"EMA8/21金叉+5")
                elif ema_cross_down:
                    enhanced_score -= 5
                    score_breakdown.append(f"EMA8/21死叉-5")
            
            tech_score += max(-10, min(10, enhanced_score))
        except Exception as e:
            logger.debug(f"Enhanced indicators error: {e}")
        
        # --- LAYER 10: MARKET RESONANCE — Scanner Linkage (±8 max) ---
        resonance_score = 0
        try:
            scanner_result = _multi_scan_cache.get("result")
            if scanner_result and time.time() - _multi_scan_cache.get("timestamp", 0) < 300:
                opportunities = scanner_result.get("opportunities", [])
                if opportunities:
                    bullish_count = sum(1 for s in opportunities if s.get("direction") == "bullish")
                    bearish_count = sum(1 for s in opportunities if s.get("direction") == "bearish")
                    total = len(opportunities)
                    
                    if total >= 3:
                        if bullish_count >= total * 0.7:
                            resonance_score = 8
                            score_breakdown.append(f"大盘共振多头+8({bullish_count}/{total})")
                        elif bearish_count >= total * 0.7:
                            resonance_score = -8
                            score_breakdown.append(f"大盘共振空头-8({bearish_count}/{total})")
                        elif bullish_count >= total * 0.5:
                            resonance_score = 3
                            score_breakdown.append(f"大盘偏多+3({bullish_count}/{total})")
                        elif bearish_count >= total * 0.5:
                            resonance_score = -3
                            score_breakdown.append(f"大盘偏空-3({bearish_count}/{total})")
                    
                    tech_score += resonance_score
        except Exception:
            pass
        
        # --- LAYER 11: ORDER BOOK DEPTH (±5 max) ---
        orderbook_score = 0
        orderbook_imbalance = 1.0
        try:
            book_data = await _exchange_data.get_orderbook_with_fallback(symbol, limit=50)
            if book_data:
                total_bid = sum(float(b[1]) * float(b[0]) for b in book_data.get("bids", []))
                total_ask = sum(float(a[1]) * float(a[0]) for a in book_data.get("asks", []))
                
                if total_ask > 0:
                    orderbook_imbalance = round(total_bid / total_ask, 2)
                
                src_label = book_data.get("source", "unknown")
                
                if orderbook_imbalance > 1.5:
                    orderbook_score = 5
                    score_breakdown.append(f"厚买盘({src_label})>1.5x+5(比率{orderbook_imbalance})")
                elif orderbook_imbalance < 0.67:
                    orderbook_score = -5
                    score_breakdown.append(f"厚抛压({src_label})>1.5x-5(比率{orderbook_imbalance})")
                
                tech_score += orderbook_score
        except Exception:
            pass
        
        # --- LAYER 18: LONG/SHORT RATIO (±8 max, contrarian) ---
        ls_ratio = 1.0
        ls_long_pct = 50.0
        ls_adj = 0
        try:
            ls_data = await _exchange_data.get_long_short_with_fallback(symbol, period="1h", limit=1)
            if ls_data and len(ls_data) > 0:
                ls_ratio = float(ls_data[0].get("long_short_ratio", 1.0))
                ls_long_pct = float(ls_data[0].get("long_ratio", 0.5)) * 100
                ls_short_pct = float(ls_data[0].get("short_ratio", 0.5)) * 100
                
                # Contrarian logic: extreme crowd positioning = reversal signal
                if ls_long_pct > 65:
                    # Too many longs → bearish contrarian signal
                    ls_adj = -8
                    score_breakdown.append(f"多空比=多头{ls_long_pct:.0f}%>65%过度拥挤→逆向-8")
                elif ls_long_pct > 58:
                    ls_adj = -3
                    score_breakdown.append(f"多空比=多头{ls_long_pct:.0f}%>58%偏多→谨慎-3")
                elif ls_short_pct > 65:
                    # Too many shorts → bullish contrarian signal
                    ls_adj = +8
                    score_breakdown.append(f"多空比=空头{ls_short_pct:.0f}%>65%过度拥挤→逆向+8")
                elif ls_short_pct > 58:
                    ls_adj = +3
                    score_breakdown.append(f"多空比=空头{ls_short_pct:.0f}%>58%偏空→谨慎+3")
            tech_score += ls_adj
        except Exception:
            pass  # Long/short ratio fetch is non-critical
        
        # --- ADX GATE: No trade in weak trends ---
        market_regime = "trending" if adx >= 25 else "ranging" if adx < 20 else "transitioning"
        if adx < 20 and abs(tech_score - 50) > 10:
            # Dampen score in ranging market
            tech_score = 50 + int((tech_score - 50) * 0.5)
            score_breakdown.append(f"ADX={adx}<20震荡市,评分减半")
        
        # NOTE: Do NOT clamp here — more layers still add to tech_score below
        
        # --- LAYER 12: SIGNAL CONFLICT MATRIX (±8 max) ---
        try:
            from backend.analysis.signal_matrix import evaluate_signal_conflicts
            conflict_result = evaluate_signal_conflicts({
                "rsi": rsi, "adx": adx, "trend_15m": trend_15m,
                "trend_1h": trend_1h, "trend_4h": trend_4h,
                "macd_growing": macd_hist_growing, "bb_position": bb_position,
                "volume_ratio": vol_ratio,
                "stoch_rsi": stoch_rsi_k,
                "market_regime": market_regime,
                "smc_structure": smc_result.get("market_structure", "neutral"),
                "orderbook_imbalance": orderbook_imbalance,
            })
            if conflict_result["adjustment"] != 0:
                tech_score += conflict_result["adjustment"]
                combo_label = conflict_result.get("combo_name", "")
                reasons_str = '; '.join(conflict_result['reasons'][:2])
                score_breakdown.append(f"信号矩阵{'+' if conflict_result['adjustment']>0 else ''}{conflict_result['adjustment']}({combo_label}: {reasons_str})")
            tech_score = max(0, min(100, tech_score))
        except Exception as e:
            conflict_result = {"adjustment": 0, "confidence_level": "low", "reasons": [], "combo_name": None}
            logger.debug(f"Signal matrix error: {e}")
        
        # --- LAYER 13: LIQUIDATION ZONE ESTIMATION (±5 max) — cached 60s ---
        liq_result = None
        try:
            from backend.analysis.liquidation_estimator import estimate_liquidation_zones
            now_l = time.time()
            if (_liquidation_cache.get("symbol") == symbol and 
                now_l - _liquidation_cache.get("timestamp", 0) < 60 and
                _liquidation_cache.get("result")):
                liq_result = _liquidation_cache["result"]
                logger.debug("LAYER13 cache hit")
            else:
                ex_data = await _exchange_data.get_comprehensive_exchange_data(symbol)
                liq_result = await estimate_liquidation_zones(current_price, ex_data, symbol)
                _liquidation_cache.update({"result": liq_result, "timestamp": now_l, "symbol": symbol})
                logger.info(f"LAYER13 清算推算刷新: {liq_result.get('dominant_label','N/A')}, 4所FR={liq_result.get('funding_rates',{})}")
            
            if liq_result and liq_result.get("score_adjustment", 0) != 0:
                tech_score += liq_result["score_adjustment"]
                liq_reasons = '; '.join(liq_result.get("reasons", [])[:2])
                score_breakdown.append(f"清算推算{'+' if liq_result['score_adjustment']>0 else ''}{liq_result['score_adjustment']}({liq_result.get('dominant_label','')}: {liq_reasons})")
            tech_score = max(0, min(100, tech_score))
        except Exception as e:
            logger.debug(f"Liquidation estimator error: {e}")
        
        # --- LAYER 14: VOLUME PROFILE — Multi-Exchange VPVR (±5 max) — cached 60s ---
        vp_result = None
        vp_score_result = None
        try:
            from backend.analysis.volume_profile import compute_volume_profile, score_volume_profile
            now_v = time.time()
            
            if (_vpvr_cache.get("symbol") == symbol and
                now_v - _vpvr_cache.get("timestamp", 0) < 60 and
                _vpvr_cache.get("vp_raw")):
                # Cache hit: reuse VP data, only re-score (price may have moved)
                vp_result = _vpvr_cache["vp_raw"]
                vp_score_result = score_volume_profile(vp_result, current_price)
                logger.debug("LAYER14 VPVR cache hit")
            else:
                # Cache miss: fetch fresh K-lines from all 4 exchanges
                kline_tasks = [
                    _exchange_data.binance_klines(symbol, "1h", 200, "futures"),
                    _exchange_data.okx_klines(symbol, "1h", 200, "futures"),
                    _exchange_data.bybit_klines(symbol, "1h", 200, "futures"),
                    _exchange_data.hyperliquid_klines(symbol, "1h", 200, "futures"),
                ]
                klines_results = await asyncio.gather(*kline_tasks, return_exceptions=True)
                valid_klines = [k for k in klines_results if isinstance(k, list) and len(k) > 0]
                
                if valid_klines:
                    vp_result = compute_volume_profile(valid_klines, num_bins=50)
                    if vp_result:
                        vp_score_result = score_volume_profile(vp_result, current_price)
                        _vpvr_cache.update({"vp_raw": vp_result, "timestamp": now_v, "symbol": symbol})
                        logger.info(f"LAYER14 VPVR刷新: POC=${vp_result['poc']:,.0f}, VA=[${vp_result['val']:,.0f}-${vp_result['vah']:,.0f}], {len(valid_klines)}所数据")
            
            if vp_score_result and vp_score_result.get("adjustment", 0) != 0:
                tech_score += vp_score_result["adjustment"]
                vp_reasons = '; '.join(vp_score_result.get("reasons", [])[:2])
                score_breakdown.append(f"VPVR{'+' if vp_score_result['adjustment']>0 else ''}{vp_score_result['adjustment']}({vp_reasons})")
            tech_score = max(0, min(100, tech_score))
        except Exception as e:
            logger.debug(f"Volume profile error: {e}")
        
        # --- LAYER 15: MULTI-EXCHANGE L/S DEEP ANALYSIS (±12 max) ---
        ls_analysis_result = None
        try:
            from backend.analysis.ls_analyzer import LSAnalyzer
            # Reuse exchange data from LAYER 13 cache (avoid duplicate fetch)
            now_ls = time.time()
            ex_data_ls = None
            if (_liquidation_cache.get("symbol") == request.symbol and 
                now_ls - _liquidation_cache.get("timestamp", 0) < 60):
                # LAYER 13 already fetched comprehensive exchange data
                ex_data_ls = _liquidation_cache.get("ex_data")
            
            if not ex_data_ls:
                ex_data_ls = await _exchange_data.get_comprehensive_exchange_data(request.symbol)
                # Store for future reuse
                _liquidation_cache["ex_data"] = ex_data_ls
            
            if ex_data_ls:
                ls_ratios = ex_data_ls.get("long_short_ratios", {})
                fr_rates = ex_data_ls.get("funding_rates", {})
                oi_chg = ex_data_ls.get("oi_change_pct")
                
                # 价格变化 — 从K线数据估算
                price_chg = None
                if len(closes) >= 12:
                    price_12_ago = closes[-12]
                    if price_12_ago > 0:
                        price_chg = (current_price - price_12_ago) / price_12_ago * 100
                
                ls_analysis_result = LSAnalyzer.analyze_multi_exchange(
                    long_short_ratios=ls_ratios,
                    funding_rates=fr_rates,
                    oi_change_pct=oi_chg,
                    price_change_pct=price_chg,
                    avg_long_pct=ex_data_ls.get("avg_long_pct"),
                )
                
                ls_adj = ls_analysis_result.get("score_adjustment", 0)
                if ls_adj != 0:
                    tech_score += ls_adj
                    ls_bd = ls_analysis_result.get("breakdown", [])
                    ls_label = '; '.join(ls_bd[:2]) if ls_bd else f"L/S={ls_analysis_result.get('avg_ratio', 0):.2f}"
                    score_breakdown.append(f"多空比{'+' if ls_adj > 0 else ''}{ls_adj}({ls_label})")
                
                # 生成告警 (用户要求: <0.8 或 >2.8)
                for alert in ls_analysis_result.get("alerts", []):
                    score_breakdown.append(alert)
                    logger.warning(f"🚨 {request.symbol} {alert}")
                
                tech_score = max(0, min(100, tech_score))
        except Exception as e:
            logger.debug(f"LS Analyzer error: {e}")
        
        # === MACHINE LEARNING PREDICTOR INJECTION ===
        ml_win_probability = 0.50
        try:
            from backend.trading.ml_predictor import ml_predictor
            # Need a preliminary direction for the Predictor
            prelim_dir = "bullish" if tech_score >= 50 else "bearish"
            ml_features = ml_predictor.extract_features(
                indicators={
                    "rsi": rsi, "adx": adx, "atr_pct": (atr_approx / current_price * 100) if current_price else 0,
                    "bb_position": {"position": bb_position, "width_pct": 0, "distance_to_mid_pct": 0}, 
                    "volume_ratio": vol_ratio
                },
                exchange_data=ex_data_ls if 'ex_data_ls' in locals() else None
            )
            ml_result = ml_predictor.predict(ml_features, prelim_dir)
            ml_win_probability = ml_result["probability"]
            
            # Blend ML probability into tech_score (give it 30% weight)
            ml_implied_score = ml_win_probability * 100
            tech_score = round(tech_score * 0.7 + ml_implied_score * 0.3)
            
            score_breakdown.append(f"🤖ML预测: 胜率{ml_win_probability*100:.1f}%,信心{ml_result['confidence']}")
            
        except Exception as e:
            logger.error(f"ML Predictor Error: {e}")
            
        # === FINAL CLAMP: All layers done, now constrain to 0-100 ===
        tech_score = max(0, min(100, tech_score))
        
        # === DIRECTION: Score thresholds (lowered from 70/30 to 62/38 to allow valid signals) ===
        if tech_score >= 62:
            direction = "bullish"
        elif tech_score <= 38:
            direction = "bearish"
        else:
            direction = "neutral"
        
        # === V4: 4H TREND GUARD — reject signals against strong higher-TF trend ===
        if direction == "bullish" and trend_4h < 0 and trend_1h < 0:
            tech_score -= 5
            direction = "neutral"
            score_breakdown.append("V4守卫: 4H+1H双空头→拒绝做多")
        elif direction == "bearish" and trend_4h > 0 and trend_1h > 0:
            tech_score += 5
            direction = "neutral"
            score_breakdown.append("V4守卫: 4H+1H双多头→拒绝做空")
        
        # === LLM REVIEW LAYER — 大模型审核最终决策 ===
        llm_review = None
        review_llm = getattr(orchestrator, 'llm', None) or reflection_llm  # Prefer orchestrator's LLM (proven working)
        if req.use_llm and review_llm and direction != "neutral":
            try:
                import json as _json
                review_data = {
                    "symbol": symbol,
                    "price": current_price,
                    "score": tech_score,
                    "proposed_direction": direction,
                    "score_breakdown": score_breakdown,
                    "indicators": {
                        "rsi": rsi, "adx": adx, "atr": round(atr_approx, 2),
                        "macd": round(macd_line, 4), "macd_histogram": round(macd_histogram, 4),
                        "bb_position": bb_position,
                        "trend_15m": trend_15m, "trend_1h": trend_1h, "trend_4h": trend_4h,
                        "volume_ratio": vol_ratio,
                        "stoch_rsi": round(stoch_rsi_k, 1),
                        "fear_greed": fng_value,
                        "market_regime": market_regime,
                    },
                }
                
                review_prompt = f"""你是一位严格的加密货币交易风控审核官。你的唯一任务是审核一个由17层评分引擎生成的交易信号，决定是否允许执行。

## 你收到的数据
{_json.dumps(review_data, ensure_ascii=False, indent=2)}

## 审核规则（必须严格遵守）

1. **确认执行（CONFIRM）条件**：
   - 评分方向与多数技术指标一致
   - 没有明显的指标矛盾（如RSI超买却建议做多）
   - ADX >= 15（有趋势支撑）
   - 至少2个时间框架支持该方向

2. **拒绝执行（REJECT）条件**：
   - 指标之间严重矛盾（如趋势看空但评分看多）
   - RSI > 75 却做多，或 RSI < 25 却做空（追极端）
   - ADX < 15 且评分边缘（接近阈值）
   - 恐贪指数极端 且方向与逆向逻辑矛盾
   - 成交量不配合（缩量突破）

3. **方向覆盖（OVERRIDE）条件**（极少使用）：
   - 多数强信号明确指向反方向

## 输出格式（严格JSON，不要markdown）
{{"decision": "CONFIRM或REJECT或OVERRIDE", "direction": "bullish或bearish或neutral", "confidence": 0-100整数, "reason": "30字以内的审核理由"}}"""

                llm_response = await asyncio.wait_for(
                    review_llm.chat(
                        messages=[{"role": "user", "content": review_prompt}],
                        max_tokens=200,
                        temperature=0.1,
                    ),
                    timeout=10.0
                )
                
                # Parse LLM review response
                import re as _re
                json_match = _re.search(r'\{[^{}]+\}', llm_response, _re.DOTALL)
                if json_match:
                    review = _json.loads(json_match.group())
                    decision = review.get("decision", "CONFIRM").upper()
                    llm_review = {
                        "decision": decision,
                        "direction": review.get("direction", direction),
                        "confidence": review.get("confidence", 50),
                        "reason": review.get("reason", ""),
                    }
                    
                    if decision == "REJECT":
                        score_breakdown.append(f"🤖LLM审核: REJECT → 降级观望({llm_review['reason']})")
                        direction = "neutral"
                        logger.info(f"🤖 LLM审核拒绝交易: {llm_review['reason']}")
                    elif decision == "OVERRIDE":
                        new_dir = review.get("direction", "neutral")
                        if new_dir in ("bullish", "bearish", "neutral"):
                            score_breakdown.append(f"🤖LLM审核: OVERRIDE → {new_dir}({llm_review['reason']})")
                            direction = new_dir
                            logger.info(f"🤖 LLM审核覆盖方向: {direction}, 原因: {llm_review['reason']}")
                    else:  # CONFIRM
                        score_breakdown.append(f"🤖LLM审核: ✅确认{direction}({llm_review['reason']})")
                        logger.info(f"🤖 LLM审核确认交易: {direction}, 信心: {llm_review['confidence']}%")
                else:
                    logger.warning(f"LLM审核返回格式异常: {llm_response[:100]}")
                    
            except asyncio.TimeoutError:
                logger.warning("LLM审核超时(10s)，使用纯评分决策")
                score_breakdown.append("🤖LLM审核: 超时，跳过")
            except Exception as e:
                logger.warning(f"LLM审核异常: {e}")
                score_breakdown.append("🤖LLM审核: 异常，跳过")
        
        # Calculate entry/TP/SL using Risk Manager
        entry_price = current_price
        range_strategy = None
        trade_allowed = risk_manager.can_trade()
        
        if direction == "bullish":
            sl_tp = risk_manager.calculate_dynamic_sl_tp(current_price, "bullish", atr_approx, tech_score)
            tp_price = sl_tp["take_profit"]
            sl_price = sl_tp["stop_loss"]
        elif direction == "bearish":
            sl_tp = risk_manager.calculate_dynamic_sl_tp(current_price, "bearish", atr_approx, tech_score)
            tp_price = sl_tp["take_profit"]
            sl_price = sl_tp["stop_loss"]
        else:
            sl_tp = risk_manager.calculate_dynamic_sl_tp(current_price, "bullish", atr_approx, tech_score)
            tp_price = round(bb_upper, 2)
            sl_price = round(bb_lower, 2)
            range_strategy = {
                "type": "range",
                "description": "震荡区间交易策略 — 在布林带上下轨之间高抛低吸",
                "range_high": round(bb_upper, 2),
                "range_low": round(bb_lower, 2),
                "range_mid": round(bb_sma, 2),
                "long": {
                    "entry": round(bb_lower + atr_approx * 0.3, 2),
                    "tp": round(bb_sma + atr_approx * 0.5, 2),
                    "sl": round(bb_lower - atr_approx * 0.5, 2),
                    "side": "buy",
                    "trigger": f"价格接近下轨 ${round(bb_lower, 2):,}",
                },
                "short": {
                    "entry": round(bb_upper - atr_approx * 0.3, 2),
                    "tp": round(bb_sma - atr_approx * 0.5, 2),
                    "sl": round(bb_upper + atr_approx * 0.5, 2),
                    "side": "sell",
                    "trigger": f"价格接近上轨 ${round(bb_upper, 2):,}",
                },
                "recommended_leverage": 2,
            }
        
        # --- R:R RATIO FILTER ---
        rr_ratio = 0.0
        if direction != "neutral" and sl_price and tp_price:
            risk_dist = abs(entry_price - sl_price)
            reward_dist = abs(tp_price - entry_price)
            rr_ratio = round(reward_dist / risk_dist, 2) if risk_dist > 0 else 0
            if rr_ratio < 1.5:
                score_breakdown.append(f"⚠️盈亏比={rr_ratio}<1.5,降级观望")
                direction = "neutral"
                # Recalculate range strategy for neutral
                if not range_strategy:
                    range_strategy = {
                        "type": "range",
                        "description": f"盈亏比不足(R:R={rr_ratio}:1)，建议等待更好入场点",
                        "range_high": round(bb_upper, 2),
                        "range_low": round(bb_lower, 2),
                        "range_mid": round(bb_sma, 2),
                        "recommended_leverage": 2,
                    }
        
        # Leverage — volatility-adjusted
        lev_info = risk_manager.calculate_leverage(tech_score, atr_approx, current_price, direction)
        rec_leverage = lev_info["leverage"]
        
        # Position sizing (Dynamic Kelly Size)
        user_balance = req.account_balance if req.account_balance else None
        user_risk = req.risk_pct if req.risk_pct else None
        pos_info = risk_manager.calculate_kelly_position_size(
            entry_price=current_price, 
            stop_loss=sl_price, 
            target_price=tp_price,
            ml_win_probability=ml_win_probability,
            leverage=rec_leverage,
            account_balance=user_balance, 
            base_risk_pct=user_risk
        )
        
        # Signal-scaled position sizing (dynamic based on score strength)
        signal_pos = risk_manager.calculate_signal_scaled_position(
            entry_price=current_price,
            stop_loss=sl_price,
            leverage=rec_leverage,
            score=tech_score,
            balance=user_balance or risk_manager.account_balance,
        )
        
        indicators = {
            "rsi": rsi,
            "macd": round(macd_line, 4),
            "macd_histogram": round(macd_histogram, 4),
            "macd_growing": macd_hist_growing,
            "ma7": round(ma7, 2),
            "ma25": round(ma25, 2),
            "ma99": round(ma99, 2),
            "bb_upper": round(bb_upper, 2),
            "bb_lower": round(bb_lower, 2),
            "bb_position": bb_position,
            "volume_ratio": vol_ratio,
            "price_change_1h": price_change_1h,
            "price_change_4h": price_change_4h,
            "atr": round(atr_approx, 2),
            "adx": adx,
            "trend_15m": trend_15m,
            "trend_1h": trend_1h,
            "trend_4h": trend_4h,
            "market_regime": market_regime,
            "fear_greed": fng_value,
            "fear_greed_label": fng_label,
            "smc_structure": smc_result.get("market_structure", "unknown"),
            "smc_signals": smc_result.get("signals", []),
            # Enhanced indicators
            "stoch_rsi": round(stoch_rsi_k, 1),
            "orderbook_imbalance": orderbook_imbalance,
            "ls_long_pct": round(ls_long_pct, 1),
            "ls_ratio": round(ls_ratio, 2),
            "resonance_score": resonance_score,
        }
        
        trend_labels = {1: "多", -1: "空", 0: "平"}
        reasoning_text = (
            f"评分{tech_score} [{' | '.join(score_breakdown)}] "
            f"| ADX={adx}({market_regime}) "
            f"| 趋势 15m:{trend_labels[trend_15m]} 1h:{trend_labels[trend_1h]} 4h:{trend_labels[trend_4h]} "
            f"{'✅一致' if trends_agree else '⚠️分歧'} "
            f"| 恐贪={fng_value}({fng_label}) "
            f"| RSI={rsi} MACD={'↑' if macd_line>0 else '↓'} 量比={vol_ratio}"
        )
        if range_strategy:
            reasoning_text += f" | 震荡区间: ${round(bb_lower,0):,.0f}-${round(bb_upper,0):,.0f}"
        
        # Multi-TP levels
        try:
            multi_tp = risk_manager.calculate_multi_tp(entry_price, direction, atr_approx, tech_score)
        except Exception:
            multi_tp = None
        
        result = {
            "success": True,
            "mode": "quick",
            "symbol": symbol,
            "current_price": current_price,
            "indicators": indicators,
            "tech_score": tech_score,
            "direction": direction,
            "entry_price": round(entry_price, 2),
            "exit_price": tp_price,
            "stop_loss": sl_price,
            "leverage": rec_leverage,
            "reasoning": reasoning_text,
            "score_breakdown": score_breakdown,
            "range_strategy": range_strategy,
            "risk_info": {
                "position_size": pos_info["position_size"],
                "position_value": pos_info["position_value_usd"],
                "margin_required": pos_info["margin_required"],
                "max_risk_amount": pos_info["max_risk_amount"],
                "risk_pct": pos_info["risk_pct"],
                "rr_ratio": sl_tp.get("rr_ratio", 0) if direction != "neutral" else 0,
                "trailing_trigger": sl_tp.get("trailing_trigger") if direction != "neutral" else None,
                "leverage_detail": lev_info,
                "trade_allowed": trade_allowed,
                "consecutive_losses": pos_info.get("consecutive_losses", 0),
                "position_reduced": pos_info.get("position_reduced", False),
                # Kelly info
                "kelly_pct": pos_info.get("kelly_pct", 0),
                "win_probability": pos_info.get("win_probability", 50),
                # Signal-scaled dynamic sizing
                "signal_scaled_size": signal_pos["position_size"],
                "signal_scaled_value": signal_pos["position_value_usd"],
                "signal_scaled_margin": signal_pos["margin_required"],
                "signal_strength": signal_pos["signal_strength"],
                "signal_tier": signal_pos["signal_tier"],
                "position_pct": signal_pos["position_pct"],
            },
            "multi_tp": multi_tp,
            "signal_matrix": {
                "adjustment": conflict_result.get("adjustment", 0),
                "confidence_level": conflict_result.get("confidence_level", "low"),
                "combo_name": conflict_result.get("combo_name"),
                "reasons": conflict_result.get("reasons", []),
            },
            "liquidation_zones": {
                "dominant_side": liq_result.get("dominant_side") if liq_result else None,
                "dominant_label": liq_result.get("dominant_label") if liq_result else None,
                "key_zones_below": liq_result.get("key_zones_below", []) if liq_result else [],
                "key_zones_above": liq_result.get("key_zones_above", []) if liq_result else [],
                "nearest_support": liq_result.get("nearest_support") if liq_result else None,
                "nearest_resistance": liq_result.get("nearest_resistance") if liq_result else None,
                "funding_rates": liq_result.get("funding_rates", {}) if liq_result else {},
                "oi_intensity": liq_result.get("oi_intensity") if liq_result else None,
                "score_adjustment": liq_result.get("score_adjustment", 0) if liq_result else 0,
            },
            "volume_profile": {
                "poc": vp_result.get("poc") if vp_result else None,
                "vah": vp_result.get("vah") if vp_result else None,
                "val": vp_result.get("val") if vp_result else None,
                "exchanges_used": vp_result.get("exchanges_used", 0) if vp_result else 0,
                "candles_analyzed": vp_result.get("candles_analyzed", 0) if vp_result else 0,
                "high_volume_nodes": vp_result.get("high_volume_nodes", [])[:3] if vp_result else [],
                "score_adjustment": vp_score_result.get("adjustment", 0) if vp_score_result else 0,
                "reasons": vp_score_result.get("reasons", []) if vp_score_result else [],
            },
        }
        
        # 3. Optional: single LLM call for refined opinion (~5s)
        if req.use_llm and orchestrator.llm:
            deep_context = ""
            if req.deep_bias:
                db = req.deep_bias
                deep_context = f"\n\n上一次深度分析结果：方向={db.get('direction','N/A')}, 评分={db.get('score','N/A')}/100, 入场=${db.get('entry_price','N/A')}, 杠杆={db.get('leverage','N/A')}x"
            
            prompt = f"""你是一个量化交易助手。根据以下{symbol}的技术指标数据，给出简短的交易建议。

当前价格: ${current_price:,.2f}
RSI(14): {rsi}
MACD: {'多头' if macd_line>0 else '空头'} ({macd_line:.4f})
MA7: ${ma7:,.2f}, MA25: ${ma25:,.2f}, MA99: ${ma99:,.2f}
布林带位置: {bb_position}% (上轨${bb_upper:,.2f}, 下轨${bb_lower:,.2f})
量比: {vol_ratio}
1小时涨跌: {price_change_1h}%
4小时涨跌: {price_change_4h}%
ATR: ${atr_approx:,.2f}{deep_context}

如果方向是neutral，请额外给出震荡区间交易策略（在布林带上下轨之间高抛低吸的建议）。

请用JSON格式回复（不要markdown），包含：
{{"direction": "bullish/bearish/neutral", "score": 0-100, "entry_price": 数字, "exit_price": 数字, "stop_loss": 数字, "leverage": 1-10, "reasoning": "一句话理由"}}"""

            try:
                llm_response = await asyncio.wait_for(
                    orchestrator.llm.chat(
                        messages=[{"role": "user", "content": prompt}],
                        system_prompt="你是专业量化交易员，只输出JSON，不要任何解释或markdown标记。",
                        max_tokens=300,
                        temperature=0.3,
                    ),
                    timeout=15.0
                )
                
                # Parse JSON from LLM response
                import re
                json_match = re.search(r'\{[^{}]+\}', llm_response, re.DOTALL)
                if json_match:
                    llm_data = json.loads(json_match.group())
                    result["direction"] = llm_data.get("direction", direction)
                    result["tech_score"] = llm_data.get("score", tech_score)
                    result["entry_price"] = llm_data.get("entry_price", entry_price)
                    result["exit_price"] = llm_data.get("exit_price", tp_price)
                    result["stop_loss"] = llm_data.get("stop_loss", sl_price)
                    result["leverage"] = llm_data.get("leverage", rec_leverage)
                    result["reasoning"] = llm_data.get("reasoning", result["reasoning"])
                    result["llm_enhanced"] = True
                    logger.info(f"Quick analyze LLM增强: {llm_data.get('direction')} {llm_data.get('score')}/100")
                else:
                    result["llm_enhanced"] = False
                    logger.warning(f"Quick analyze LLM返回非JSON: {llm_response[:100]}")
            except asyncio.TimeoutError:
                result["llm_enhanced"] = False
                logger.warning("Quick analyze LLM超时，使用纯技术指标")
            except Exception as llm_err:
                result["llm_enhanced"] = False
                logger.warning(f"Quick analyze LLM失败: {llm_err}")
        else:
            result["llm_enhanced"] = False
        
        # Apply deep bias adjustment
        if req.deep_bias:
            db = req.deep_bias
            deep_dir = db.get("direction", "neutral")
            deep_score = db.get("score", 50)
            original_dir = result["direction"]
            original_score = result["tech_score"]
            
            # Blend: 50% quick + 50% deep bias (experts have equal weight)
            blended_score = round(result["tech_score"] * 0.5 + deep_score * 0.5)
            result["tech_score"] = blended_score
            result["deep_bias_applied"] = True
            
            if blended_score >= 65:
                result["direction"] = "bullish"
            elif blended_score <= 35:
                result["direction"] = "bearish"
            else:
                result["direction"] = "neutral"
            
            score_breakdown.append(f"圆桌{deep_score}/技术{original_score}→混合{blended_score}")
            result["score_breakdown"] = score_breakdown
            
            # 🔴 CRITICAL: 如果方向改变了，必须重新计算 TP/SL
            new_dir = result["direction"]
            if new_dir != original_dir and new_dir != "neutral":
                sl_tp_new = risk_manager.calculate_dynamic_sl_tp(current_price, new_dir, atr_approx, blended_score)
                result["entry_price"] = round(current_price, 2)
                result["exit_price"] = sl_tp_new["take_profit"]
                result["stop_loss"] = sl_tp_new["stop_loss"]
                # 重新计算杠杆
                lev_new = risk_manager.calculate_leverage(blended_score, atr_approx, current_price, new_dir)
                result["leverage"] = lev_new["leverage"]
                score_breakdown.append(f"方向{original_dir}→{new_dir},重算TP/SL")
            
            # 如果 deep_bias 有更精确的价格，且方向一致，优先使用
            if deep_dir == new_dir and new_dir != "neutral":
                if db.get("entry_price"):
                    result["entry_price"] = db["entry_price"]
                if db.get("exit_price"):
                    # 验证 TP 方向正确 (bullish: TP > entry, bearish: TP < entry)
                    ep = result["entry_price"]
                    tp = db["exit_price"]
                    if (new_dir == "bullish" and tp > ep) or (new_dir == "bearish" and tp < ep):
                        result["exit_price"] = tp
                if db.get("stop_loss"):
                    sl = db["stop_loss"]
                    ep = result["entry_price"]
                    if (new_dir == "bullish" and sl < ep) or (new_dir == "bearish" and sl > ep):
                        result["stop_loss"] = sl
                if db.get("leverage"):
                    result["leverage"] = db["leverage"]
            
            # If direction became neutral after blending, ensure range_strategy exists
            if result["direction"] == "neutral" and not result.get("range_strategy"):
                result["range_strategy"] = {
                    "type": "range",
                    "description": "震荡区间交易策略 — 在布林带上下轨之间高抛低吸",
                    "range_high": round(bb_upper, 2),
                    "range_low": round(bb_lower, 2),
                    "range_mid": round(bb_sma, 2),
                    "long": {
                        "entry": round(bb_lower + atr_approx * 0.3, 2),
                        "tp": round(bb_sma + atr_approx * 0.5, 2),
                        "sl": round(bb_lower - atr_approx * 0.5, 2),
                        "side": "buy",
                        "trigger": f"价格接近下轨 ${round(bb_lower, 2):,}",
                    },
                    "short": {
                        "entry": round(bb_upper - atr_approx * 0.3, 2),
                        "tp": round(bb_sma - atr_approx * 0.5, 2),
                        "sl": round(bb_upper + atr_approx * 0.5, 2),
                        "side": "sell",
                        "trigger": f"价格接近上轨 ${round(bb_upper, 2):,}",
                    },
                    "recommended_leverage": 2,
                }
                result["reasoning"] += f" | 深度偏好({deep_dir}/{deep_score})混合后进入震荡策略"
        
        # Also store as final_decision format for compatibility
        result["final_decision"] = {
            "direction": result["direction"],
            "score": result["tech_score"],
            "entry_price": result["entry_price"],
            "exit_price": result["exit_price"],
            "stop_loss": result["stop_loss"],
            "leverage": result["leverage"],
            "reasoning": result["reasoning"],
        }
        
        logger.info(f"Quick analyze完成: {symbol} → {result['direction']} {result['tech_score']}/100 (LLM={'✓' if result.get('llm_enhanced') else '✗'})")
        return result
        
    except Exception as e:
        logger.error(f"Quick analyze失败: {e}")
        return {"success": False, "error": str(e)}


# ===== 多币种并行分析 =====
class MultiAnalyzeRequest(BaseModel):
    symbols: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT"]
    use_llm: bool = False
    account_balance: float = 10000
    risk_pct: float = 5.0   # 总风险池 (方案B: 共享)
    deep_bias: Optional[Dict] = None


@app.post("/api/multi-analyze")
async def multi_analyze(req: MultiAnalyzeRequest):
    """多币种并行分析 + 信号加权仓位分配（共享风控池）"""
    try:
        if not req.symbols or "HOT" in [s.upper() for s in req.symbols]:
            logger.info("动态市场雷达: 拉取全网 Top 10 交易量币种...")
            symbols = await _exchange_data.get_top_volume_symbols(limit=10)
        else:
            symbols = [s.upper() for s in req.symbols[:10]]  # 允许最多 10 个

        logger.info(f"多币种分析: {', '.join(symbols)}")

        # 1. 并行快速分析所有币种
        tasks = [
            quick_analyze(QuickAnalyzeRequest(
                symbol=sym, use_llm=req.use_llm,
                account_balance=req.account_balance,
                risk_pct=req.risk_pct, deep_bias=req.deep_bias,
            ))
            for sym in symbols
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 2. 收集有效结果
        results = []
        for sym, res in zip(symbols, raw_results):
            if isinstance(res, Exception):
                results.append({"symbol": sym, "success": False, "error": str(res)})
                continue
            if not isinstance(res, dict) or not res.get("success"):
                results.append({"symbol": sym, "success": False, "error": res.get("error", "unknown") if isinstance(res, dict) else "failed"})
                continue
            fd = res.get("final_decision", {})
            results.append({
                "symbol": sym,
                "success": True,
                "current_price": res.get("current_price"),
                "direction": fd.get("direction", "neutral"),
                "score": fd.get("score", 50),
                "entry_price": fd.get("entry_price"),
                "exit_price": fd.get("exit_price"),
                "stop_loss": fd.get("stop_loss"),
                "leverage": fd.get("leverage", 1),
                "reasoning": fd.get("reasoning", "")[:120],
                "rsi": res.get("indicators", {}).get("rsi"),
                "adx": res.get("indicators", {}).get("adx"),
                "market_regime": res.get("indicators", {}).get("market_regime"),
                "bb_position": res.get("indicators", {}).get("bb_position"),
                "volume_ratio": res.get("indicators", {}).get("volume_ratio"),
                "rr_ratio": res.get("risk_info", {}).get("rr_ratio", 0),
                "range_strategy": res.get("range_strategy"),
                "risk_info": res.get("risk_info"),
                "llm_enhanced": res.get("llm_enhanced", False),
                "signal_strength": abs(fd.get("score", 50) - 50),  # 0~50
            })

        # 3. 信号加权仓位分配 (方案B: 共享风控池)
        tradeable = [r for r in results if r.get("success") and r["direction"] != "neutral"]
        total_risk = req.account_balance * (req.risk_pct / 100.0)
        total_signal_weight = sum(r["signal_strength"] for r in tradeable) or 1

        for r in results:
            if r in tradeable:
                weight = r["signal_strength"] / total_signal_weight
                r["risk_weight"] = round(weight, 4)
                r["allocated_risk"] = round(total_risk * weight, 2)
                r["allocated_pct"] = round(weight * 100, 1)
                # 基于分配的风险计算仓位
                sl_dist = abs(r["entry_price"] - r["stop_loss"]) if r.get("entry_price") and r.get("stop_loss") else r.get("entry_price", 1) * 0.02
                if sl_dist > 0:
                    pos = r["allocated_risk"] / sl_dist
                    r["weighted_position_size"] = round(pos, 6)
                    r["weighted_position_value"] = round(pos * (r.get("entry_price") or 0), 2)
                    r["weighted_margin"] = round(pos * (r.get("entry_price") or 0) / max(1, r.get("leverage", 1)), 2)
            else:
                r["risk_weight"] = 0
                r["allocated_risk"] = 0
                r["allocated_pct"] = 0

        # 4. 按评分排序 (非中性优先, 然后按分数)
        results.sort(key=lambda x: (
            1 if x.get("direction") != "neutral" else 0,  # tradeable first
            x.get("score", 50) if x.get("direction") == "bullish" else (100 - x.get("score", 50)),  # higher score for bull, lower for bear
        ), reverse=True)

        # Find actual strongest (highest score deviation from 50, non-neutral)
        strongest = None
        strongest_score = None
        for r in results:
            if r.get("direction") != "neutral":
                if strongest is None or abs(r.get("score", 50) - 50) > abs(strongest_score - 50):
                    strongest = r["symbol"]
                    strongest_score = r["score"]

        return {
            "success": True,
            "results": results,
            "summary": {
                "total_symbols": len(symbols),
                "tradeable": len(tradeable),
                "total_risk_pool": round(total_risk, 2),
                "strongest": strongest,
                "strongest_score": strongest_score,
            }
        }
    except Exception as e:
        logger.error(f"多币种分析失败: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/analyze")
async def analyze_sync(request: AnalyzeRequest):
    """同步分析端点（非WebSocket）"""
    try:
        logger.info(f"收到分析请求: {request.symbol} ({request.interval})")
        
        result = await orchestrator.run_analysis(
            symbol=request.symbol,
            interval=request.interval,
            user_config=request.user_config or {},
            websocket=None
        )
        
        return result
        
    except Exception as e:
        logger.error(f"分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/exchanges/symbols")
async def get_available_symbols():
    """获取可交易的币种列表"""
    # 返回常用的交易对
    return {
        "success": True,
        "symbols": [
            {"symbol": "BTCUSDT", "name": "Bitcoin", "default": True},
            {"symbol": "ETHUSDT", "name": "Ethereum", "default": True},
            {"symbol": "SOLUSDT", "name": "Solana", "default": True},
            {"symbol": "ADAUSDT", "name": "Cardano", "default": True},
            {"symbol": "XRPUSDT", "name": "Ripple", "default": True},
            {"symbol": "DOGEUSDT", "name": "Dogecoin", "default": True},
            {"symbol": "BNBUSDT", "name": "Binance Coin"},
            {"symbol": "AVAXUSDT", "name": "Avalanche"},
            {"symbol": "DOTUSDT", "name": "Polkadot"},
            {"symbol": "MATICUSDT", "name": "Polygon"},
            {"symbol": "LINKUSDT", "name": "Chainlink"},
            {"symbol": "UNIUSDT", "name": "Uniswap"},
            {"symbol": "ATOMUSDT", "name": "Cosmos"},
            {"symbol": "LTCUSDT", "name": "Litecoin"},
            {"symbol": "NEARUSDT", "name": "NEAR Protocol"},
        ]
    }


@app.get("/api/intervals")
async def get_intervals():
    """获取可用时间周期"""
    return {
        "success": True,
        "intervals": [
            {"value": "1m", "label": "1分钟"},
            {"value": "5m", "label": "5分钟"},
            {"value": "15m", "label": "15分钟"},
            {"value": "1h", "label": "1小时"},
            {"value": "4h", "label": "4小时"},
            {"value": "1d", "label": "1日"},
            {"value": "1w", "label": "1周"},
        ]
    }



# ===== 风险管理 API =====
@app.get("/api/risk-status")
async def get_risk_status():
    """获取风险管理状态和交易统计"""
    stats = risk_manager.get_stats()
    trade_check = risk_manager.can_trade()
    return {
        "success": True,
        "stats": stats,
        "trade_check": trade_check,
        "config": {
            "max_risk_per_trade": risk_manager.max_risk_per_trade * 100,
            "max_daily_loss": risk_manager.max_daily_loss * 100,
            "max_leverage": risk_manager.max_leverage,
            "min_rr_ratio": risk_manager.min_rr_ratio,
            "consecutive_loss_threshold": risk_manager.consecutive_loss_threshold,
        }
    }

@app.post("/api/risk/record-result")
async def record_trade_result(pnl: float, trade_id: str = None):
    """记录交易结果"""
    risk_manager.record_trade_result(pnl, trade_id)
    return {"success": True, "stats": risk_manager.get_stats()}


# ===== 实时价格 API =====
@app.get("/api/price")
async def get_price(symbol: str = "BTCUSDT"):
    """获取实时价格 — 使用与 quick-analyze 相同的 httpx 通道"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try ticker/price first (fastest)
            try:
                resp = await client.get(
                    f"https://fapi.binance.com/fapi/v1/ticker/price",
                    params={"symbol": symbol.upper()}
                )
                data = resp.json()
                if "price" in data:
                    return {"success": True, "symbol": symbol, "price": float(data["price"])}
            except Exception:
                pass
            # Fallback: last kline close
            resp = await client.get(
                f"https://fapi.binance.com/fapi/v1/klines",
                params={"symbol": symbol.upper(), "interval": "1m", "limit": 1}
            )
            klines = resp.json()
            if klines and len(klines) > 0:
                return {"success": True, "symbol": symbol, "price": float(klines[0][4])}
        return {"success": False, "error": "无法获取价格"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===== 交易执行 API =====
# Paper positions with disk persistence
PAPER_POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "paper_positions.json")

def _save_paper_positions():
    """Save paper_positions to disk — survives backend restarts"""
    try:
        with open(PAPER_POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(paper_positions, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.warning(f"保存模拟持仓失败: {e}")

def _load_paper_positions():
    """Load paper_positions from disk on startup"""
    try:
        if os.path.exists(PAPER_POSITIONS_FILE):
            with open(PAPER_POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                logger.info(f"📂 加载 {len(data)} 个模拟持仓 (open={sum(1 for p in data if p.get('status')=='open')})")
                return data
    except Exception as e:
        logger.warning(f"加载模拟持仓失败: {e}")
    return []

paper_positions = _load_paper_positions()
paper_orders = []

class TradeExecuteRequest(BaseModel):
    symbol: str = "BTCUSDT"
    side: str = "buy"  # buy / sell
    mode: str = "paper"  # paper / live
    amount: Optional[float] = None  # If None, auto-calculate via risk manager
    leverage: Optional[int] = None  # If None, auto-calculate
    entry_price: Optional[float] = None
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    account_balance: Optional[float] = None
    risk_pct: Optional[float] = None

@app.post("/api/trade/execute")
async def execute_trade(req: TradeExecuteRequest):
    """执行交易 — 支持模拟盘和实盘"""
    try:
        import httpx
        
        # Get current price
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={req.symbol}")
            current_price = float(r.json()["price"])
        
        entry_price = current_price  # Always use real-time price at execution, not stale analysis price
        
        # Auto-calculate if not provided
        if not req.tp_price or not req.sl_price:
            # Calculate ATR for SL/TP
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={req.symbol}&interval=15m&limit=20")
                klines = r.json()
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
            direction = "bullish" if req.side == "buy" else "bearish"
            sl_tp = risk_manager.calculate_dynamic_sl_tp(entry_price, direction, atr, 60)
            tp_price = req.tp_price or sl_tp["take_profit"]
            sl_price = req.sl_price or sl_tp["stop_loss"]
        else:
            tp_price = req.tp_price
            sl_price = req.sl_price
        
        # Risk check
        trade_check = risk_manager.can_trade()
        if not trade_check["allowed"]:
            return {"success": False, "error": trade_check["reason"]}
        
        # Calculate leverage and position size
        if req.leverage:
            lev = min(req.leverage, risk_manager.max_leverage)
        else:
            atr_approx = abs(tp_price - sl_price) / 3
            lev_info = risk_manager.calculate_leverage(60, atr_approx, current_price, "bullish" if req.side == "buy" else "bearish")
            lev = lev_info["leverage"]
        
        if req.amount:
            position_size = req.amount
            position_value = position_size * entry_price
            margin_required = position_value / lev
        else:
            pos_info = risk_manager.calculate_position_size(
                entry_price, sl_price, lev,
                account_balance=req.account_balance,
                risk_pct=req.risk_pct,
            )
            position_size = pos_info["position_size"]
            position_value = pos_info["position_value_usd"]
            margin_required = pos_info["margin_required"]
        
        # Create position
        position = {
            "id": str(datetime.now().timestamp()),
            "symbol": req.symbol,
            "side": req.side,
            "entry_price": round(entry_price, 2),
            "current_price": round(current_price, 2),
            "amount": round(position_size, 6),
            "leverage": lev,
            "tp_price": round(tp_price, 2),
            "sl_price": round(sl_price, 2),
            "position_value": round(position_value, 2),
            "margin_required": round(margin_required, 2),
            "pnl": 0,
            "roe": 0,
            "mode": req.mode,
            "status": "open",
            "opened_at": datetime.now().isoformat(),
            "source": "api",
        }
        
        # Record in risk manager
        risk_manager.open_trade(position)
        
        # Register with position_manager for PriceMonitor TP/SL/Trailing monitoring
        try:
            position_manager.open_position({
                "symbol": req.symbol,
                "side": req.side,
                "entry_price": entry_price,
                "amount": position_size,
                "leverage": lev,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "source": "api",
                "account_balance": req.account_balance or risk_manager.account_balance,
            })
            logger.info(f"✅ 持仓已注册到 position_manager (PriceMonitor 将监控 TP/SL)")
        except Exception as pm_err:
            logger.warning(f"⚠️ position_manager 注册失败 (paper_positions 仍会记录): {pm_err}")
        
        if req.mode == "paper":
            paper_positions.append(position)
            paper_orders.append({
                **position,
                "type": "open",
                "time": datetime.now().isoformat(),
            })
            _save_paper_positions()  # Persist to disk
            logger.info(f"📝 模拟盘下单: {req.side} {position_size:.6f} {req.symbol} @ ${entry_price:,.2f} | 杠杆 {lev}x | TP ${tp_price:,.2f} SL ${sl_price:,.2f}")
        else:
            # TODO: Real exchange API integration
            logger.warning(f"⚠️ 实盘交易需要交易所API集成 — 当前仅记录")
        
        rr_ratio = round(abs(tp_price - entry_price) / abs(sl_price - entry_price), 2) if abs(sl_price - entry_price) > 0 else 0
        
        return {
            "success": True,
            "position": position,
            "summary": {
                "action": f"{'做多' if req.side == 'buy' else '做空'} {req.symbol}",
                "entry": f"${entry_price:,.2f}",
                "tp": f"${tp_price:,.2f}",
                "sl": f"${sl_price:,.2f}",
                "amount": f"{position_size:.6f}",
                "value": f"${position_value:,.2f}",
                "margin": f"${margin_required:,.2f}",
                "leverage": f"{lev}x",
                "rr_ratio": f"{rr_ratio}:1",
                "mode": "模拟盘" if req.mode == "paper" else "🔴 实盘",
            }
        }
    except Exception as e:
        logger.error(f"交易执行失败: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/trade/positions")
async def get_positions():
    """获取当前持仓"""
    # Update current prices
    try:
        import httpx
        symbols = list(set(p["symbol"] for p in paper_positions if p["status"] == "open"))
        async with httpx.AsyncClient(timeout=5) as client:
            for sym in symbols:
                r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}")
                price = float(r.json()["price"])
                for p in paper_positions:
                    if p["symbol"] == sym and p["status"] == "open":
                        p["current_price"] = round(price, 2)
                        diff = price - p["entry_price"] if p["side"] == "buy" else p["entry_price"] - price
                        p["pnl"] = round(diff * p["amount"], 2)
                        p["roe"] = round(diff / p["entry_price"] * p["leverage"] * 100, 2)
    except Exception:
        pass
    
    open_positions = [p for p in paper_positions if p["status"] == "open"]
    total_pnl = sum(p["pnl"] for p in open_positions)
    
    return {
        "success": True,
        "positions": open_positions,
        "total_pnl": round(total_pnl, 2),
        "count": len(open_positions),
        "orders": paper_orders[-20:],  # last 20 orders
    }

class TradeCloseRequest(BaseModel):
    position_id: Optional[str] = None
    symbol: Optional[str] = None  # Close all positions for this symbol
    close_price: Optional[float] = None

@app.post("/api/trade/close")
async def close_trade(req: TradeCloseRequest):
    """平仓"""
    try:
        import httpx
        closed = []
        
        for p in paper_positions:
            if p["status"] != "open":
                continue
            if req.position_id and p["id"] != req.position_id:
                continue
            if req.symbol and p["symbol"] != req.symbol:
                continue
            
            # Get close price
            if req.close_price:
                close_price = req.close_price
            else:
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={p['symbol']}")
                    close_price = float(r.json()["price"])
            
            diff = close_price - p["entry_price"] if p["side"] == "buy" else p["entry_price"] - close_price
            pnl = round(diff * p["amount"], 2)
            roe = round(diff / p["entry_price"] * p["leverage"] * 100, 2)
            
            p["status"] = "closed"
            p["current_price"] = round(close_price, 2)
            p["pnl"] = pnl
            p["roe"] = roe
            p["closed_at"] = datetime.now().isoformat()
            
            # Record in risk manager
            risk_manager.record_trade_result(pnl, p["id"])
            
            closed.append(p)
            logger.info(f"📋 平仓: {p['side']} {p['amount']:.6f} {p['symbol']} | PnL: ${pnl:+.2f} ({roe:+.1f}%)")
        
        if closed:
            _save_paper_positions()  # Persist to disk
        
        return {
            "success": True,
            "closed": closed,
            "total_pnl": sum(p["pnl"] for p in closed),
            "stats": risk_manager.get_stats(),
        }
    except Exception as e:
        logger.error(f"平仓失败: {e}")
        return {"success": False, "error": str(e)}

class AutoTradeRequest(BaseModel):
    symbol: str = "BTCUSDT"
    mode: str = "paper"
    account_balance: Optional[float] = None
    risk_pct: Optional[float] = None
    use_llm: bool = False

@app.post("/api/trade/auto")
async def auto_trade(req: AutoTradeRequest):
    """一键自动交易 — 分析+下单一步完成"""
    # 1. Run analysis
    analyze_req = QuickAnalyzeRequest(
        symbol=req.symbol,
        use_llm=req.use_llm,
        account_balance=req.account_balance,
        risk_pct=req.risk_pct,
    )
    analysis = await quick_analyze(analyze_req)
    
    if not analysis.get("success"):
        return {"success": False, "error": "分析失败", "analysis": analysis}
    
    fd = analysis.get("final_decision", {})
    direction = fd.get("direction", "neutral")
    score = fd.get("score", 50)
    
    # 2. Decide whether to trade
    if direction == "neutral":
        return {
            "success": True,
            "action": "观望",
            "reason": f"评分 {score}/100 — 方向中性，不执行交易",
            "analysis": analysis,
            "range_strategy": analysis.get("range_strategy"),
        }
    
    # 3. Execute trade
    side = "buy" if direction == "bullish" else "sell"
    trade_req = TradeExecuteRequest(
        symbol=req.symbol,
        side=side,
        mode=req.mode,
        entry_price=fd.get("entry_price"),
        tp_price=fd.get("exit_price"),
        sl_price=fd.get("stop_loss"),
        leverage=fd.get("leverage"),
        account_balance=req.account_balance,
        risk_pct=req.risk_pct,
    )
    trade_result = await execute_trade(trade_req)
    
    if not trade_result.get("success"):
        return {"success": False, "error": trade_result.get("error", "交易执行失败"), "analysis": analysis}
    
    return {
        "success": True,
        "action": f"{'做多' if side == 'buy' else '做空'} {req.symbol}",
        "score": score,
        "position": trade_result.get("position"),
        "summary": trade_result.get("summary"),
        "analysis": analysis,
        "trade": trade_result,
    }


@app.get("/api/trade/history")
async def trade_history(start_date: str = None, end_date: str = None, symbol: str = None):
    """获取交易历史 — 支持按日期和交易对过滤"""
    from collections import defaultdict
    
    # Combine paper_positions (closed) + risk_manager persisted trades
    all_closed = []
    
    # From in-memory paper positions
    for p in paper_positions:
        if p.get("status") != "closed":
            continue
        all_closed.append({
            "id": p.get("id", ""),
            "symbol": p.get("symbol", ""),
            "side": p.get("side", ""),
            "entry_price": p.get("entry_price", 0),
            "close_price": p.get("current_price", 0),
            "amount": p.get("amount", 0),
            "leverage": p.get("leverage", 1),
            "tp_price": p.get("tp_price"),
            "sl_price": p.get("sl_price"),
            "position_value": p.get("position_value", 0),
            "margin_required": p.get("margin_required", 0),
            "pnl": p.get("pnl", 0),
            "roe": p.get("roe", 0),
            "source": p.get("source", "ai"),
            "mode": p.get("mode", "paper"),
            "opened_at": p.get("opened_at", ""),
            "closed_at": p.get("closed_at", ""),
            "close_reason": p.get("close_reason", "manual"),
        })
    
    # From risk_manager persisted trades (if not already in paper_positions)
    existing_ids = set(t["id"] for t in all_closed)
    for t in risk_manager.trades:
        if t.status != "closed" or t.id in existing_ids:
            continue
        all_closed.append({
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": t.entry_price,
            "close_price": t.exit_price or 0,
            "amount": t.amount,
            "leverage": t.leverage,
            "tp_price": t.tp_price,
            "sl_price": t.sl_price,
            "position_value": t.amount * t.entry_price if t.entry_price else 0,
            "margin_required": (t.amount * t.entry_price / t.leverage) if t.entry_price and t.leverage else 0,
            "pnl": t.pnl,
            "roe": t.roe,
            "source": t.source,
            "mode": "paper",
            "opened_at": t.opened_at,
            "closed_at": t.closed_at,
            "close_reason": t.close_reason,
        })
    
    # Sort by closed_at descending
    all_closed.sort(key=lambda x: x.get("closed_at", ""), reverse=True)
    
    # Filter by date range
    if start_date:
        all_closed = [t for t in all_closed if t.get("closed_at", "")[:10] >= start_date]
    if end_date:
        all_closed = [t for t in all_closed if t.get("closed_at", "")[:10] <= end_date]
    if symbol:
        all_closed = [t for t in all_closed if t.get("symbol") == symbol]
    
    # Daily PnL summaries
    daily_pnl = defaultdict(lambda: {"pnl": 0, "trades": 0, "wins": 0, "losses": 0})
    for t in all_closed:
        day = t.get("closed_at", "")[:10]
        if day:
            daily_pnl[day]["pnl"] += t.get("pnl", 0)
            daily_pnl[day]["trades"] += 1
            if t.get("pnl", 0) > 0:
                daily_pnl[day]["wins"] += 1
            elif t.get("pnl", 0) < 0:
                daily_pnl[day]["losses"] += 1
    
    # Convert to sorted list
    daily_summary = []
    for day, data in sorted(daily_pnl.items(), reverse=True):
        daily_summary.append({
            "date": day,
            "pnl": round(data["pnl"], 2),
            "trades": data["trades"],
            "wins": data["wins"],
            "losses": data["losses"],
            "win_rate": round(data["wins"] / data["trades"] * 100, 1) if data["trades"] > 0 else 0,
        })
    
    # Cumulative stats
    total_pnl = sum(t.get("pnl", 0) for t in all_closed)
    wins = [t for t in all_closed if t.get("pnl", 0) > 0]
    losses = [t for t in all_closed if t.get("pnl", 0) < 0]
    total_profit = sum(t["pnl"] for t in wins)
    total_loss = abs(sum(t["pnl"] for t in losses))
    
    # Equity curve
    equity = []
    running = 0
    for t in sorted(all_closed, key=lambda x: x.get("closed_at", "")):
        running += t.get("pnl", 0)
        equity.append(round(running, 2))
    
    return {
        "success": True,
        "trades": all_closed,
        "count": len(all_closed),
        "daily_summary": daily_summary,
        "stats": {
            "total_pnl": round(total_pnl, 2),
            "total_trades": len(all_closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(all_closed) * 100, 1) if all_closed else 0,
            "avg_pnl": round(total_pnl / len(all_closed), 2) if all_closed else 0,
            "avg_win": round(total_profit / len(wins), 2) if wins else 0,
            "avg_loss": round(total_loss / len(losses), 2) if losses else 0,
            "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else 0,
            "best_trade": round(max((t["pnl"] for t in all_closed), default=0), 2),
            "worst_trade": round(min((t["pnl"] for t in all_closed), default=0), 2),
        },
        "equity_curve": equity[-50:],
    }


# ===== 托管交易系统 API =====
import asyncio

# === 托管状态持久化 ===
MANAGED_STATE_FILE = os.path.join(os.path.dirname(__file__), "managed_state.json")

def _save_managed_state():
    """保存托管状态到文件 — 热重载后可恢复"""
    try:
        save_data = {k: v for k, v in managed_state.items() if k != "task"}
        with open(MANAGED_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.warning(f"保存托管状态失败: {e}")

def _load_managed_state():
    """从文件恢复托管状态"""
    try:
        if os.path.exists(MANAGED_STATE_FILE):
            with open(MANAGED_STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("running"):
                logger.info(f"🔄 检测到未完成的托管会话, 将自动恢复: {saved.get('symbol')} | {saved.get('mode')}")
                return saved
    except Exception as e:
        logger.warning(f"读取托管状态失败: {e}")
    return None

_restored = _load_managed_state()

managed_state = {
    "running": False,
    "task": None,
    "symbol": "BTCUSDT",
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "mode": "paper",
    "interval_minutes": 5,
    "account_balance": paper_balance,
    "risk_pct": 2.0,
    "use_llm": False,
    "auto_threshold": 55,
    "started_at": None,
    "stopped_at": None,
    "cycles": 0,
    "last_analysis": None,
    "analysis_history": [],
    "strategy_log": [],
    "trades_executed": 0,
    "session_pnl": 0,
    "deep_bias": None,
    "crisis_mode": False,
    "crisis_info": {},
    "_per_symbol": {},  # per-symbol gate tracking
}

# 如果有恢复数据，覆盖默认值
if _restored:
    for k, v in _restored.items():
        if k != "task":
            managed_state[k] = v

async def _managed_loop():
    """托管交易主循环 — 多币种+危机模式自动切换"""
    while managed_state["running"]:
        try:
            managed_state["cycles"] += 1
            cycle = managed_state["cycles"]
            base_symbols = managed_state.get("symbols", [managed_state.get("symbol", "BTCUSDT")])
            
            # ===== DYNAMIC SCANNING (HOT & System 2 Target Selection) =====
            actual_symbols = []
            for sym in base_symbols:
                if sym.upper() == "HOT":
                    try:
                        # System 2 动态猎物池 (Dynamic Target Selection)
                        # We only update the heavy target list every 24 cycles
                        if cycle == 1 or cycle % 24 == 0 or "system2_watchlist" not in managed_state:
                            hot_syms = await _exchange_data.get_top_volume_symbols(limit=5)
                            logger.info(f"🌐 [System 2 扫描] 新猎物池入选: {', '.join(hot_syms)}")
                            managed_state["system2_watchlist"] = hot_syms
                        
                        actual_symbols.extend(managed_state.get("system2_watchlist", []))
                    except Exception as e:
                        logger.warning(f"获取全网热点失败: {e}")
                else:
                    actual_symbols.append(sym)
                    
            # Deduplicate while preserving order, limit to 15 symbols to prevent rate limits
            symbols = list(dict.fromkeys(actual_symbols))[:15]
            
            # Sync balance to risk manager each cycle
            risk_manager.update_balance(managed_state["account_balance"])
            
            # ===== CRISIS MODE DETECTION (once per cycle, shared) =====
            try:
                crisis_info = await detect_crisis_mode()
                managed_state["crisis_mode"] = crisis_info.get("is_crisis", False)
                managed_state["crisis_info"] = crisis_info
                if cycle <= 3 or cycle % 10 == 0:
                    mode_label = "🔴 危机模式" if managed_state["crisis_mode"] else "🟢 正常模式"
                    logger.info(f"Cycle {cycle} | {mode_label} | {crisis_info.get('reason', '')}")
            except Exception as e:
                logger.warning(f"危机检测失败: {e}")
                
            # ===== SYSTEM 2 (Hybrid AI) BACKGROUND CHECKS =====
            if cycle == 1 or cycle % 12 == 0:
                try:
                    from backend.agents.base_agent import AgentType
                    # 1. Macro Veto Power
                    macro_agent = orchestrator.agents.get(AgentType.MACRO)
                    if macro_agent:
                        macro_analysis = await macro_agent.analyze("BTCUSDT", "1d", user_config={"force_high_risk_macro": False})
                        is_high_risk = macro_analysis.metadata.get("is_high_risk_regime", False)
                        reason = macro_analysis.metadata.get("high_risk_reason", "")
                        risk_manager.set_macro_regime(is_high_risk, reason)
                        
                    # 2. Dynamic Kelly Limits
                    tech_agent = orchestrator.agents.get(AgentType.TECHNICAL)
                    if tech_agent:
                        tech_analysis = await tech_agent.analyze("BTCUSDT", "1d", user_config={})
                        max_risk = tech_analysis.metadata.get("dynamic_max_risk", 0.05)
                        reason = tech_analysis.metadata.get("market_structure_reason", "")
                        risk_manager.set_dynamic_risk_limit(max_risk, reason)
                except Exception as e:
                    logger.warning(f"System 2 后台检查失败: {e}")
            
            # ===== ITERATE OVER EACH SYMBOL =====
            for sym in symbols:
                try:
                    await _process_symbol(cycle, sym)
                except Exception as sym_err:
                    logger.error(f"处理{sym}失败: {sym_err}")
                    managed_state["strategy_log"].append({
                        "cycle": cycle, "time": datetime.now().isoformat(),
                        "event": "symbol_error", "symbol": sym,
                        "detail": str(sym_err),
                    })
                await asyncio.sleep(2)  # Small delay between symbols
            
            # ===== CHECK ALL OPEN POSITIONS FOR SL/TP =====
            await _check_all_positions(cycle, symbols)
            
        except Exception as e:
            logger.error(f"托管循环错误: {e}")
            managed_state["strategy_log"].append({
                "cycle": managed_state["cycles"],
                "time": datetime.now().isoformat(),
                "event": "error",
                "detail": str(e),
            })
        
        # 每个周期结束后保存状态
        _save_managed_state()
        await asyncio.sleep(managed_state["interval_minutes"] * 60)


def _get_sym_state(sym: str) -> dict:
    """Get per-symbol gate tracking state"""
    ps = managed_state.setdefault("_per_symbol", {})
    if sym not in ps:
        ps[sym] = {
            "_last_trade_cycle": 0,
            "_consec_losses": 0,
            "_breaker_until_cycle": 0,
            "_prev_score": 50,
        }
    return ps[sym]


async def _process_symbol(cycle: int, sym: str):
    """Process one symbol per cycle — crisis or normal mode"""
    ss = _get_sym_state(sym)
    is_crisis = managed_state.get("crisis_mode", False)
    fng_val = managed_state.get("crisis_info", {}).get("fng", 50)
    
    if is_crisis:
        # ===== CRISIS MODE: Use S5 crisis scorer =====
        result = await run_crisis_cycle(sym, fng_value=fng_val)
        direction = result.get("direction", "neutral")
        score = result.get("score", 50)
        
        # If crisis scorer says neutral (conditions not met), try normal analyzer as fallback
        if direction == "neutral":
            try:
                analyze_req = QuickAnalyzeRequest(
                    symbol=sym,
                    use_llm=managed_state.get("use_llm", False),
                    account_balance=managed_state.get("account_balance", 10000),
                    risk_pct=managed_state.get("risk_pct", 2.0),
                    deep_bias=managed_state.get("deep_bias"),
                )
                fallback = await quick_analyze(analyze_req)
                if fallback.get("success"):
                    fd = fallback.get("final_decision", {})
                    direction = fd.get("direction", "neutral")
                    score = fd.get("score", 50)
                    result = {
                        "direction": direction,
                        "entry_price": fd.get("entry_price"),
                        "tp_price": fd.get("exit_price"),
                        "sl_price": fd.get("stop_loss"),
                        "leverage": fd.get("leverage", 5),
                        "risk_pct": managed_state.get("risk_pct", 2.0),
                        "score": score,
                        "reasoning": f"[crisis→Trend回退] {fd.get('reasoning','')[:120]}",
                        "breakdown": [f"⚠️ S5無信號→切Trend分析", f"得分 {score}/100 方向 {direction}"],
                    }
                    logger.info(f"[Managed] {sym}: crisis neutral → Trend fallback: {direction} {score}")
            except Exception as e:
                logger.warning(f"[Managed] {sym}: Trend fallback failed: {e}")
        
        # Save analysis
        analysis_snap = {
            "cycle": cycle, "symbol": sym,
            "time": datetime.now().isoformat(),
            "mode": "crisis",
            "score": score, "direction": direction,
            "entry": result.get("entry_price"),
            "tp": result.get("tp_price"),
            "sl": result.get("sl_price"),
            "leverage": result.get("leverage"),
            "risk_pct": result.get("risk_pct"),
            "reasoning": result.get("reasoning", "")[:150],
            "breakdown": result.get("breakdown", []),
        }
        managed_state["last_analysis"] = analysis_snap
        managed_state["analysis_history"].append(analysis_snap)
        if len(managed_state["analysis_history"]) > 200:
            managed_state["analysis_history"] = managed_state["analysis_history"][-200:]
        
        # Crisis mode: bearish from S5 OR any direction from fallback
        threshold = managed_state.get("auto_threshold", 55)
        should_trade = direction != "neutral" and (score >= threshold or score <= (100 - threshold))
        entry_price = result.get("entry_price") or result.get("current_price")
        tp_price = result.get("tp_price")
        sl_price = result.get("sl_price")
        leverage = result.get("leverage", 2)
        risk_pct = result.get("risk_pct", 2.0)
        regime = "crisis"
    else:
        # ===== NORMAL MODE: Use existing quick_analyze =====
        analyze_req = QuickAnalyzeRequest(
            symbol=sym,
            use_llm=managed_state["use_llm"],
            account_balance=managed_state["account_balance"],
            risk_pct=managed_state["risk_pct"],
            deep_bias=managed_state.get("deep_bias"),
        )
        analysis = await quick_analyze(analyze_req)
        
        if not analysis.get("success"):
            managed_state["strategy_log"].append({
                "cycle": cycle, "symbol": sym,
                "time": datetime.now().isoformat(),
                "event": "analysis_failed",
                "detail": str(analysis.get("error", "unknown")),
            })
            return
        
        fd = analysis.get("final_decision", {})
        score = fd.get("score", 50)
        direction = fd.get("direction", "neutral")
        ri = analysis.get("risk_info", {})
        
        analysis_snap = {
            "cycle": cycle, "symbol": sym,
            "time": datetime.now().isoformat(),
            "mode": "normal",
            "score": score, "direction": direction,
            "entry": fd.get("entry_price"),
            "tp": fd.get("exit_price"),
            "sl": fd.get("stop_loss"),
            "leverage": fd.get("leverage"),
            "reasoning": fd.get("reasoning", "")[:120],
        }
        managed_state["last_analysis"] = analysis_snap
        managed_state["analysis_history"].append(analysis_snap)
        if len(managed_state["analysis_history"]) > 200:
            managed_state["analysis_history"] = managed_state["analysis_history"][-200:]
        
        threshold = managed_state["auto_threshold"]
        # should_trade: bullish needs score >= threshold, bearish needs score <= (100-threshold)
        # e.g. threshold=55: bullish >= 55, bearish <= 45 (but direction already set by 62/38 cutoff)
        should_trade = direction != "neutral" and (score >= threshold or score <= (100 - threshold))
        entry_price = fd.get("entry_price")
        tp_price = fd.get("exit_price")
        sl_price = fd.get("stop_loss")
        leverage = fd.get("leverage")
        risk_pct = managed_state["risk_pct"]
        
        adx_val = analysis.get("indicators", {}).get("adx", 25)
        regime = "trending" if adx_val and adx_val >= 25 else ("ranging" if adx_val and adx_val < 20 else "transitioning")
    
    # ===== PER-SYMBOL TRADE GATES =====
    gate_reason = None
    
    # Gate 1: Cooldown
    cooldown = 2 if regime in ("trending", "crisis") else 3
    if should_trade and (cycle - ss["_last_trade_cycle"]) < cooldown:
        gate_reason = f"{sym} 冷却中({cycle - ss['_last_trade_cycle']}/{cooldown})"
        should_trade = False
    
    # Gate 2: Circuit Breaker
    if should_trade and cycle < ss["_breaker_until_cycle"]:
        gate_reason = f"{sym} 熔断中(连亏{ss['_consec_losses']}次)"
        should_trade = False
    
    # Gate 3: Duplicate Direction Guard
    if should_trade:
        side_check = "buy" if direction == "bullish" else "sell"
        has_same = any(
            p.get("side") == side_check and p.get("symbol") == sym and p.get("status") == "open"
            for p in paper_positions
        )
        if not has_same:
            for pos in position_manager.positions.values():
                if pos.side == side_check and pos.symbol == sym and pos.status == "open":
                    has_same = True
                    break
        if has_same:
            gate_reason = f"{sym} 已有同方向持仓({side_check})"
            should_trade = False
    
    # Gate 4: ADX Gate — ADX < 15 means no trend, block trade
    if should_trade and not is_crisis:
        adx_gate = analysis.get("indicators", {}).get("adx", 25) if not is_crisis else 25
        if adx_gate is not None and adx_gate < 15:
            gate_reason = f"{sym} ADX={adx_gate:.1f}<15(无趋势,禁止交易)"
            should_trade = False
    
    if gate_reason:
        managed_state["strategy_log"].append({
            "cycle": cycle, "symbol": sym,
            "time": datetime.now().isoformat(),
            "event": "gate_blocked", "direction": direction,
            "score": score, "reason": gate_reason,
        })
    
    # ===== EXECUTE TRADE =====
    max_hold = 72 if regime == "crisis" else {"trending": 36, "transitioning": 24, "ranging": 18}.get(regime, 24)
    
    if should_trade:
        side = "buy" if direction == "bullish" else "sell"
        trade_req = TradeExecuteRequest(
            symbol=sym,
            side=side,
            mode=managed_state["mode"],
            entry_price=entry_price,
            tp_price=tp_price,
            sl_price=sl_price,
            leverage=leverage,
            account_balance=managed_state["account_balance"],
            risk_pct=risk_pct,
        )
        trade_result = await execute_trade(trade_req)
        
        if trade_result.get("success"):
            managed_state["trades_executed"] += 1
            ss["_last_trade_cycle"] = cycle
            ss["_consec_losses"] = 0
            
            pos_id = trade_result.get("position", {}).get("id")
            if pos_id and pos_id in position_manager.positions:
                position_manager.positions[pos_id].max_hold_hours = max_hold
                position_manager._save()
            
            mode_tag = "🔴危机" if is_crisis else "🟢正常"
            managed_state["strategy_log"].append({
                "cycle": cycle, "symbol": sym,
                "time": datetime.now().isoformat(),
                "event": "trade_executed",
                "mode": "crisis" if is_crisis else "normal",
                "direction": side, "score": score,
                "entry": entry_price, "tp": tp_price, "sl": sl_price,
                "leverage": leverage, "risk_pct": risk_pct,
                "regime": regime, "max_hold_hours": max_hold,
            })
            logger.info(f"🤖 {mode_tag} {side.upper()} {sym} @ ${entry_price:,.2f} | 评分{score} | R{risk_pct:.1f}% L{leverage}x | {regime}")
    else:
        # Build detailed hold reason
        reasoning_text = analysis_snap.get("reasoning", "")
        hold_detail = gate_reason or (
            f"{'中性(无方向信号)' if direction == 'neutral' else '信号不够强'}"
            + (f" | {reasoning_text[:80]}" if reasoning_text else "")
        )
        managed_state["strategy_log"].append({
            "cycle": cycle, "symbol": sym,
            "time": datetime.now().isoformat(),
            "event": "hold",
            "mode": "crisis" if is_crisis else "normal",
            "direction": direction, "score": score,
            "entry": analysis_snap.get("entry"),
            "tp": analysis_snap.get("tp"),
            "sl": analysis_snap.get("sl"),
            "leverage": analysis_snap.get("leverage"),
            "reason": hold_detail,
        })


async def _check_all_positions(cycle: int, symbols: list):
    """Check ALL open positions across ALL symbols for SL/TP hit"""
    import httpx as _httpx
    for p in paper_positions:
        if p["status"] != "open":
            continue
        sym = p.get("symbol", "")
        if sym not in symbols:
            continue
        
        # Get current price (use Binance Futures for consistency with execute_trade)
        try:
            async with _httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price",
                                     params={"symbol": sym})
                if r.status_code == 200:
                    price = float(r.json().get("price", 0))
                else:
                    continue
        except Exception:
            continue
        
        if price <= 0:
            continue
        
        ss = _get_sym_state(sym)
        
        if p["side"] == "buy":
            if p.get("tp_price") and price >= p["tp_price"]:
                await close_trade(TradeCloseRequest(position_id=p["id"], close_price=price))
                managed_state["strategy_log"].append({"cycle": cycle, "symbol": sym, "time": datetime.now().isoformat(), "event": "tp_hit", "pnl": p.get("pnl", 0)})
                ss["_consec_losses"] = 0
            elif p.get("sl_price") and price <= p["sl_price"]:
                await close_trade(TradeCloseRequest(position_id=p["id"], close_price=price))
                managed_state["strategy_log"].append({"cycle": cycle, "symbol": sym, "time": datetime.now().isoformat(), "event": "sl_hit", "pnl": p.get("pnl", 0)})
                ss["_consec_losses"] += 1
                if ss["_consec_losses"] >= 3:
                    ss["_breaker_until_cycle"] = cycle + 12
                    logger.warning(f"🔴 {sym} 熔断: 连续{ss['_consec_losses']}次止损")
        else:  # sell
            if p.get("tp_price") and price <= p["tp_price"]:
                await close_trade(TradeCloseRequest(position_id=p["id"], close_price=price))
                managed_state["strategy_log"].append({"cycle": cycle, "symbol": sym, "time": datetime.now().isoformat(), "event": "tp_hit", "pnl": p.get("pnl", 0)})
                ss["_consec_losses"] = 0
            elif p.get("sl_price") and price >= p["sl_price"]:
                await close_trade(TradeCloseRequest(position_id=p["id"], close_price=price))
                managed_state["strategy_log"].append({"cycle": cycle, "symbol": sym, "time": datetime.now().isoformat(), "event": "sl_hit", "pnl": p.get("pnl", 0)})
                ss["_consec_losses"] += 1
                if ss["_consec_losses"] >= 3:
                    ss["_breaker_until_cycle"] = cycle + 12
                    logger.warning(f"🔴 {sym} 熔断: 连续{ss['_consec_losses']}次止损")

class ManagedStartRequest(BaseModel):
    symbol: str = "BTCUSDT"
    symbols: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    mode: str = "paper"
    interval_minutes: int = 5
    account_balance: float = 10000
    risk_pct: float = 2.0
    use_llm: bool = False
    auto_threshold: int = 55

@app.post("/api/managed/start")
async def managed_start(req: ManagedStartRequest):
    """启动AI托管交易"""
    if managed_state["running"]:
        return {"success": False, "error": "托管已在运行中", "status": managed_state}
    
    managed_state.update({
        "running": True,
        "symbol": req.symbol,
        "symbols": req.symbols if req.symbols else [req.symbol],
        "mode": req.mode,
        "interval_minutes": req.interval_minutes,
        "account_balance": req.account_balance,
        "risk_pct": req.risk_pct,
        "use_llm": req.use_llm,
        "auto_threshold": req.auto_threshold,
        "started_at": datetime.now().isoformat(),
        "stopped_at": None,
        "cycles": 0,
        "last_analysis": None,
        "analysis_history": [],
        "strategy_log": [],
        "trades_executed": 0,
        "session_pnl": 0,
        "crisis_mode": False,
        "crisis_info": {},
        "_per_symbol": {},
    })
    
    managed_state["task"] = asyncio.create_task(_managed_loop())
    
    # Sync balance to risk manager
    risk_manager.update_balance(req.account_balance)
    
    # 持久化状态 — 热重载后可恢复
    _save_managed_state()
    
    sym_list = managed_state["symbols"]
    logger.info(f"🤖 AI托管启动: {sym_list} | {req.mode} | 间隔{req.interval_minutes}分钟 | 余额${req.account_balance:,.0f} | 风险{req.risk_pct}% | 多币种+危机模式")
    
    return {
        "success": True,
        "message": f"AI托管已启动 — {','.join(sym_list)} {'模拟盘' if req.mode == 'paper' else '🔴实盘'} (危机模式自动切换)",
        "config": {
            "symbol": req.symbol,
            "mode": req.mode,
            "interval": f"{req.interval_minutes}分钟",
            "balance": f"${req.account_balance:,.0f}",
            "risk": f"{req.risk_pct}%",
            "threshold": req.auto_threshold,
            "use_llm": req.use_llm,
        }
    }

@app.post("/api/managed/stop")
async def managed_stop():
    """停止AI托管交易"""
    if not managed_state["running"]:
        return {"success": False, "error": "托管未在运行"}
    
    managed_state["running"] = False
    managed_state["stopped_at"] = datetime.now().isoformat()
    if managed_state["task"]:
        managed_state["task"].cancel()
        managed_state["task"] = None
    
    # 持久化停止状态
    _save_managed_state()
    
    # Calculate session PnL
    closed = [p for p in paper_positions if p.get("status") == "closed"]
    session_pnl = sum(p.get("pnl", 0) for p in closed)
    open_pnl = sum(p.get("pnl", 0) for p in paper_positions if p.get("status") == "open")
    
    return {
        "success": True,
        "message": "AI托管已停止",
        "session_summary": {
            "duration": managed_state["started_at"],
            "cycles": managed_state["cycles"],
            "trades_executed": managed_state["trades_executed"],
            "closed_pnl": round(session_pnl, 2),
            "open_pnl": round(open_pnl, 2),
            "total_pnl": round(session_pnl + open_pnl, 2),
        },
        "stats": risk_manager.get_stats(),
    }

@app.get("/api/managed/status")
async def managed_status():
    """获取托管交易完整状态"""
    open_pos = [p for p in paper_positions if p.get("status") == "open"]
    closed_pos = [p for p in paper_positions if p.get("status") == "closed"]
    open_pnl = sum(p.get("pnl", 0) for p in open_pos)
    closed_pnl = sum(p.get("pnl", 0) for p in closed_pos)
    
    # Current strategy description
    last = managed_state.get("last_analysis")
    if last:
        if last["direction"] == "bullish":
            strategy_desc = f"📈 看多 — 评分 {last['score']}/100, 等待回调至 ${last.get('entry', 0):,.0f} 入场"
        elif last["direction"] == "bearish":
            strategy_desc = f"📉 看空 — 评分 {last['score']}/100, 等待反弹至 ${last.get('entry', 0):,.0f} 入场"
        else:
            strategy_desc = f"➡️ 中性/观望 — 评分 {last['score']}/100, 等待方向明确"
    else:
        strategy_desc = "⏳ 等待首次分析..."
    
    # Score trend (last 5 cycles)
    recent = managed_state["analysis_history"][-5:]
    score_trend = [a["score"] for a in recent] if recent else []
    
    # Recent events
    recent_events = managed_state["strategy_log"][-200:]
    
    return {
        "success": True,
        "running": managed_state["running"],
        "config": {
            "symbol": managed_state["symbol"],
            "mode": managed_state["mode"],
            "interval": f"{managed_state['interval_minutes']}分钟",
            "balance": managed_state["account_balance"],
            "risk_pct": managed_state["risk_pct"],
            "threshold": managed_state["auto_threshold"],
        },
        "session": {
            "started_at": managed_state["started_at"],
            "cycles": managed_state["cycles"],
            "trades_executed": managed_state["trades_executed"],
            "running_time": str(datetime.now() - datetime.fromisoformat(managed_state["started_at"])).split('.')[0] if managed_state["started_at"] else "N/A",
        },
        "current_strategy": strategy_desc,
        "last_analysis": last,
        "score_trend": score_trend,
        "portfolio": {
            "open_positions": len(open_pos),
            "open_pnl": round(open_pnl, 2),
            "closed_trades": len(closed_pos),
            "closed_pnl": round(closed_pnl, 2),
            "total_pnl": round(open_pnl + closed_pnl, 2),
            "positions": open_pos,
        },
        "recent_events": recent_events,
        "risk_stats": risk_manager.get_stats(),
    }

@app.post("/api/balance/sync")
async def balance_sync(req: dict):
    """同步模拟盘资金 — 更新后台余额 + 风控 + 仓位计算"""
    new_balance = req.get("balance", 10000)
    if new_balance <= 0:
        return {"success": False, "error": "余额必须大于0"}
    
    # Update managed state
    managed_state["account_balance"] = new_balance
    _save_managed_state()
    
    # Update risk manager
    risk_manager.update_balance(new_balance)
    
    # Recalculate open positions margin info
    open_positions = [p for p in paper_positions if p.get("status") == "open"]
    used_margin = sum(p["entry_price"] * p["amount"] / p["leverage"] for p in open_positions)
    free_margin = new_balance - used_margin
    
    logger.info(f"💰 资金同步: ${new_balance:,.0f} | 已用保证金: ${used_margin:,.0f} | 可用: ${free_margin:,.0f}")
    
    return {
        "success": True,
        "balance": new_balance,
        "used_margin": round(used_margin, 2),
        "free_margin": round(free_margin, 2),
        "risk_pct": managed_state.get("risk_pct", 2.0),
        "max_risk": round(new_balance * managed_state.get("risk_pct", 2.0) / 100, 2),
    }

@app.get("/api/managed/report")
async def managed_report():
    """生成专业交易报告"""
    stats = risk_manager.get_stats()
    open_pos = [p for p in paper_positions if p.get("status") == "open"]
    closed_pos = [p for p in paper_positions if p.get("status") == "closed"]
    open_pnl = sum(p.get("pnl", 0) for p in open_pos)
    closed_pnl = sum(p.get("pnl", 0) for p in closed_pos)
    
    # Equity curve
    equity = [managed_state["account_balance"]]
    for p in closed_pos:
        equity.append(equity[-1] + p.get("pnl", 0))
    
    # Win/loss streaks
    trades_pl = [p.get("pnl", 0) for p in closed_pos]
    max_win_streak = 0
    max_loss_streak = 0
    current_streak = 0
    for pl in trades_pl:
        if pl > 0:
            current_streak = max(0, current_streak) + 1
            max_win_streak = max(max_win_streak, current_streak)
        elif pl < 0:
            current_streak = min(0, current_streak) - 1
            max_loss_streak = max(max_loss_streak, abs(current_streak))
        else:
            current_streak = 0
    
    return {
        "success": True,
        "report": {
            "title": f"Trading Oracle — {managed_state['symbol']} 交易报告",
            "period": f"{managed_state.get('started_at', 'N/A')} → {datetime.now().isoformat()}",
            "performance": {
                "total_pnl": round(closed_pnl + open_pnl, 2),
                "closed_pnl": round(closed_pnl, 2),
                "unrealized_pnl": round(open_pnl, 2),
                "roi_pct": round((closed_pnl + open_pnl) / managed_state["account_balance"] * 100, 2) if managed_state["account_balance"] > 0 else 0,
                "win_rate": stats.get("win_rate", 0),
                "profit_factor": stats.get("profit_factor", 0),
                "max_drawdown": stats.get("max_drawdown", 0),
                "sharpe_approx": round(closed_pnl / max(stats.get("max_drawdown", 1), 1), 2),
            },
            "activity": {
                "total_cycles": managed_state["cycles"],
                "total_trades": len(closed_pos) + len(open_pos),
                "closed_trades": len(closed_pos),
                "open_positions": len(open_pos),
                "max_win_streak": max_win_streak,
                "max_loss_streak": max_loss_streak,
            },
            "equity_curve": equity[-20:],
            "current_positions": open_pos,
            "recent_strategy": managed_state["strategy_log"][-50:],
        }
    }



# ==========================================
# 持仓管理 API
# ==========================================

class OpenPositionRequest(BaseModel):
    symbol: str
    side: str  # buy / sell
    entry_price: float
    amount: float
    leverage: int = 3
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    score: Optional[int] = 50
    reasoning: Optional[str] = ""
    source: Optional[str] = "ai"
    account_balance: Optional[float] = None


@app.post("/api/positions/open")
async def open_position(req: OpenPositionRequest):
    """开仓 — 后端创建持仓并监控 TP/SL"""
    # Risk check
    can_trade = risk_manager.can_trade()
    if not can_trade["allowed"]:
        return {"success": False, "error": can_trade["reason"]}
    
    # Exposure check
    total_margin = position_manager.get_total_margin()
    new_margin = req.amount * req.entry_price / req.leverage
    balance = risk_manager.account_balance
    if (total_margin + new_margin) / balance > 0.6:
        return {"success": False, "error": f"总保证金占用超60%上限 ({(total_margin + new_margin)/balance*100:.1f}%)"}
    
    pos = position_manager.open_position({
        "symbol": req.symbol,
        "side": req.side,
        "entry_price": req.entry_price,
        "amount": req.amount,
        "leverage": req.leverage,
        "sl_price": req.sl_price,
        "tp_price": req.tp_price,
        "score": req.score,
        "reasoning": req.reasoning,
        "source": req.source,
        "account_balance": req.account_balance or risk_manager.account_balance,
    })
    
    # Record in risk manager
    risk_manager.open_trade({
        "id": pos.id,
        "symbol": req.symbol,
        "side": req.side,
        "entry_price": req.entry_price,
        "amount": req.amount,
        "leverage": req.leverage,
        "sl_price": req.sl_price,
        "tp_price": req.tp_price,
        "source": req.source,
    })
    
    # Broadcast to frontend
    await manager.broadcast({
        "type": "position_opened",
        "position": {
            "id": pos.id,
            "symbol": pos.symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "amount": pos.amount,
            "leverage": pos.leverage,
            "sl_price": pos.sl_price,
            "tp_levels": pos.tp_levels,
            "margin_used": pos.margin_used,
            "account_balance": pos.account_balance,
        },
        "timestamp": datetime.now().isoformat(),
    })
    
    return {
        "success": True,
        "position": {
            "id": pos.id,
            "symbol": pos.symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "amount": pos.amount,
            "leverage": pos.leverage,
            "sl_price": pos.sl_price,
            "tp_levels": pos.tp_levels,
            "trailing_active": pos.trailing_active,
            "margin_used": pos.margin_used,
            "liq_price": pos.liq_price,
        }
    }


class ClosePositionRequest(BaseModel):
    position_id: Optional[str] = None
    symbol: Optional[str] = None  # Close by symbol (e.g. "BTCUSDT")
    close_price: Optional[float] = None
    reason: Optional[str] = "manual"
    pct: Optional[float] = 1.0


@app.post("/api/positions/close")
async def close_position(req: ClosePositionRequest):
    """平仓 — 先查 position_manager，再查 paper_positions"""
    # Try position_manager first
    if req.position_id in position_manager.positions:
        close_price = req.close_price
        if not close_price:
            close_price = price_monitor.get_price(
                position_manager.positions[req.position_id].symbol
            ) or None
        
        result = position_manager.close_position(
            req.position_id,
            close_price=close_price,
            reason=req.reason,
            pct=req.pct,
        )
        
        if result is None:
            return {"success": False, "error": f"持仓 {req.position_id} 不存在"}
        
        if result.get("remaining_amount", 0) <= 0:
            risk_manager.record_trade_result(result["pnl"], req.position_id)
            asyncio.create_task(on_trade_close(result))
        
        await manager.broadcast({
            "type": "position_closed",
            "result": result,
            "timestamp": datetime.now().isoformat(),
        })
        
        return {"success": True, **result}
    
    # Fallback: try paper_positions
    for p in paper_positions:
        if p.get("id") == req.position_id and p.get("status") == "open":
            import httpx
            close_price = req.close_price
            if not close_price:
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={p['symbol']}")
                    close_price = float(r.json()["price"])
            
            diff = close_price - p["entry_price"] if p["side"] == "buy" else p["entry_price"] - close_price
            pnl = round(diff * p["amount"], 2)
            roe = round(diff / p["entry_price"] * p.get("leverage", 1) * 100, 2)
            
            p["status"] = "closed"
            p["current_price"] = round(close_price, 2)
            p["pnl"] = pnl
            p["roe"] = roe
            p["closed_at"] = datetime.now().isoformat()
            p["close_reason"] = req.reason
            
            risk_manager.record_trade_result(pnl, req.position_id)
            _save_paper_positions()
            
            logger.info(f"📋 平仓(paper): {p['side']} {p['amount']:.6f} {p['symbol']} | PnL: ${pnl:+.2f} ({roe:+.1f}%)")
            
            return {
                "success": True,
                "position_id": req.position_id,
                "symbol": p["symbol"],
                "side": p["side"],
                "close_price": close_price,
                "pnl": pnl,
                "roe": roe,
                "reason": req.reason,
            }
    
    # Also try by symbol (OpenClaw often closes by symbol)
    if req.symbol:
        closed_any = False
        total_pnl = 0
        for p in paper_positions:
            if p.get("symbol") == req.symbol and p.get("status") == "open":
                import httpx
                close_price = req.close_price
                if not close_price:
                    async with httpx.AsyncClient(timeout=5) as client:
                        r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={p['symbol']}")
                        close_price = float(r.json()["price"])
                
                diff = close_price - p["entry_price"] if p["side"] == "buy" else p["entry_price"] - close_price
                pnl = round(diff * p["amount"], 2)
                
                p["status"] = "closed"
                p["current_price"] = round(close_price, 2)
                p["pnl"] = pnl
                p["closed_at"] = datetime.now().isoformat()
                p["close_reason"] = req.reason
                total_pnl += pnl
                closed_any = True
                risk_manager.record_trade_result(pnl, p["id"])
        
        if closed_any:
            _save_paper_positions()
            return {"success": True, "symbol": req.symbol, "pnl": round(total_pnl, 2), "reason": req.reason}
    
    return {"success": False, "error": f"持仓 {req.position_id or req.symbol} 不存在"}


@app.get("/api/positions")
async def get_positions():
    """获取所有活跃持仓 — 合并 position_manager + paper_positions"""
    pm_positions = position_manager.get_all_positions()
    
    # Get open paper_positions not in position_manager
    pm_ids = set(p.get("id", "") for p in pm_positions)
    open_paper = [p for p in paper_positions if p.get("status") == "open" and p.get("id") not in pm_ids]
    
    # Update paper position prices
    try:
        import httpx
        symbols = list(set(p["symbol"] for p in open_paper))
        async with httpx.AsyncClient(timeout=5) as client:
            for sym in symbols:
                r = await client.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}")
                price = float(r.json()["price"])
                for p in open_paper:
                    if p["symbol"] == sym:
                        p["current_price"] = round(price, 2)
                        diff = price - p["entry_price"] if p["side"] == "buy" else p["entry_price"] - price
                        p["pnl"] = round(diff * p["amount"], 2)
                        p["roe"] = round(diff / p["entry_price"] * p.get("leverage", 1) * 100, 2)
    except Exception:
        pass
    
    all_positions = pm_positions + open_paper
    total_margin = position_manager.get_total_margin() + sum(p.get("margin_required", 0) for p in open_paper)
    
    return {
        "success": True,
        "positions": all_positions,
        "total_margin": round(total_margin, 2),
        "position_count": len(all_positions),
    }


@app.post("/api/positions/reset")
async def reset_positions():
    """重置所有持仓、交易历史和风控状态"""
    try:
        # Clear position manager
        position_manager.positions.clear()
        position_manager.history.clear()
        position_manager._save()
        position_manager._save_history()
        
        # Clear paper positions
        paper_positions.clear()
        paper_orders.clear()
        _save_paper_positions()  # Persist cleared state
        
        # Reset risk manager state
        risk_manager.daily_pnl = 0.0
        risk_manager.consecutive_losses = 0
        risk_manager.today_trade_count = 0
        risk_manager.circuit_breaker_active = False
        risk_manager.trades.clear()
        risk_manager._save_trades()
        
        # Reset managed state
        managed_state["session_pnl"] = 0
        managed_state["trades_executed"] = 0
        managed_state["strategy_log"] = []
        managed_state["analysis_history"] = []
        
        logger.info("🗑️ 重置完成: 所有持仓、历史、风控状态已清空")
        
        return {"success": True, "message": "所有数据已重置"}
    except Exception as e:
        logger.error(f"重置失败: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/positions/stats")
async def get_position_stats():
    """获取交易统计"""
    return {
        "success": True,
        "stats": position_manager.get_stats(),
        "risk": risk_manager.get_stats(),
    }


@app.get("/api/positions/history")
async def get_position_history(limit: int = 50):
    """获取交易历史"""
    return {
        "success": True,
        "history": position_manager.get_history(limit),
    }


@app.post("/api/positions/reset")
async def reset_positions():
    """清除所有持仓和历史记录（模拟盘重置）"""
    try:
        # Clear position_manager
        position_manager.positions.clear()
        position_manager._save()
        position_manager.history.clear()
        position_manager._save_history()
        
        # Clear paper_positions (the in-memory trade list used by /api/trade/history)
        global paper_positions
        paper_positions.clear()
        
        # Clear risk_manager trades + stats
        risk_manager.trades.clear()
        risk_manager.daily_pnl = 0
        risk_manager.daily_trades = 0
        risk_manager.consecutive_losses = 0
        risk_manager.circuit_breaker_active = False
        # Persist cleared trades to disk
        if hasattr(risk_manager, '_save_trades'):
            risk_manager._save_trades()
        
        # Reset risk_manager stats
        if hasattr(risk_manager, 'stats'):
            risk_manager.stats = {
                'total_trades': 0, 'wins': 0, 'losses': 0,
                'total_pnl': 0, 'win_rate': 0, 'profit_factor': 0,
                'max_drawdown': 0, 'daily_pnl': 0,
                'account_balance': 10000,
            }
        
        logger.info("🔄 模拟盘已重置 — 所有持仓、历史、统计已清除")
        return {"success": True, "message": "已清除所有持仓和交易记录"}
    except Exception as e:
        logger.error(f"重置失败: {e}")
        return {"success": False, "error": str(e)}

# ==========================================
# 自我进化 API
# ==========================================

@app.get("/api/reflections")
async def get_reflections(limit: int = 50):
    """获取交易反思记录"""
    return {
        "success": True,
        "reflections": reflection_engine.get_all(limit),
        "total": len(reflection_engine.reflections),
    }


@app.get("/api/reflections/rules")
async def get_evolution_rules():
    """获取进化规则"""
    return {
        "success": True,
        "rules": evolution_engine.get_all_rules(),
        "active_rules": evolution_engine.get_active_rules(),
        "stats": evolution_engine.get_stats(),
    }


@app.get("/api/reflections/summary")
async def get_reflection_summary():
    """获取策略总结"""
    return {
        "success": True,
        "summary": reflection_engine.get_strategy_summary(),
        "evolution_stats": evolution_engine.get_stats(),
    }


# ==========================================
# 多币种扫描
# ==========================================

_multi_scan_cache = {"result": None, "timestamp": 0, "key": ""}
# 60-second caches for expensive multi-exchange layers (LAYER 13/14)
_liquidation_cache = {"result": None, "timestamp": 0, "symbol": ""}
_vpvr_cache = {"result": None, "vp_raw": None, "timestamp": 0, "symbol": ""}

@app.get("/api/multi-scan")
async def multi_symbol_scan(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT"):
    """多币种并行扫描 — 技术面快速评分"""
    import time as _time
    import httpx
    
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    now = _time.time()
    cache_key = ",".join(sorted(symbol_list))
    
    if (_multi_scan_cache.get("key") == cache_key and 
        now - _multi_scan_cache.get("timestamp", 0) < 120 and
        _multi_scan_cache.get("result")):
        return _multi_scan_cache["result"]
    
    async def scan_one(sym: str) -> Dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={"symbol": sym, "interval": "1h", "limit": 100}
                )
                if resp.status_code != 200:
                    return {"symbol": sym, "error": "API error"}
                klines = resp.json()
                if len(klines) < 30:
                    return {"symbol": sym, "error": "Insufficient data"}
                
                closes = [float(k[4]) for k in klines]
                volumes = [float(k[5]) for k in klines]
                highs = [float(k[2]) for k in klines]
                lows = [float(k[3]) for k in klines]
                current = closes[-1]
                
                ma7 = sum(closes[-7:]) / 7
                ma25 = sum(closes[-25:]) / 25
                
                # RSI
                deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                gains = [d if d > 0 else 0 for d in deltas[-14:]]
                loss_vals = [-d if d < 0 else 0 for d in deltas[-14:]]
                avg_gain = sum(gains) / 14
                avg_loss = sum(loss_vals) / 14
                rs = avg_gain / avg_loss if avg_loss > 0 else 100
                rsi = round(100 - (100 / (1 + rs)), 1)
                
                change_1h = round((current - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else 0
                change_4h = round((current - closes[-5]) / closes[-5] * 100, 2) if len(closes) >= 5 else 0
                change_24h = round((current - closes[-25]) / closes[-25] * 100, 2) if len(closes) >= 25 else 0
                
                vol_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
                vol_ratio = round(volumes[-1] / vol_avg, 2) if vol_avg > 0 else 1
                
                # ATR
                trs = []
                for i in range(-14, 0):
                    tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                    trs.append(tr)
                atr = sum(trs) / len(trs) if trs else current * 0.01
                
                score = 50
                if current > ma7: score += 5
                if current > ma25: score += 5
                if ma7 > ma25: score += 5
                if rsi < 30: score += 10
                elif rsi > 70: score -= 10
                if vol_ratio > 1.5: score += 5
                if change_4h > 0: score += 3
                
                direction = "bullish" if score >= 65 else ("bearish" if score <= 35 else "neutral")
                
                return {
                    "symbol": sym, "price": round(current, 2), "score": min(100, max(0, score)),
                    "direction": direction, "rsi": rsi, "change_1h": change_1h,
                    "change_4h": change_4h, "change_24h": change_24h,
                    "vol_ratio": vol_ratio, "atr": round(atr, 2), "atr_pct": round(atr / current * 100, 2),
                }
        except Exception as e:
            return {"symbol": sym, "error": str(e)}
    
    results = await asyncio.gather(*[scan_one(s) for s in symbol_list], return_exceptions=True)
    opportunities = [r for r in results if isinstance(r, dict) and "error" not in r]
    opportunities.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    response = {
        "success": True, "scanned": len(symbol_list),
        "opportunities": opportunities, "timestamp": datetime.now().isoformat(),
    }
    _multi_scan_cache.update({"key": cache_key, "result": response, "timestamp": now})
    return response


# ==========================================
# 回测 API
# ==========================================

@app.post("/api/backtest")
async def run_backtest(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    days: int = 30,
    score_threshold: int = 65,
    leverage: int = 3,
    risk_pct: float = 2.0,
):
    """运行策略回测"""
    from backend.trading.backtester import Backtester
    
    try:
        bt = Backtester(initial_balance=10000)
        result = await bt.run(
            symbol=symbol, interval=interval, days=days,
            score_threshold=score_threshold, leverage=leverage, risk_pct=risk_pct,
        )
        return {"success": True, "backtest": result}
    except Exception as e:
        logger.error(f"回测失败: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    logger.info("启动 Trading Oracle API V2.0...")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
