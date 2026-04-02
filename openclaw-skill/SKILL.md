---
name: trading_oracle
description: "AI多Agent加密货币交易决策系统 — BTC/ETH/SOL 多币种实时分析、AI托管自动交易、模拟盘/实盘、持仓管理、风控、自我进化反思、策略回测、多币种扫描。Use when: user asks about crypto trading, portfolio, positions, buy/sell, analysis, managed trading, backtest, market scan, or trading strategy."
metadata:
  {
    "openclaw":
      {
        "emoji": "📊",
        "requires": { "bins": ["curl"] },
        "heartbeat":
          {
            "interval": "*/15 * * * *",
            "prompt": "检查AI托管交易状态，如果正在运行就用 /api/managed/status 获取最新状态并向用户汇报当前策略、持仓和PnL。如果没有在运行则跳过。",
          },
      },
  }
---

# Trading Oracle — AI 多Agent交易决策系统 v5.0

后端: `http://127.0.0.1:8000`。所有命令用 curl 调用。**默认中文回复。**

## 系统架构

- **5 AI Agent 圆桌会议**: 技术分析师、巨鲸追踪者(OnchainOS)、宏观领航员(FRED)、逆向交易者(F&G)、量化玄学师(DeepSeek)
- **15层评分引擎**: 趋势/RSI/MACD/布林带/成交量/ADX/进化引擎/资金费率/StochRSI&EMA/多币种共振/订单簿/信号冲突矩阵/清算推算/VPVR/多空比深度分析
- **4交易所数据**: Binance + OKX + Bybit + HyperLiquid (K线/OI/资金费率/多空比)
- **链上数据**: OnchainOS v6 API (DEX交易/Index Price/链上价格)
- **宏观数据**: FRED API (联邦基金利率/CPI/GDP/M2/失业率/收益率曲线)
- **情绪数据**: Fear&Greed Index + 6551 OpenNews + Twitter + BlockBeats
- **AI玄学**: DeepSeek AI (八字/紫微/占星/塔罗 — 真实AI推理，非模拟)
- **自我进化系统**: 每笔亏损自动反思 → 提取规则 → 信心衰减 → 持续优化
- **100% 真实数据**: 全系统零假数据，所有指标来源于真实API

---

## 🤖 一、AI 托管交易（核心功能）

### 启动托管

用户说 "帮我托管交易"、"开启AI托管"、"自动帮我炒BTC":

```bash
curl -s -X POST http://127.0.0.1:8000/api/managed/start \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","mode":"paper","interval_minutes":5,"account_balance":10000,"risk_pct":2.0,"use_llm":false,"auto_threshold":55}'
```

**参数说明:**
- `symbol`: 交易对 (BTCUSDT, ETHUSDT, SOLUSDT)
- `mode`: "paper" 模拟盘 / "live" 实盘 (⚠️实盘需二次确认)
- `interval_minutes`: 分析间隔 (分钟)，建议 3-15
- `account_balance`: 模拟盘余额
- `risk_pct`: 每笔风险% (1-5)
- `use_llm`: true开启LLM辅助分析 (更准但更慢)
- `auto_threshold`: 自动执行阈值 (45-70，越低越容易执行)

回复:
```
🤖 AI托管已启动
━━━━━━━━━━━━━━━━
交易对: {symbol} | 模式: {mode}
分析频率: 每 {interval} 分钟
初始资金: ${balance}
单笔风险: {risk_pct}%
执行阈值: ≥{threshold}做多 / ≤{100-threshold}做空
AI分析: {use_llm ? '技术+LLM' : '纯技术'}
━━━━━━━━━━━━━━━━
系统将自动分析行情并在信号明确时执行交易。
```

### 查看托管状态

用户问 "托管怎么样了"、"状态"、"现在什么策略":

```bash
curl -s http://127.0.0.1:8000/api/managed/status
```

如果 running=false，回复: "⏹ AI托管未运行。发送'启动托管'开始。"

### 停止托管

```bash
curl -s -X POST http://127.0.0.1:8000/api/managed/stop
```

### 交易报告

```bash
curl -s http://127.0.0.1:8000/api/managed/report
```

---

## 二、手动分析

### 快速分析 (<3秒, 15层评分)

```bash
# 纯技术
curl -s -X POST http://127.0.0.1:8000/api/quick-analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","use_llm":false}'

# 技术+LLM (~8秒)
curl -s -X POST http://127.0.0.1:8000/api/quick-analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","use_llm":true,"account_balance":10000,"risk_pct":2.0}'
```

返回: tech_score, direction, entry/tp/sl, leverage, rr_ratio, position_size, breakdown (含15层评分明细)

