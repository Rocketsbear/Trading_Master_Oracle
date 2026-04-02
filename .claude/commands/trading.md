# Trading Oracle 交易操作指令

当用户要求进行交易相关操作时，使用以下 API 调用模式。后端地址: `http://127.0.0.1:8000`

## AI 托管交易

### 启动托管
```bash
curl -s -X POST http://127.0.0.1:8000/api/managed/start \
  -H "Content-Type: application/json" \
  -d '{"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"],"mode":"paper","interval_minutes":5,"account_balance":10000,"risk_pct":2.0,"use_llm":false,"auto_threshold":55}'
```
参数:
- `symbols`: 多币种列表, 后端原生支持同时交易
- `mode`: "paper" 模拟盘 / "live" 实盘 (需二次确认)
- `interval_minutes`: 分析频率 (建议 3-15)
- `risk_pct`: 单笔风险% (1-5)
- `use_llm`: true 启用 LLM 辅助
- `auto_threshold`: 自动执行阈值 (45-70)

### 查看托管状态
```bash
curl -s http://127.0.0.1:8000/api/managed/status
```

### 停止托管
```bash
curl -s -X POST http://127.0.0.1:8000/api/managed/stop
```

### 交易报告
```bash
curl -s http://127.0.0.1:8000/api/managed/report
```

## 手动分析

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

### 深度分析 (Agent圆桌, 60-120秒)
```bash
curl -s -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","interval":"1h"}'
```

## 手动交易

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
  -d '{"symbol":"BTCUSDT","side":"sell","mode":"paper","account_balance":1000,"risk_pct":2.0}'
```

### 查看持仓
```bash
curl -s http://127.0.0.1:8000/api/positions
```

### 平仓
```bash
# 平指定币种
curl -s -X POST http://127.0.0.1:8000/api/positions/close \
  -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT"}'

# 部分平仓 (50%)
curl -s -X POST http://127.0.0.1:8000/api/positions/close \
  -H "Content-Type: application/json" -d '{"symbol":"BTCUSDT","close_pct":50}'
```

## 多币种扫描
```bash
curl -s "http://127.0.0.1:8000/api/multi-scan?symbols=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT"
```

## 策略回测
```bash
# 单币回测
curl -s -X POST "http://127.0.0.1:8000/api/backtest?symbol=BTCUSDT&days=30&score_threshold=65&leverage=3&risk_pct=2.0"

# V2批量回测
curl -s -X POST "http://127.0.0.1:8000/api/backtest/v2/batch"
```

## 自我进化系统
```bash
# 反思记录
curl -s "http://127.0.0.1:8000/api/reflections?limit=10"

# 进化规则
curl -s http://127.0.0.1:8000/api/reflections/rules

# 进化摘要
curl -s http://127.0.0.1:8000/api/reflections/summary
```

## 风控与市场数据
```bash
# 风控状态
curl -s http://127.0.0.1:8000/api/risk-status

# 多空比 (3交易所)
curl -s "http://127.0.0.1:8000/api/long-short?symbol=BTCUSDT"

# 实时价格
curl -s "http://127.0.0.1:8000/api/price?symbol=BTCUSDT"

# K线数据
curl -s "http://127.0.0.1:8000/api/klines?symbol=BTCUSDT&interval=1h&limit=24"

# 系统健康
curl -s http://127.0.0.1:8000/api/health
```

## 用户意图映射

| 用户说 | 调用 |
|--------|------|
| 帮我托管 / 开启AI / 自动交易 | POST managed/start |
| 托管状态 / 怎么样了 | GET managed/status |
| 停止托管 / 关掉 | POST managed/stop |
| 报告 / 业绩 / 统计 | GET managed/report |
| BTC怎么样 / 分析一下 | POST quick-analyze (use_llm=false) |
| 详细分析 / 深入分析 | POST quick-analyze (use_llm=true) |
| 深度分析 / Agent圆桌 | POST analyze |
| 帮我买 / 做多 | POST trade/auto (side=buy) |
| 做空 / 空BTC | POST trade/execute (side=sell) |
| 持仓 / 仓位 | GET positions |
| 平仓 / 清仓 | POST positions/close |
| 扫描市场 / 哪个币好 | GET multi-scan |
| 回测 / backtest | POST backtest |
| 反思 / 进化 | GET reflections |

## 安全规则
1. 默认模拟盘, 实盘需用户明确说"实盘"并二次确认
2. 每次交易显示最大风险金额
3. 入场价始终使用 Binance 下单瞬间实时价格
4. 系统自动拒绝盈亏比 < 1.5 的交易
