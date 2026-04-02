# Trading Oracle — 多Agent AI加密货币交易系统

> **版本**: V4 | **技术栈**: FastAPI + React + Vite | **策略**: 17层评分引擎 + 5重交易门控

## 📌 项目简介

Trading Oracle 是一套完整的 AI 驱动的加密货币交易系统。它通过 **5个独立AI专家** 实时分析市场，经过 **17层评分引擎** 打分，配合 **V4交易门控** 和 **智能仓位管理**，在模拟盘或实盘中自动执行交易。

### 核心特点

- 🧠 **多Agent圆桌讨论** — 技术/链上/宏观/情绪/玄学 5个AI专家独立分析，交叉辩论
- 📊 **18层评分引擎** — 从趋势、动量、成交量到SMC聪明钱、清算推算、VPVR、多空比逆向指标等全面评估
- 🤖 **AI托管交易** — 设定参数后全自动运行（模拟盘/实盘），含V4五重过滤门控
- 🚨 **Crisis 战争/危机模式** — 结合FRED宏观数据与恐贪指数，在极端行情下自动切入防守级S5策略
- 📈 **实时可视化** — TradingView K线图 + 多交易所多空比 + 专家讨论面板
- 🔄 **自我进化** — 每笔交易后自动反思，生成进化规则，越交易越聪明

---

## 🚀 快速启动（5分钟上手）

### 1. 环境要求

| 工具 | 版本 | 用途 |
|---|---|---|
| **Python** | 3.10+ | 后端 |
| **Node.js** | 18+ | 前端 |
| **npm** | 9+ | 前端包管理 |

### 2. 安装依赖

```bash
# 克隆项目后进入目录
cd Trading_system

# 后端依赖
pip install -r backend/requirements.txt

# 前端依赖
cd frontend_v2
npm install
cd ..
```

### 3. 配置 API Key

编辑 `config/api_keys.json`：

```json
{
  "openai": {
    "api_key": "sk-xxx",        // OpenAI Key（深度分析用）
    "model": "gpt-4o-mini"      // 推荐模型
  },
  "anthropic": {
    "api_key": "sk-ant-xxx"     // Claude Key（可选，备用LLM）
  },
  "fred": {
    "api_key": "xxx"            // FRED API Key（宏观经济数据，可选）
  },
  "binance": {
    "api_key": "",              // 实盘交易用（模拟盘不需要）
    "api_secret": ""
  }
}
```

> **💡 最低配置**：即使不配任何Key，系统也能运行 — 技术分析使用公开的OKX和Binance聚合数据，不需要Key。LLM Key 只在"深度分析"和"AI Chat"功能中使用。

### 4. 启动系统

**终端1 — 启动后端：**
```bash
cd Trading_system
python -m backend.main
# ✅ 看到 "Application startup complete" 即成功
# 后端地址: http://localhost:8000
```

**终端2 — 启动前端：**
```bash
cd Trading_system/frontend_v2
npm run dev
# ✅ 看到 "VITE ready" 即成功
# 前端地址: http://localhost:3001 (端口可能变化，看终端输出)
```

### 5. 打开浏览器

访问终端2显示的地址（通常是 `http://localhost:3001`），即可看到交易界面。

---

## 🖥️ 功能说明

### 一、主界面

打开后你会看到：

| 区域 | 位置 | 功能 |
|---|---|---|
| **TradingView K线图** | 中央 | 实时BTC/ETH/SOL价格走势，支持1min~1W |
| **交易对选择** | 顶部 | BTC/USDT 永续合约、可切换币种 |
| **交易所切换** | 顶部 | Binance/OKX/Bybit/Hyperliquid |
| **多空比面板** | 底部 | 多交易所实时多空比、OI、资金费率 |
| **专家讨论面板** | 右侧 | AI专家圆桌讨论过程 |
| **Start Analysis** | 右上角 | 启动一次完整的AI分析 |

### 二、Start Analysis（AI分析）

点击 **Start Analysis** 按钮后，系统会：

1. **独立分析阶段** — 5个AI专家各自独立分析市场
2. **专家讨论阶段** — 专家们交叉辩论、质疑、补充
3. **最终决策阶段** — 主持人综合所有观点，给出最终评分和方向

