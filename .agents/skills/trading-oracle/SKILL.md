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

# Trading Oracle — AI 多Agent交易决策系统 v6.1 (V4策略引擎 + Crisis Fallback)

后端: `http://127.0.0.1:8000`。所有命令用 curl 调用。**默认中文回复。**

## 📋 完整功能概览

| 模块 | 功能 |
|------|------|
| 🤖 AI托管 | 多币种自动交易、危机模式(S5/战争级)、5重门控 |
| 📊 手动分析 | 快速分析(3秒)、深度分析(60-120秒)、18层评分 |
| 🎯 手动交易 | 一键交易、DCA分批建仓、部分平仓 |
| 🔍 多币种扫描 | 6主流币种实时扫描 |
| 🔬 策略回测 | 单币/批量回测、7-90天 |
| 🧠 自我进化 | 反思记录、进化规则、学习机制 |
| 🛡️ 风控数据 | 多空比、价格、K线、健康检查 |

## 系统架构

- **5 AI Agent 圆桌会议**: 技术分析师、巨鲸追踪者(OnchainOS)、宏观领航员(FRED)、逆向交易者(F&G)、量化玄学师(DeepSeek)
- **V4 18层评分引擎**: 趋势(4H主导)/V4价格结构(HH/HL/LL/LH)/动量(RSI+MACD)/成交量(+OBV)/布林带/恐贪指数(逆向)/SMC聪明钱(BOS/CHoCH/OB/FVG)/进化规则/资金费率/StochRSI+EMA交叉/大盘共振/订单簿深度/信号冲突矩阵/清算推算(4所)/VPVR(4所)/CoinAnk爆仓数据/OI市值比杠杆风险/多空比逆向指标(散户失衡>65%)
- **V4 五重交易门控**: G1冷却期(动态2-4周期)/G2熔断器(连亏3次暂停12周期)/G3方向去重(含position_manager持久化检查)/G4 ADX门控(<15禁止)/G5分数加速度
- **评分方向阈值**: score≥65=bullish / score≤35=bearish / 36-64=neutral (18层评分阈值)
- **LLM审核层(Claude)**: 17层评分后,Claude作为风控官做CONFIRM/REJECT/OVERRIDE决策(10s超时回退)
- **V4仓位管理**: 2级止盈(TP1平60%+移SL到保本, TP2平40%runner)+Trailing Stop+自适应持仓时间(趋势36h/震荡18h)
- **4交易所数据**: Binance + OKX + Bybit + HyperLiquid (K线/OI/资金费率/多空比)
- **Binance自动回退**: OKX API不可用时自动切换 Binance K线/FR/LS数据
- **Crisis→Trend回退**: S5危机策略无信号时自动回退到Trend+SMC分析，确保始终有可操作评分
- **链上数据**: OnchainOS v6 API (DEX交易/Index Price/链上价格)
- **宏观数据**: FRED API (联邦基金利率/CPI/GDP/M2/失业率/收益率曲线)
- **情绪数据**: Fear&Greed Index + 6551 OpenNews + Twitter + BlockBeats
- **AI玄学**: DeepSeek AI (八字/紫微/占星/塔罗 — 真实AI推理，非模拟)
- **自我进化系统**: 每笔交易(盈亏均)自动反思 → 结构化教训(ROOT_CAUSE/RED_FLAGS/LESSON/SUGGESTION/PATTERN) → 教训链传递(近5条) → 进化规则自动加载
- **余额同步**: 从 config/api_keys.json paper_trading.balance 读取初始余额，前后端7处统一，无硬编码
- **入场价**: 始终使用下单瞬间Binance API实时价格，非分析时旧价格
- **100% 真实数据**: 全系统零假数据，所有指标来源于真实API

---

## 🤖 一、AI 托管交易（核心功能）

> **⚠️ 重要: 后端已完整支持多币种同时交易！** 
> 每次启动使用 `symbols` 参数传入币种列表即可。
> 默认 BTC+ETH+SOL 三个币种同时分析+下单，无需分开启动。

### 启动托管（多币种+危机模式）

用户说 "帮我托管交易"、"开启AI托管"、"自动帮我炒币":

```bash
# ✅ 多币种同时交易 — 后端原生支持，一次启动即可
curl -s -X POST http://127.0.0.1:8000/api/managed/start \
  -H "Content-Type: application/json" \
  -d '{"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"],"mode":"paper","interval_minutes":5,"account_balance":10000,"risk_pct":2.0,"use_llm":false,"auto_threshold":55}'
```

**参数说明:**
- `symbols`: **多币种交易对列表 — 后端原生支持多币种同时分析和下单** (默认 ["BTCUSDT","ETHUSDT","SOLUSDT"])。后端 `_managed_loop` 每个周期会依次分析列表中的每个币种，每个币种独立评分、独立下单。
- `symbol`: 向后兼容字段，当 `symbols` 未提供时使用
- `mode`: "paper" 模拟盘 / "live" 实盘 (⚠️实盘需二次确认)
- `interval_minutes`: 分析间隔 (分钟)，建议 3-15
- `account_balance`: 模拟盘余额 (从config读取默认值)
- `risk_pct`: 每笔风险% (1-5)
- `use_llm`: true开启LLM辅助分析 (更准但更慢)
- `auto_threshold`: 自动执行阈值 (45-70，越低越容易执行)

