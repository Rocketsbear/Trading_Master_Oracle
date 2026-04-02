# Trading Oracle Frontend V2

## 项目结构

```
frontend/
├── src/
│   ├── components/
│   │   ├── TradingViewChart.jsx    # K线图
│   │   ├── AgentPanel.jsx          # Agent状态面板
│   │   ├── AgentCard.jsx           # 单个Agent卡片
│   │   ├── DiscussionPanel.jsx      # 讨论时间线
│   │   ├── MessageBubble.jsx       # 消息气泡
│   │   ├── FinalDecision.jsx       # 最终决策面板
│   │   ├── ExchangeConfig.jsx      # 交易所配置
│   │   └── SymbolSelector.jsx       # 币种选择器
│   ├── hooks/
│   │   └── useWebSocket.js         # WebSocket连接
│   ├── App.jsx                     # 主应用
│   └── main.jsx
├── public/
└── package.json
```

## 核心组件说明

### 1. TradingViewChart.jsx
- 集成TradingView的lightweight-charts
- 支持实时K线数据
- 支持技术指标叠加
- 支持多周期切换

### 2. AgentPanel.jsx + AgentCard.jsx
- 展示6个Agent的状态
- 实时更新评分
- 显示当前观点方向
- 动画效果

### 3. DiscussionPanel.jsx + MessageBubble.jsx
- 类似聊天软件的界面
- 显示每个Agent的发言
- 时间线展示讨论过程
- 支持滚动历史

### 4. FinalDecision.jsx
- 显示最终决策
- 一键下单按钮
- 风险提示

### 5. ExchangeConfig.jsx
- 用户输入交易所API Key
- 支持多个交易所
- 安全存储

## 安装依赖

```bash
npm install lightweight-charts framer-motion zustand axios
```

## 运行

```bash
npm run dev
```