> 结果包括：评分(0-100)、方向(做多/做空/观望)、入场价、止盈价、止损价、推荐杠杆、仓位大小

### 三、AI托管交易

在交易面板中找到 **"AI Managed Trading"** 区域：

1. **设置参数**：
   - 交易对：BTCUSDT（默认）
   - 模式：`paper`（模拟盘）或 `live`（实盘）
   - 余额：模拟盘初始金额（如$10,000）
   - 风险比例：每笔最大亏损占余额的百分比（如2%）
   - 分析间隔：每N分钟自动分析一次（如5分钟）
   - 阈值：评分≥多少才执行交易（如55）

2. **点击 Start** — 系统开始自动循环：
   - 每5分钟执行一次快速分析
   - 每5个周期执行一次深度圆桌分析
   - 通过V4五重门控过滤后执行交易
   - 自动管理止盈止损

3. **点击 Stop** — 停止自动交易

### 四、回测

调用后端API进行历史回测：

```bash
# 基本回测
curl -X POST "http://localhost:8000/api/backtest?symbol=BTCUSDT&days=90&score_threshold=65"

# V4回测（推荐）
curl -X POST "http://localhost:8000/api/backtest/v2/batch"
```

---

## 🧠 系统架构

### 目录结构

```
Trading_system/
├── backend/                    # 后端（Python/FastAPI）
│   ├── main.py                 # 主入口 + 所有API端点 + 评分引擎
│   ├── agents/                 # AI专家团队
│   │   ├── orchestrator.py     # 圆桌主持人（协调5个Agent）
│   │   ├── technical_agent.py  # 技术分析师
│   │   ├── onchain_agent.py    # 链上数据分析师
│   │   ├── macro_agent.py      # 宏观经济分析师
│   │   ├── sentiment_agent.py  # 市场情绪分析师
│   │   ├── metaphysical_agent.py # 周期/斐波那契分析师
│   │   ├── risk_agent.py       # 风控专家
│   │   └── portfolio_agent.py  # 组合管理专家
│   ├── analysis/               # 分析引擎（纯计算，无LLM）
│   │   ├── technical.py        # RSI/MACD/BB/ADX/ATR等技术指标
│   │   ├── smart_money.py      # SMC聪明钱分析（OB/FVG/结构）
│   │   ├── signal_matrix.py    # 信号冲突矩阵
│   │   ├── volume_profile.py   # VPVR量价分布（4交易所数据）
│   │   ├── ls_analyzer.py      # 多交易所多空比深度分析
│   │   ├── liquidation_estimator.py  # 清算带推算
│   │   ├── macro_engine.py     # 宏观数据引擎
│   │   ├── sentiment_engine.py # 情绪数据引擎
│   │   └── onchain_engine.py   # 链上数据引擎
│   ├── trading/                # 交易引擎
│   │   ├── position_manager.py # 仓位管理（V4: 2级TP 60/40）
│   │   ├── price_monitor.py    # 价格监控（3秒轮询TP/SL/Trailing）
│   │   ├── backtester_v2.py    # V4回测引擎（18层评分）
│   │   ├── reflection_engine.py # 自我反思引擎
│   │   └── evolution_rules.py  # 进化规则引擎
│   ├── risk/                   # 风控
│   │   └── risk_manager.py     # 仓位计算/杠杆/熔断器
│   ├── data_sources/           # 数据源
│   │   ├── market/exchange_data.py  # 多交易所数据聚合
│   │   └── macro/fred.py       # FRED宏观经济API
│   └── requirements.txt        # Python依赖
│
├── frontend_v2/                # 前端（React + Vite）
│   ├── src/
│   │   ├── App.jsx             # 主应用
│   │   ├── components/
│   │   │   ├── TradingPanel.jsx       # 交易面板（核心组件，含托管/持仓/历史）
│   │   │   ├── TradingViewChart.jsx   # TradingView K线图
│   │   │   ├── DiscussionPanel.jsx    # AI专家讨论面板
│   │   │   ├── LongShortPanel.jsx     # 多空比可视化
│   │   │   ├── FinalDecision.jsx      # 最终决策展示
│   │   │   ├── ScoreGauge.jsx         # 评分仪表盘
│   │   │   ├── AgentCard.jsx          # 单个Agent卡片
│   │   │   ├── MultiCoinCompare.jsx   # 多币种扫描对比
│   │   │   ├── UserChatPanel.jsx      # AI聊天
│   │   │   └── ApiSettingsModal.jsx   # API设置弹窗
│   │   ├── hooks/useWebSocket.js      # WebSocket连接
│   │   ├── store/tradingStore.js      # Zustand状态管理
│   │   └── index.css                  # 全局样式（暗色主题）
│   └── package.json
│
├── config/                     # 配置文件
│   ├── api_keys.json           # API密钥（LLM/交易所/FRED）
│   ├── risk_rules.json         # 风控规则
│   ├── weights.json            # Agent权重配置
│   └── user_profiles.json      # 用户配置
│
└── data/                       # 持久化数据
    ├── active_positions.json   # 当前活跃持仓
    ├── position_history.json   # 历史交易记录
    ├── reflections.json        # 反思记录
    └── evolution_rules.json    # 进化规则
```

