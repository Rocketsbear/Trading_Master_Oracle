# 🎯 AI 驱动交易系统 - 完整项目规划

**项目名称**: Trading Oracle System  
**项目路径**: `D:\All_in_AI\Trading_system`  
**目标**: 构建一个全面的 AI 驱动交易系统，整合多维度数据源，提供华尔街级别的交易决策支持

---

## 📁 项目结构

```
D:\All_in_AI\Trading_system\
├── backend/                    # FastAPI 后端
│   ├── api/                   # API 端点
│   ├── data_sources/          # 数据源封装
│   │   ├── exchanges/         # 交易所 API
│   │   │   ├── binance.py
│   │   │   ├── okx.py
│   │   │   └── hyperliquid.py
│   │   ├── onchain/           # 链上数据
│   │   │   └── onchainos.py
│   │   ├── macro/             # 宏观经济
│   │   │   ├── fred.py
│   │   │   ├── news.py
│   │   │   └── twitter.py
│   │   ├── technical/         # 技术分析
│   │   │   ├── indicators.py
│   │   │   └── coinank.py
│   │   └── metaphysical/      # 玄学分析
│   │       ├── bazi.py
│   │       ├── astrology.py
│   │       └── ziwei.py
│   ├── analysis/              # 分析引擎
│   │   ├── technical.py       # 技术面分析
│   │   ├── onchain.py         # 链上分析
│   │   ├── macro.py           # 宏观分析
│   │   ├── sentiment.py       # 情绪分析
│   │   └── metaphysical.py    # 玄学分析
│   ├── ai/                    # AI 合成层
│   │   ├── synthesizer.py     # 多维度综合决策
│   │   ├── risk_manager.py    # 风险管理
│   │   └── prompts.py         # Prompt 模板
│   ├── models/                # 数据模型
│   ├── utils/                 # 工具函数
│   │   ├── validator.py       # 数据验证器
│   │   └── cache.py           # 缓存管理
│   ├── main.py                # FastAPI 入口
│   └── requirements.txt       # Python 依赖
│
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── components/        # UI 组件
│   │   │   ├── Dashboard.tsx  # 主仪表板
│   │   │   ├── TradingChart.tsx # K线图
│   │   │   ├── ScoreCards.tsx # 评分卡片
│   │   │   ├── AIRecommendation.tsx # AI 建议
│   │   │   ├── NewsPanel.tsx  # 新闻面板
│   │   │   └── MetaphysicalPanel.tsx # 玄学面板
│   │   ├── hooks/             # React Hooks
│   │   ├── services/          # API 调用
│   │   ├── types/             # TypeScript 类型
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
│
├── mcps/                       # MCP 服务器
│   ├── opennews/              # 6551 新闻 MCP
│   ├── opentwitter/           # 6551 Twitter MCP
│   ├── bazi-master/           # 八字 MCP
│   ├── astropy/               # 占星 MCP
│   └── ziwei/                 # 紫微 MCP
│
├── skills/                     # Agent Skills
│   ├── hyperliquid/           # Hyperliquid 市场数据
│   ├── agent-reach/           # 互联网数据源
│   └── self-improving-agent/  # 自我进化能力
│
├── config/                     # 配置文件
│   ├── api_keys.json          # API Keys（加密存储）
│   ├── weights.json           # 权重配置
│   ├── risk_rules.json        # 风险规则
│   └── user_profiles.json     # 用户配置（八字等）
│
├── .learnings/                 # 自我学习日志
│   ├── LEARNINGS.md
│   ├── ERRORS.md
│   └── FEATURE_REQUESTS.md
│
├── docs/                       # 文档
│   ├── API.md
│   ├── DEPLOYMENT.md
│   └── USER_GUIDE.md
│
├── tests/                      # 测试
│   ├── test_data_sources.py
│   ├── test_analysis.py
│   └── test_api.py
│
├── PROJECT_PLAN.md            # 本文件
├── README.md
└── .gitignore
```

---

## 🔌 数据源清单

### 1️⃣ **交易所 API（实时数据）**

| 数据源 | 用途 | API Key | 状态 |
|--------|------|---------|------|
| **Binance** | K线、技术指标、多空比、资金费率 | 公共 API（暂不需要 Key） | ✅ 待集成 |
| **OKX OnchainOS** | 多链数据、钱包操作 | 通过 MCP | ✅ 待集成 |
| **Hyperliquid** | 永续合约、现货数据 | 通过 Skill | ✅ 待集成 |
| **CoinAnk** | 爆仓数据、多空比、资金费率 | `your_coinank_api_key` | ✅ 已提供 |