**15层评分明细:**
1. 趋势(MA) ±15 | 2. RSI ±10 | 3. MACD ±10 | 4. 布林带 ±5 | 5. 成交量 ±10
6. ADX Gate | 7. 进化引擎 ±var | 8. 资金费率 ±5 | 9. StochRSI+EMA ±10
10. 多币种共振 ±8 | 11. 订单簿深度 ±5 | 12. 信号冲突矩阵 ±8
13. 清算推算(4所) ±5 | 14. VPVR(4所) ±5 | 15. **多空比(3所×6维) ±12**

回复:
```
📊 {symbol} 快速分析
评分: {tech_score}/100 | 方向: {direction}
入场: ${entry} → 🎯 TP: ${tp} | 🛑 SL: ${sl}
杠杆: {lev}x | R:R {rr}:1
💰 仓位: {pos} (${value}) | 保证金: ${margin}
⚠️ 最大风险: ${risk} ({risk_pct}%)
```

### 深度分析（Agent圆桌 60-120秒）

```bash
curl -s -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","interval":"1h"}'
```

**深度循环增强数据 (enriched_context):**
- VPVR: 4交易所聚合成交量分布 (POC/VAH/VAL)
- 清算推算: 4交易所FR+OI+整数关口分析
- 订单簿: 买卖盘深度偏差
- 多空比深度: 3交易所L/S×6维分析 (共识/极端/FR交叉/OI联动/价格背离/偏差)
- OnchainOS: DEX交易/Index Price/链上价格

---

## 三、手动交易

### 一键交易 (分析+自动下单)

```bash
curl -s -X POST http://127.0.0.1:8000/api/trade/auto \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","mode":"paper","account_balance":10000,"risk_pct":2.0}'
```

### 指定方向下单

```bash
# 做多
curl -s -X POST http://127.0.0.1:8000/api/trade/execute \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"buy","mode":"paper","account_balance":10000,"risk_pct":2.0}'

# 做空
curl -s -X POST http://127.0.0.1:8000/api/trade/execute \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"sell","mode":"paper","amount":0.05,"leverage":3}'
```

### 高级开仓（支持DCA分批建仓）

```bash
curl -s -X POST http://127.0.0.1:8000/api/positions/open \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"buy","amount":0.01,"leverage":3,"tp":70000,"sl":65000,"scale_in":true}'
```

`scale_in=true`: 60%立即开仓 + 40%挂单在回调位自动加仓

### 查看持仓

```bash
curl -s http://127.0.0.1:8000/api/positions
```

### 平仓

```bash
# 平指定币种
curl -s -X POST http://127.0.0.1:8000/api/positions/close \
  -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT"}'

# 部分平仓
curl -s -X POST http://127.0.0.1:8000/api/positions/close \
  -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT","close_pct":50}'
```

### 持仓统计 & 历史

```bash
curl -s http://127.0.0.1:8000/api/positions/stats
curl -s "http://127.0.0.1:8000/api/positions/history?limit=20"
curl -s "http://127.0.0.1:8000/api/trade/history?filter=today"
```

---

## 四、多币种扫描

用户说 "扫描市场"、"有什么机会"、"哪个币值得看":

```bash
# 扫描6个主流币种
curl -s "http://127.0.0.1:8000/api/multi-scan?symbols=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT"
```

返回每个币种的 score, direction, price, change_4h，按评分排序。

回复:
```
📡 多币种扫描
━━━━━━━━━━━━━━━━
{symbol} | {score}/100 | {direction} | ${price} | {change_4h}%
...
```

---

## 五、策略回测

用户说 "回测一下BTC"、"测试策略"、"backtest":

```bash
# BTC 30天回测
curl -s -X POST "http://127.0.0.1:8000/api/backtest?symbol=BTCUSDT&days=30&score_threshold=65&leverage=3&risk_pct=2.0"

# ETH 7天回测
curl -s -X POST "http://127.0.0.1:8000/api/backtest?symbol=ETHUSDT&days=7&score_threshold=60"
```

**参数:**
- `symbol`: 交易对
- `days`: 回测天数 (7-90)
- `score_threshold`: 开仓阈值 (55-75)
- `leverage`: 杠杆 (1-10)
- `risk_pct`: 风险百分比

返回: total_trades, win_rate, total_pnl, max_drawdown_pct, sharpe_ratio, profit_factor, rr_ratio, equity_curve

回复:
```
🔬 策略回测 — {symbol} 最近{days}天
━━━━━━━━━━━━━━━━━━━━━━━
📊 总交易: {total_trades}笔 | 胜率: {win_rate}%
💰 PnL: ${total_pnl} ({total_pnl_pct}%)
📉 最大回撤: {max_drawdown_pct}%
📈 夏普比率: {sharpe_ratio} | 利润因子: {profit_factor}
⚖️ 盈亏比: {rr_ratio}:1
```