**多币种工作原理:**
每个分析周期，后端会：
1. 检测危机模式 (FNG+新闻) — 一次检测，所有币种共享
2. 依次分析每个 symbol (BTC→ETH→SOL)
3. 每个币种独立评分、独立门控、独立下单
4. 每个币种有独立的冷却期/熔断器/方向去重

**危机/战争模式自动切换 (Crisis Mode S5):**
- 系统每周期自动检测 极端恐慌(FNG≤25) + 战时新闻飙升(BlockBeats) + 避险情绪(FRED收益率)
- 正常模式(FNG>25): Trend+SMC双向交易
- 危机模式(FNG≤25): **S5 危机策略** — 开启保命模式，死锁做空，限制最高2x杠杆，防插针3xATR宽止损，贪婪8xATR巨额止盈，捕捉瀑布行情
- **Crisis→Trend回退**: S5条件不满足(4H非下跌/非2连阴/EMA21上方)时，自动用Trend+SMC分析作为回退
- 战争回测验证: (FNG≤25强制激发的真实战时回测) — BTC 胜率50% 回撤仅2.5%，SOL 胜率75% 回撤0.8%

**数据获取回退:**
- K线: OKX → Binance (自动切换)
- FundingRate: OKX → Binance Futures (自动切换)
- 多空比: OKX → Binance Futures (自动切换)
- FNG: Alternative.me API (5分钟缓存)

回复:
```
🤖 AI托管已启动
━━━━━━━━━━━━━━━━
交易对: BTC/ETH/SOL (多币种同时)
模式: {mode} | 危机模式: 自动切换
分析频率: 每 {interval} 分钟
策略: 正常=Trend+SMC / 危机=S5(做空+情绪调仓)
V4门控: 冷却期 / 熔断器 / 方向去重 (每币种独立)
━━━━━━━━━━━━━━━━
```

### 查看托管状态

用户问 "托管怎么样了"、"状态"、"现在什么策略":

```bash
curl -s http://127.0.0.1:8000/api/managed/status
```

**返回字段:**
- `running`: 是否运行中
- `session.cycles`: 已完成周期数
- `last_analysis`: 最后分析结果 (symbol, mode, direction, score, entry, tp, sl, reasoning)
- `recent_events[]`: 近期事件列表，**包含每个币种**的分析结果:
  - `symbol`: 币种 (BTCUSDT/ETHUSDT/SOLUSDT)
  - `direction`: bearish/bullish/neutral
  - `score`: 评分 (0-100)
  - `mode`: crisis/normal
  - `event`: hold/trade_executed/gate_blocked
  - `reason`: 详细分析reasoning (含指标细节)
  - `entry/tp/sl/leverage`: 交易参数
- `config`: 当前配置

如果 running=false，回复: "⏹ AI托管未运行。发送'启动托管'开始。"

回复示例:
```
🤖 AI托管状态
━━━━━━━━━━━━━━━━
运行中: ✅ | 已完成 {cycles} 轮
模式: {crisis ? '🔴 危机模式' : '🟢 正常模式'}

📊 各币种分析:
 BTC: {direction} ({score}/100) {reasoning}
 ETH: {direction} ({score}/100) {reasoning}
 SOL: {direction} ({score}/100) {reasoning}
━━━━━━━━━━━━━━━━
```

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

### 快速分析 (<3秒, V4 18层评分)

```bash
# 纯技术
curl -s -X POST http://127.0.0.1:8000/api/quick-analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","use_llm":false,"account_balance":1000,"risk_pct":2.0}'

# 技术+LLM (~8秒)
curl -s -X POST http://127.0.0.1:8000/api/quick-analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","use_llm":true,"account_balance":1000,"risk_pct":2.0}'
```

返回: tech_score, direction, entry/tp/sl, leverage, rr_ratio, position_size, breakdown (含18层评分明细+LLM审核结果)

**V4 18层评分明细:**
1. 趋势(4H主导±20) | 2. V4价格结构(HH/HL/LL/LH ±5) | 3. 动量(RSI+MACD ±15)
4. 成交量(+OBV ±10) | 5. 布林带(±5) | 6. 恐贪指数(逆向 ±10)
7. SMC聪明钱(BOS/CHoCH/OB/FVG ±10) | 8. 进化规则(±5)
9. 资金费率(拥挤惩罚 ±5) | 10. StochRSI+EMA交叉(±10) | 11. 大盘共振(±8)
12. 订单簿深度(±5) | 13. 信号冲突矩阵(±8) | 14. 清算推算(4所 ±5)
15. VPVR量价分布(4所 ±5) | 16. CoinAnk爆仓数据(V5 ±8) | 17. OI/市值比杠杆风险(V5 ±5) | 18. 多空比逆向指标(散户极端>65%逆作 ±8)