### 2️⃣ **链上数据（小时级更新）**

| 数据源 | 用途 | 配置 | 状态 |
|--------|------|------|------|
| **onchainos MCP** | 交易所流动、巨鲸动向、链上活跃度 | MCP 服务器 | ✅ 已克隆 |

### 3️⃣ **宏观经济（日/周/月更新）**

| 数据源 | 用途 | API Key | 状态 |
|--------|------|---------|------|
| **FRED API** | GDP、CPI、失业率、利率 | `your_fred_api_key` | ✅ 已提供 |
| **6551 opennews-mcp** | 实时新闻（crypto/美股） | JWT Token（已提供） | ✅ 已克隆 |
| **6551 opentwitter-mcp** | Twitter 情绪分析 | JWT Token（已提供） | ✅ 已克隆 |

### 4️⃣ **情绪分析（实时/小时级）**

| 数据源 | 用途 | 配置 | 状态 |
|--------|------|------|------|
| **Agent-Reach** | Twitter/Reddit/YouTube/小红书/B站 | 一键安装 | ✅ 已克隆 |
| **Alternative.me** | 恐惧贪婪指数 | 免费 API | ⏳ 待集成 |
| **Google Trends** | 搜索热度 | pytrends 库 | ⏳ 待集成 |

### 5️⃣ **玄学分析（用户触发时计算）**

| 数据源 | 用途 | 配置 | 状态 |
|--------|------|------|------|
| **bazi-master** | 综合八字系统 | MCP 服务器 | ✅ 已克隆 |
| **MCPAstropy** | 西方占星 | MCP 服务器 | ✅ 已克隆 |
| **ziwei-mcp** | 紫微斗数 | MCP 服务器 | ✅ 已克隆 |
| **塔罗牌** | 随机抽取 | 内置算法 | ⏳ 待实现 |

### 6️⃣ **自我进化（持续学习）**

| 功能 | 用途 | 配置 | 状态 |
|------|------|------|------|
| **Self-Improving Agent** | 记录错误、学习经验、自动优化 | Skill | ✅ 已克隆 |

---

## 🎯 分析维度与权重

### **默认权重配置**

```json
{
  "technical": 0.30,      // 技术面
  "onchain": 0.25,        // 链上数据
  "macro": 0.20,          // 宏观经济
  "sentiment": 0.15,      // 市场情绪
  "metaphysical": 0.10    // 玄学
}
```

### **币种差异化权重**

#### BTC（数字黄金）
```json
{
  "technical": 0.25,
  "onchain": 0.25,
  "macro": 0.30,          // 宏观权重更高
  "sentiment": 0.15,
  "metaphysical": 0.05
}
```

#### ETH（世界计算机）
```json
{
  "technical": 0.25,
  "onchain": 0.35,        // 链上权重更高
  "macro": 0.15,
  "sentiment": 0.15,
  "metaphysical": 0.10
}
```

#### 山寨币
```json
{
  "technical": 0.40,      // 技术面权重更高
  "onchain": 0.25,
  "macro": 0.10,          // 宏观权重降低
  "sentiment": 0.20,
  "metaphysical": 0.05
}
```

---

## 🛡️ 风险管理规则（硬编码）

这些规则 AI 无法覆盖，必须强制执行：

```json
{
  "max_position_size": 0.10,           // 单笔最大仓位 10%
  "max_stop_loss": 0.03,               // 最大止损 3%
  "max_daily_trades": 5,               // 日内最大交易次数
  "consecutive_loss_limit": 3,         // 连续亏损 3 次暂停 24h
  "mandatory_stop_loss": true,         // 必须设置止损
  "min_risk_reward_ratio": 1.5,        // 最小盈亏比 1:1.5
  "max_leverage": 3,                   // 最大杠杆 3x
  "emergency_exit_drawdown": 0.15      // 回撤 15% 强制平仓
}
```

---

## 📊 输出格式设计

### **每个维度的详细输出**

每个分析维度必须包含：

1. ✅ **评分**（0-100）
2. ✅ **倾向**（看多/看空/中性）
3. ✅ **详细数据**（具体指标、数值）
4. ✅ **逻辑推理**（为什么这么评分）
5. ✅ **历史对比**（相似情境）
6. ✅ **风险提示**（需要警惕的点）
7. ✅ **数据时间戳**（数据更新时间）
8. ✅ **数据来源**（API/MCP 来源）

