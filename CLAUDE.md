# Trading Oracle — AI 多Agent量化交易决策系统

## 项目概述
Trading Oracle 是一个混合架构（Hybrid Engine）AI 加密货币交易系统。核心理念是"LLM 多智能体圆桌会议提供市场感知，传统量化风控引擎负责机械执行"。

**技术栈:**
- 后端: Python / FastAPI (`backend/main.py`), 端口 8000
- 前端: React 18 + Vite + TailwindCSS + Framer Motion (`frontend_v2/`), 端口 3001
- ML: XGBoost 本地模型 (`backend/trading/models/xgb_model.json`)
- LLM: DeepSeek / Claude (可选, 用于审核层和玄学数据源)
- 数据源: Binance + OKX + Bybit + HyperLiquid (K线/OI/FR), FRED (宏观), OnchainOS (链上), Alternative.me (FNG)

## 系统架构

### 双循环引擎 (System 1 / System 2)
- **Quick Cycle (System 1)**: 每1-15分钟, 纯技术面 (`/api/quick-analyze`), <3秒
- **Deep Cycle (System 2)**: 每1-4小时, 5 Agent 全量圆桌会议 (`/api/analyze`), 60-120秒
- **信号融合**: 70% 技术分 + 30% 深度偏好 (Deep Bias)

### 5+1 Agent 圆桌
| Agent | 权重 | 数据源 |
|-------|------|--------|
| 技术分析师 📊 | 30% | Binance/OKX K线, RSI, MACD, BB, EMA |
| 链上分析师 ⛓️ | 25% | OnchainOS v6 (DEX/巨鲸/资金流) |
| 宏观分析师 🌍 | 20% | FRED API (利率/CPI/GDP/M2) |
| 情绪分析师 💬 | 15% | F&G Index + OpenNews + Twitter |
| 玄学分析师 🔮 | 10% | DeepSeek AI (八字/紫微/塔罗) |
| 主持人 🎯 | — | 加权裁决, 防中庸陷阱 |

### V4 18层评分引擎
趋势(4H) / 价格结构(HH/HL/LL/LH) / 动量(RSI+MACD) / 成交量(+OBV) / 布林带 / 恐贪指数(逆向) / SMC聪明钱(BOS/CHoCH/OB/FVG) / 进化规则 / 资金费率 / StochRSI+EMA交叉 / 大盘共振 / 订单簿深度 / 信号冲突矩阵 / 清算推算(4所) / VPVR(4所) / CoinAnk爆仓 / OI市值比 / 多空比逆向

### 风控引擎 (`backend/risk/risk_manager.py`)
- **半凯利公式 (Half-Kelly)**: 基于历史胜率+盈亏比动态计算最优敞口, 上限 0.5%-5%
- **ATR动态SL/TP**: SL = 2×ATR, TP = 3-4×ATR (信心度调优)
- **三段移动止损**: TP1达成→保本位, TP2达成→SL移至TP1, 持续追踪
- **连败降仓**: 连续3亏→仓位强制减半
- **波动率反向杠杆**: ATR/Price > 3% → 杠杆减半
- **每日熔断**: 日亏损达5%余额→全面停止交易

### ML预测引擎 (`backend/trading/ml_predictor.py`)
- XGBoost 模型, 7维特征: RSI, ADX, ATR%, VolumeRatio, TrendAlign, BB_Width, BB_Pos
- 输出: 胜率概率 (0.20-0.75 clamped), 用于 Kelly 公式的 Win Probability 输入

## 目录结构

```
backend/
├── main.py                    # FastAPI 主入口, 所有 API 路由
├── agents/                    # 5个 AI Agent + Orchestrator
│   ├── orchestrator.py        # 圆桌会议调度器
│   ├── technical_agent.py     # 技术分析
│   ├── onchain_agent.py       # 链上分析
│   ├── macro_agent.py         # 宏观分析
│   ├── sentiment_agent.py     # 情绪分析
│   └── base_agent.py          # Agent 基类
├── analysis/
│   ├── quick_tech_engine.py   # V4 18层快速评分引擎
│   ├── quick_xgb_backcast.py  # XGBoost 集成的快速分析
│   ├── volume_profile.py      # VPVR 多交易所量价分布
│   └── strategy_backtester.py # 策略回测引擎
├── risk/
│   └── risk_manager.py        # 风控核心 (Kelly/ATR/熔断/降仓)
├── trading/
│   ├── ml_predictor.py        # XGBoost ML预测器
│   └── models/xgb_model.json  # 训练好的模型权重
├── data_sources/
│   ├── exchange/              # 4交易所数据适配器
│   ├── macro/                 # FRED宏观数据
│   ├── sentiment/             # 情绪数据
│   └── metaphysical/          # 玄学数据(DeepSeek)
├── ai/
│   └── synthesizer.py         # LLM 合成/审核层
└── config/
    └── api_keys.json          # API密钥 + 模拟盘余额配置

frontend_v2/
├── src/
│   ├── App.jsx                # 主布局
│   ├── store/tradingStore.js  # Zustand 全局状态
│   └── components/
│       ├── TradingPanel.jsx   # 核心交易面板 (托管/手动/聊天)
│       ├── AgentCard.jsx      # Agent 评分卡片
│       ├── ScoreGauge.jsx     # SVG 圆环评分仪表
│       ├── FinalDecision.jsx  # 最终决策展示
│       ├── DiscussionPanel.jsx# 专家讨论面板
│       └── managed/           # AI托管子组件
```

## 核心 API 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/quick-analyze` | POST | 快速技术分析 (<3s) |
| `/api/analyze` | POST | 深度 Agent 圆桌分析 (60-120s) |
| `/api/trade/execute` | POST | 执行交易 (买/卖) |
| `/api/trade/auto` | POST | 一键分析+自动下单 |
| `/api/positions` | GET | 查看当前持仓 |
| `/api/positions/close` | POST | 平仓 (支持部分平仓) |
| `/api/managed/start` | POST | 启动AI托管 |
| `/api/managed/stop` | POST | 停止AI托管 |
| `/api/managed/status` | GET | 托管状态查询 |
| `/api/managed/report` | GET | 绩效报告 |
| `/api/multi-scan` | GET | 多币种扫描 |
| `/api/backtest` | POST | 策略回测 |
| `/api/reflections` | GET | 自我反思记录 |
| `/api/risk-status` | GET | 风控状态 |

## 开发约定

1. **后端**: 所有新路由加在 `main.py`, Agent 逻辑在 `agents/`, 风控逻辑在 `risk/`
2. **前端**: 组件放 `components/`, 状态用 Zustand (`store/tradingStore.js`)
3. **默认模拟盘**: 所有交易功能默认 paper 模式, 实盘需二次确认
4. **余额统一**: 从 `config/api_keys.json` 的 `paper_trading.balance` 读取
5. **入场价**: 始终使用下单瞬间 Binance 实时价格
6. **零假数据**: 全系统 100% 真实 API 数据