**LLM审核层** (use_llm=true时激活):
- Claude收到全部17层数据后做CONFIRM/REJECT/OVERRIDE决策
- 10秒超时自动回退到纯数学结果

回复:
```
📊 {symbol} 快速分析 (V4 17层)
评分: {tech_score}/100 | 方向: {direction}
入场: ${entry} → 🎯 TP: ${tp} | 🛑 SL: ${sl}
杠杆: {lev}x | R:R {rr}:1
💰 仓位: {pos} (${value}) | 保证金: ${margin}
⚠️ 最大风险: ${risk} ({risk_pct}%)
🤖 LLM审核: {CONFIRM/REJECT/OVERRIDE}
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
  -d '{"symbol":"BTCUSDT","mode":"paper","account_balance":1000,"risk_pct":2.0}'
```

### 指定方向下单

```bash
# 做多
curl -s -X POST http://127.0.0.1:8000/api/trade/execute \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"buy","mode":"paper","account_balance":1000,"risk_pct":2.0}'

# 做空
curl -s -X POST http://127.0.0.1:8000/api/trade/execute \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"sell","mode":"paper","amount":0.05,"leverage":3}'
```

**注意**: 
- 入场价始终使用下单瞬间的Binance实时价格,非分析时价格
- `execute_trade` 同时写入 `paper_positions`(内存+JSON持久化) 和 `position_manager`(PriceMonitor TP/SL/Trailing自动监控)

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

# V2批量回测 (推荐)
curl -s -X POST "http://127.0.0.1:8000/api/backtest/v2/batch"
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

反思包含: trade_id, symbol, side, pnl, root_cause, red_flags, lesson, suggestion, pattern (追涨杀跌/逆势/震荡做单/TP太早/SL太紧等)

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

## 📡 数据源矩阵 (v6.1 — 100% 真实数据 + 自动回退)

| 数据 | 主源 | 回退 | 类型 |
|------|------|------|------|
| K线/价格 | Binance + OKX + Bybit + HyperLiquid | OKX→Binance自动切换 | 4交易所聚合 |
| 多空比 | Binance + OKX + Bybit | OKX→Binance Futures | 3交易所+6维分析 |
| 资金费率 | Binance + OKX + Bybit + HyperLiquid | OKX→Binance Futures | 4交易所 |
| 持仓量(OI) | Binance + OKX + Bybit + HyperLiquid | — | 4交易所 |
| 订单簿 | Binance | — | 实时深度 |
| DEX交易 | OnchainOS v6 API | — | 真实链上 |
| Index Price | OnchainOS v6 API | — | CEX+DEX+Oracle聚合 |
| 宏观经济 | FRED API (美联储) | — | 利率/CPI/GDP/M2 |
| 市场情绪 | 6551 OpenNews + OpenTwitter + Alternative.me F&G + BlockBeats | FNG 5min缓存 | 恐贪+新闻+社交 |
| 玄学分析 | DeepSeek AI LLM | — | 真实AI推理 |

## ⚠️ 安全规则

1. **默认模拟盘** — 除非用户明确说"实盘"
2. **实盘二次确认** — 说"实盘"时回复确认，得到"确定"才执行
3. **定时汇报** — 托管运行中时，每15分钟自动汇报一次状态
4. **风险提示** — 每次交易/汇报都要显示最大风险金额
5. **策略透明** — 告诉用户当前策略是什么、为什么做出这个决定
6. **R:R过滤** — 系统自动拒绝盈亏比<1.5的交易
7. **V4五重门控** — G1冷却/G2熔断/G3方向去重/G4 ADX<15禁止/G5加速度,缺一不可
8. **LLM审核** — Claude风控官做CONFIRM/REJECT/OVERRIDE,10s超时回退
9. **入场价实时** — 始终使用Binance下单瞬间实时价格,非分析时旧价格
10. **方向去重增强** — G3同时检查paper_positions和position_manager(持久化),服务器重启后不再重复开仓
11. **双重持仓注册** — execute_trade同时写入paper_positions和position_manager,确保PriceMonitor自动监控TP/SL/Trailing
12. **进化规则** — 系统从每笔交易(盈亏均)学习,自动调整评分权重
13. **多空比告警** — L/S > 2.8 或 < 0.8 触发告警
14. **余额统一** — 从config/api_keys.json读取,前后端7处同步,无硬编码
15. **零假数据** — 全系统100%真实API数据，无硬编码/模拟/伪造
16. **API回退** — OKX不可用时自动切Binance(K线/FR/LS), 确保数据始终有源
17. **策略回退** — S5危机策略neutral时自动切Trend+SMC, 确保每轮都有可操作分析
18. **多币种强制** — 托管启动始终包含BTC+ETH+SOL核心三币种
