"""
FastAPI 主入口 - V2.0
多Agent协作系统 + WebSocket实时推送
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import uvicorn

from backend.agents import AgentOrchestrator


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
    'jwt_token': config.get('6551', {}).get('jwt_token')
})


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
            {"symbol": "BTCUSDT", "name": "Bitcoin"},
            {"symbol": "ETHUSDT", "name": "Ethereum"},
            {"symbol": "SOLUSDT", "name": "Solana"},
            {"symbol": "BNBUSDT", "name": "Binance Coin"},
            {"symbol": "XRPUSDT", "name": "Ripple"},
            {"symbol": "ADAUSDT", "name": "Cardano"},
            {"symbol": "DOGEUSDT", "name": "Dogecoin"},
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


if __name__ == "__main__":
    logger.info("启动 Trading Oracle API V2.0...")
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