### **最终综合建议**

包含：
- 权重计算过程
- 多空倾向分析
- 核心逻辑（支持/反对理由）
- 交易建议（方向、仓位、入场、止损、目标）
- 风险管理（最大亏损、盈亏比、持仓时间）
- 执行策略（分批建仓、加减仓条件）
- 历史相似情境
- 最终结论

---

## 🚀 开发阶段规划

### **Phase 1: 环境准备（30min）**

- [x] 创建项目目录结构
- [x] 克隆所有 MCP 服务器
- [x] 克隆所有 Skills
- [ ] 安装 Python 依赖
- [ ] 安装 Node.js 依赖
- [ ] 配置环境变量

### **Phase 2: 数据层开发（2-3h）**

#### 2.1 交易所 API 封装
- [ ] Binance API（K线、技术指标、多空比）
- [ ] OKX OnchainOS 集成
- [ ] Hyperliquid Skill 集成
- [ ] CoinAnk API（爆仓数据）

#### 2.2 链上数据集成
- [ ] onchainos MCP 调用封装
- [ ] 交易所流动数据
- [ ] 巨鲸动向追踪

#### 2.3 宏观经济数据
- [ ] FRED API 封装
- [ ] 6551 News MCP 集成
- [ ] 6551 Twitter MCP 集成

#### 2.4 情绪分析
- [ ] Agent-Reach 集成
- [ ] Alternative.me 恐惧贪婪指数
- [ ] Google Trends 集成

#### 2.5 玄学分析
- [ ] bazi-master MCP 调用
- [ ] MCPAstropy MCP 调用
- [ ] ziwei-mcp MCP 调用
- [ ] 塔罗牌算法实现

#### 2.6 数据验证与缓存
- [ ] 数据验证器（防止编造数据）
- [ ] 缓存机制（减少 API 调用）
- [ ] 数据时效性检查

### **Phase 3: 分析引擎开发（2h）**

- [ ] 技术面分析模块
  - MACD、RSI、Bollinger Bands
  - 成交量分析（OBV、VWAP）
  - 多空比、资金费率
  - 关键价位识别
  
- [ ] 链上数据分析模块
  - 交易所流动分析
  - 巨鲸行为分析
  - 持仓分布分析
  
- [ ] 宏观经济分析模块
  - 美联储政策分析
  - 流动性环境分析
  - 经济周期对比
  
- [ ] 情绪分析模块
  - 新闻热度分析
  - 社交媒体情绪
  - 恐惧贪婪指数
  
- [ ] 玄学分析模块
  - 八字流日分析
  - 紫微斗数分析
  - 占星分析
  - 塔罗牌解读

### **Phase 4: AI 合成层开发（1h）**

- [ ] 多维度权重计算
- [ ] 币种差异化逻辑
- [ ] 风险评分算法
- [ ] 交易信号生成
- [ ] Prompt 模板设计
- [ ] Claude Opus 调用封装

### **Phase 5: 后端 API 开发（1h）**

#### FastAPI 端点设计
```python
POST /api/analyze
  - 输入: symbol, timeframe, user_profile
  - 输出: 完整分析报告

GET /api/market-data/{symbol}
  - 实时市场数据

GET /api/macro-context
  - 宏观经济背景

GET /api/metaphysical
  - 玄学运势（需要用户八字）

POST /api/trade-signal
  - 生成交易信号

WebSocket /ws/realtime
  - 实时数据推送
```

### **Phase 6: 前端开发（2-3h）**

#### 6.1 UI 组件
- [ ] 主仪表板布局
- [ ] TradingView K线图集成
- [ ] 多维度评分卡片
- [ ] AI 综合建议面板
- [ ] 实时新闻面板
- [ ] 玄学运势面板
- [ ] 风险仪表盘

#### 6.2 交互功能
- [ ] 币种选择器
- [ ] 时间框架切换
- [ ] 用户配置管理（八字等）
- [ ] 手动/自动交易切换
- [ ] 交易日志查看

#### 6.3 样式设计
- [ ] 暗黑模式主题
- [ ] 响应式布局
- [ ] 动画效果

### **Phase 7: 自我进化集成（30min）**

- [ ] 配置 Self-Improving Agent
- [ ] 创建 `.learnings/` 目录
- [ ] 设置学习日志模板
- [ ] 配置自动学习触发器

### **Phase 8: 测试与优化（1h）**