---

## 六、自我进化系统

### 查看反思记录

用户说 "看看反思"、"学到了什么"、"进化记录":

```bash
curl -s "http://127.0.0.1:8000/api/reflections?limit=10"
```

### 查看进化规则

```bash
curl -s http://127.0.0.1:8000/api/reflections/rules
```

返回: active_rules (名称, 条件, 信心度), stats (总规则, 活跃, 平均信心)

### 查看进化摘要

```bash
curl -s http://127.0.0.1:8000/api/reflections/summary
```

回复:
```
🧠 AI进化系统
━━━━━━━━━━━
活跃规则: {active_rules}条 (平均信心 {avg_confidence}%)
总反思: {total_reflections}条

📋 当前规则:
{for each rule: 名称 | 信心度 | 触发条件}

💡 最近教训:
{for each reflection: 原因 → 教训 → 建议}
```

---

## 七、风控与市场数据

```bash
# 风控状态
curl -s http://127.0.0.1:8000/api/risk-status

# 多空比 (Binance/OKX/Bybit 三所)
curl -s "http://127.0.0.1:8000/api/long-short?symbol=BTCUSDT"

# 实时价格
curl -s "http://127.0.0.1:8000/api/price?symbol=BTCUSDT"

# K线数据
curl -s "http://127.0.0.1:8000/api/klines?symbol=BTCUSDT&interval=1h&limit=24"

# 系统健康
curl -s http://127.0.0.1:8000/api/health
```

---

## 八、对话模式

```bash
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"BTC现在适合进场吗？","symbol":"BTCUSDT"}'
```

---

## 💡 用户意图速查

| 用户说 | 调用 | 关键参数 |
|--------|------|----------|
| 帮我托管 / 开启AI / 自动交易 | POST managed/start | mode=paper |
| 托管状态 / 怎么样了 / 策略 | GET managed/status | — |
| 停止托管 / 关掉 | POST managed/stop | — |
| 报告 / 业绩 / 统计 | GET managed/report | — |
| BTC怎么样 / 分析一下 | POST quick-analyze | use_llm=false |
| 详细分析 / 深入分析 | POST quick-analyze | use_llm=true |
| 深度分析 / Agent圆桌 | POST analyze | interval=1h |
| 帮我买 / 做多 | POST trade/auto | side=buy |
| 做空 / 空BTC | POST trade/execute | side=sell |
| 持仓 / 仓位 | GET positions | — |
| 平仓 / 清仓 | POST positions/close | symbol |
| 扫描市场 / 哪个币好 | GET multi-scan | symbols=BTC,ETH... |
| 回测 / backtest | POST backtest | symbol, days |
| 反思 / 进化 / 学到什么 | GET reflections | — |
| 进化规则 | GET reflections/rules | — |
| 余额 / 胜率 / 风控 | GET risk-status | — |
| 多空比 | GET long-short | symbol |
| 交易历史 | GET trade/history | filter |

## 📡 数据源矩阵 (v5.0 — 100% 真实数据)

| 数据 | 来源 | 类型 |
|------|------|------|
| K线/价格 | Binance + OKX + Bybit + HyperLiquid | 4交易所聚合 |
| 多空比 | Binance + OKX + Bybit | 3交易所+6维分析 |
| 资金费率 | Binance + OKX + Bybit + HyperLiquid | 4交易所 |
| 持仓量(OI) | Binance + OKX + Bybit + HyperLiquid | 4交易所 |
| 订单簿 | Binance | 实时深度 |
| DEX交易 | OnchainOS v6 API | 真实链上 |
| Index Price | OnchainOS v6 API | CEX+DEX+Oracle聚合 |
| 宏观经济 | FRED API (美联储) | 利率/CPI/GDP/M2 |
| 市场情绪 | Alternative.me + 6551 OpenNews + Twitter | 恐贪指数+新闻+社交 |
| 玄学分析 | DeepSeek AI LLM | 真实AI推理 |

## ⚠️ 安全规则

1. **默认模拟盘** — 除非用户明确说"实盘"
2. **实盘二次确认** — 说"实盘"时回复确认，得到"确定"才执行
3. **定时汇报** — 托管运行中时，每15分钟自动汇报一次状态
4. **风险提示** — 每次交易/汇报都要显示最大风险金额
5. **策略透明** — 告诉用户当前策略是什么、为什么做出这个决定
6. **R:R过滤** — 系统自动拒绝盈亏比<1.5的交易
7. **超时止损** — 持仓超24小时且浮亏的仓位会被自动平仓
8. **进化规则** — 系统从亏损中学习，自动调整评分权重
9. **多空比告警** — L/S > 2.8 或 < 0.8 触发告警
10. **零假数据** — 全系统100%真实API数据，无硬编码/模拟/伪造