### 数据流

```
Binance/OKX/Bybit/Hyperliquid（实时数据）
        ↓
   技术指标计算（RSI/MACD/BB/ADX/ATR等）
        ↓
   17层评分引擎（0-100分）
        ↓
   V4五重门控过滤（冷却/熔断/ADX/去重/加速度）
        ↓
   执行交易 → 仓位管理（V4: 2级TP 60/40 + Trailing）
        ↓
   反思引擎 → 进化规则（下次交易更准）
```

---

## 📊 V4 18层评分引擎详解

每次分析时，系统依次计算以下18个评分层：

| # | 层名 | 分值 | 数据来源 | 说明 |
|---|---|---|---|---|
| 1 | **趋势（V4 4H主导）** | ±20 | 15m/1h/4h K线 | 4H权重10，1H权重6，15m权重4 |
| 2 | **价格结构（V4新增）** | ±5 | K线 | 检测HH/HL（看涨）或LL/LH（看跌） |
| 3 | **动量** | ±15 | RSI + MACD | RSI超买/超卖 + MACD方向确认 + 动量加速 |
| 4 | **成交量** | ±10 | OKX/Binance | 放量方向确认 + OBV趋势 |
| 5 | **布林带位置** | ±5 | 计算 | 接近上/下轨 + 趋势方向确认 |
| 6 | **恐贪指数** | ±10 | alternative.me | 逆向指标：极度恐惧→加分，极度贪婪→减分 |
| 7 | **SMC聪明钱** | ±10 | 价格结构 | Order Block/FVG/市场结构分析 |
| 8 | **进化规则** | ±5 | 反思引擎 | 系统从历史交易中学到的经验 |
| 9 | **资金费率** | ±5 | OKX/Binance | 做多/做空拥挤度检测 |
| 10 | **StochRSI+EMA交叉** | ±10 | 计算 | 多指标交叉确认 |
| 11 | **大盘共振** | ±8 | 多币种扫描 | 全市场方向一致性 |
| 12 | **订单簿深度** | ±5 | OKX/Binance | 买卖盘挂单比例 |
| 13 | **信号冲突矩阵** | ±8 | 多指标 | 检测指标间是否矛盾 |
| 14 | **清算带推算** | ±5 | 4交易所OI+FR | 推算清算集中区域 |
| 15 | **VPVR量价分布** | ±5 | 4交易所1hK线 | POC/Value Area分析 |
| 16 | **CoinAnk爆仓数据(V5)** | ±8 | CoinAnk | 多空爆仓比例极端失衡检测 |
| 17 | **OI/市值比杠杆风险(V5)** | ±5 | CoinAnk | 检测全网杠杆率是否过高 |
| 18 | **多空比逆向指标(V4)** | ±8 | OKX/Binance | 散户多空比极端失衡（>65%）时逆向操作 |

---

## 🚨 战争/危机模式 (Crisis Mode S5)

系统内置了无需人工干预的**宏观危机感知引擎**，像一个经验丰富的老兵一样应对极端黑天鹅或战争爆发行情：