- [ ] 数据源连通性测试
- [ ] 分析引擎准确性测试
- [ ] API 端点测试
- [ ] 前端功能测试
- [ ] 端到端测试
- [ ] 性能优化

### **Phase 9: 部署（30min）**

- [ ] 前端部署到 Vercel
- [ ] 后端本地运行配置
- [ ] MCP 服务器启动脚本
- [ ] 环境变量配置
- [ ] 用户文档编写

---

## 🔧 技术栈

### **后端**
- Python 3.10+
- FastAPI
- python-binance
- fredapi
- pandas
- ta-lib（技术指标）
- requests
- websockets
- redis（缓存）

### **前端**
- React 18
- TypeScript
- Vite
- TailwindCSS
- TradingView Lightweight Charts
- Recharts
- Framer Motion
- Axios
- WebSocket Client

### **MCP 服务器**
- Node.js 18+
- Python 3.10+（部分 MCP）
- Docker（部分 MCP）

### **Skills**
- Node.js（Hyperliquid）
- Python（Agent-Reach）

---

## 📝 配置文件示例

### `config/api_keys.json`（加密存储）
```json
{
  "binance": {
    "api_key": "",
    "api_secret": ""
  },
  "coinank": {
    "api_key": "your_coinank_api_key"
  },
  "fred": {
    "api_key": "your_fred_api_key"
  },
  "6551": {
    "jwt_token": "your_jwt_token"
  },
  "simmer": {
    "api_key": "your_simmer_api_key"
  }
}
```

### `config/user_profiles.json`
```json
{
  "default": {
    "name": "小火龙",
    "birth_date": "1990-01-01",
    "birth_time": "12:00",
    "birth_place": "Singapore",
    "timezone": "Asia/Singapore",
    "risk_tolerance": "medium"
  }
}
```

### `config/weights.json`
```json
{
  "default": {
    "technical": 0.30,
    "onchain": 0.25,
    "macro": 0.20,
    "sentiment": 0.15,
    "metaphysical": 0.10
  },
  "BTC": {
    "technical": 0.25,
    "onchain": 0.25,
    "macro": 0.30,
    "sentiment": 0.15,
    "metaphysical": 0.05
  },
  "ETH": {
    "technical": 0.25,
    "onchain": 0.35,
    "macro": 0.15,
    "sentiment": 0.15,
    "metaphysical": 0.10
  }
}
```

---

## ⚠️ 重要原则

### **数据真实性**
- ✅ 绝不编造数据
- ✅ 数据缺失时明确标注
- ✅ 标注数据时间戳和来源
- ✅ 过期数据给出警告

### **风险管理**
- ✅ 硬编码风险规则不可覆盖
- ✅ 强制止损
- ✅ 仓位限制
- ✅ 连续亏损自动暂停

### **用户体验**
- ✅ 详细的分析逻辑
- ✅ 清晰的数据来源
- ✅ 可执行的建议
- ✅ 历史对比参考

### **自我进化**
- ✅ 记录所有错误和学习
- ✅ 持续优化决策逻辑
- ✅ 定期回顾和改进

---

## 📅 时间估算

| 阶段 | 预计时间 | 累计时间 |
|------|---------|---------|
| Phase 1: 环境准备 | 30min | 0.5h |
| Phase 2: 数据层开发 | 2-3h | 3.5h |
| Phase 3: 分析引擎开发 | 2h | 5.5h |
| Phase 4: AI 合成层开发 | 1h | 6.5h |
| Phase 5: 后端 API 开发 | 1h | 7.5h |
| Phase 6: 前端开发 | 2-3h | 10.5h |
| Phase 7: 自我进化集成 | 30min | 11h |
| Phase 8: 测试与优化 | 1h | 12h |
| Phase 9: 部署 | 30min | 12.5h |

**总计**: 约 12-13 小时（一个完整工作日）

---

## ✅ 当前进度

- [x] 项目目录创建
- [x] MCP 服务器克隆（opennews, opentwitter, bazi-master, astropy, ziwei）
- [x] Skills 克隆（self-improving-agent, agent-reach）
- [ ] Hyperliquid Skill 克隆（进行中）
- [ ] 其他所有任务

---

## 🎯 下一步行动

1. 完成 Hyperliquid Skill 克隆
2. 安装所有依赖（Python + Node.js）
3. 配置 API Keys
4. 开始数据层开发

---

**最后更新**: 2026-03-08 14:35 GMT+8