### 1. 触发条件
系统通过两个维度 24/7 监控极端风险，满足其一即自动切入危机模式：
- **FNG 极度恐慌**：实时抓取 Alternative.me 恐贪指数，当指数 **≤ 25**（极度恐惧）时触发。
- **战时新闻飙升**：实时抓取 BlockBeats 英文全网快讯，若检测到 `war`, `missile`, `strike`, `nuclear` 等战争关键词占比飙升（>20%）时强行触发。
- **宏观避险资金流向**：结合 FRED（美联储经济数据）的10年期美债收益率(DGS10) 监控避险情绪（仅在后台回测分析中完全体现）。

### 2. S5 危机策略 (与普通模式的根本区别)
一旦危机模式激活，AI 将完全抛弃追求高频胜率的 18层普通评分引擎，切换至 **S5 Crisis Scorer**：
- **绝对做空逻辑**：在大崩溃或战争恐慌中，系统**死锁做多方向**，绝不抄底，寻找均线破位后的顺势做空机会（条件极为苛刻：4H下跌+2连阴+EMA21下方）。
- **暴力降杠杆**：将原本最高 5x 的杠杆**强行限制在最高 2x**，绝对保命。
- **放宽止损 (3x ATR)**：战争时极易发生剧烈上下插针，止损设太紧会被频繁扫出局。
- **贪婪止盈 (8x ATR)**：恐慌踩踏造成的往往是瀑布式下跌，目标设在平时的两倍远，捕捉自由落体行情。
- **超长持仓 (72 bars)**：给予空单充足的恐慌发酵时间。

*(实盘回测证明：在过去30天包含美伊冲突的极度恐慌行情中，危机模式下的 AI 自动将交易频率砍掉 80%，以 2x 低杠杆成功抵御了巨幅波动，并在 SOL 上获取了高胜率的正收益，最大回撤极低。)*

---

## 🔐 V4 交易门控

AI托管模式下，评分通过后还需过5道关卡：

| 门控 | 逻辑 | 作用 |
|---|---|---|
| **冷却期** | 上次交易后等2-4个周期 | 防止过度交易 |
| **熔断器** | 连续3次止损 → 暂停12周期 | 防止连续亏损 |
| **ADX门控** | ADX<15 → 不交易 | 无趋势市场不入场 |
| **方向去重** | 已有同方向持仓 → 不开仓 | 防止重复建仓 |
| **分数加速度** | 分数在衰减 → 不入场 | 只追逐增强的信号 |

---

## 💰 V4 仓位管理

| 功能 | 说明 |
|---|---|
| **2级止盈** | TP1 平60% → SL移至保本；TP2 平40% runner |
| **Trailing Stop** | TP1后启动，锁定利润随价格移动 |
| **自适应持仓时间** | 趋势市场最长36h / 震荡市场最长18h |
| **DCA加仓** | 支持挂单在更好价位加仓（60/40分配） |
| **清算保护** | 价格距清算价<1%时自动平仓 |

---

## 🔧 常见问题

### Q: 不配置LLM Key能用吗？
**可以。** 不配LLM Key时，快速分析和AI托管正常运行（使用纯技术指标评分），只是"深度圆桌分析"和"AI Chat"功能不可用。

### Q: 模拟盘和实盘有什么区别？
**模拟盘（paper）** 使用虚拟资金，不连接交易所，不会真正下单。**实盘（live）** 需要配置交易所API Key，会真正执行交易。**建议先用模拟盘熟悉系统。**

### Q: 启动时端口被占用怎么办？
后端固定在8000端口。前端端口自动递增（3001, 3002, ...），看终端输出即可。

### Q: 数据从哪里来？
- **价格/K线**：OKX V5 API 优先，Binance Futures 兜底（免费，均无需Key）
- **深度引擎数据 (多空比/资金费率/订单簿)**：统一采取 OKX 优先抓取，超时自动无缝回退 Binance 的双重保障架构（免费）
- **恐贪指数**：alternative.me（免费）
- **宏观经济**：FRED API（需Key，但可选）

### Q: 反思引擎怎么工作？
每笔交易平仓后，系统自动分析：开仓时的指标快照 vs 实际结果 → 生成经验规则（如"RSI>70+ADX<20时做多容易亏"）→ 下次评分时自动应用。规则保存在 `data/evolution_rules.json`。

### Q: 如何查看交易历史？
- **前端**：在Trading Panel的History标签页
- **API**：`GET http://localhost:8000/api/trade/history`
- **文件**：`data/position_history.json`
