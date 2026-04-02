# Trading Oracle 风控策略详解

当用户询问风控、仓位管理、止损止盈策略时，参考以下内容。

## 1. 半凯利公式动态仓位 (Half-Kelly Criterion)

**文件**: `backend/risk/risk_manager.py` → `calculate_kelly_position_size()`

公式: `K% = W - [(1 - W) / R]`
- W = 胜率 (来自 XGBoost 模型 ml_predictor.py 的实时预测, 或历史交易统计)
- R = 盈亏比 (TP距离 / SL距离)
- 实际使用 Half-Kelly (`kelly_multiplier = 0.5`) 降低破产风险
- Kelly ≤ 0 时强制降为 0.2% 微仓试探

**双重上限拦截**:
- 用户设定的 `max_risk_per_trade` (默认 2%)
- System 2 动态防线 `dynamic_max_kelly_fraction` (宏观风险时降低)
- 取两者最小值

**历史自适应** (`kelly_position_size()`):
- 需要 ≥ 20 笔已平仓交易
- 自动统计真实胜率和平均盈亏比
- 用真实数据替代模型预测

## 2. ATR 动态止损止盈

**文件**: `backend/risk/risk_manager.py` → `calculate_dynamic_sl_tp()`

- SL = 入场价 ± (ATR × 2.0)  → 噪音之外
- TP = 入场价 ± (ATR × 3.0~4.0)  → 信心度调优
  - `tp_mult = 3.0 + confidence × 1.0` (confidence = abs(score - 50) / 50)
  - 强信号 → TP 更远 (让利润奔跑)
- 最小止损保护: 至少 0.5% 距离

## 3. 三段移动止损 (Trailing Stop)

**文件**: `backend/risk/risk_manager.py` → `calculate_trailing_stop()`

| 阶段 | 触发条件 | 止损移至 |
|------|----------|----------|
| Initial | 开仓后 | 入场 - 1.2×ATR |
| Breakeven | 浮盈达 1.0×ATR (TP1) | 入场价 (零风险) |
| Trailing | 浮盈达 1.5×ATR (TP2) | 当前价 - 0.8×ATR |

## 4. 分批止盈 (Multi-TP)

**文件**: `backend/risk/risk_manager.py` → `calculate_multi_tp()`

| 级别 | 目标 | 平仓比例 |
|------|------|----------|
| TP1 | 1.0× ATR | 50% |
| TP2 | 1.5× ATR | 30% |
| TP3 | 2.5× ATR | 20% (Runner) |

强信号(score>70)时目标距离放大 (distance_mult 最高 1.3×)

## 5. 连败阶梯降仓

**参数**:
- `consecutive_loss_threshold = 3` (连败触发阈值)
- `consecutive_loss_reduction = 0.5` (降仓比例)

**逻辑**: 连续亏损 ≥ 3 次 → 后续所有开单的风险百分比乘以 0.5 → 盈利一次后归零重置

## 6. 波动率反向杠杆

**文件**: `backend/risk/risk_manager.py` → `calculate_leverage()`

| ATR / Price | 波动等级 | 杠杆折扣 |
|-------------|----------|----------|
| > 3.0% | 高波动 | × 0.5 |
| > 2.0% | 中波动 | × 0.7 |
| > 1.0% | 正常 | × 0.85 |
| ≤ 1.0% | 低波动 | × 1.0 |

基础杠杆: score≥80 → 5x, ≥70 → 3x, ≥60 → 2x, else 1x
最终杠杆 = base × vol_factor (硬上限 5x)

## 7. 每日熔断 (Circuit Breaker)

- 每日亏损达 `account_balance × 5%` → 全面停止交易
- 第二天自动重置

## 8. 信号强度动态仓位

**文件**: `backend/risk/risk_manager.py` → `calculate_signal_scaled_position()`

| 信号强度 (abs(score-50)) | 余额使用比例 | 档位 |
|--------------------------|-------------|------|
| 0-15 | 5% | 🟡 试探 |
| 15-20 | 5-10% | 🟡 弱 |
| 20-30 | 10-20% | 🟠 中等 |
| 30-40 | 20-35% | 🔴 强 |
| 40-50 | 35-50% | 🔥 极强 |

安全帽: 单笔风险不超过 `max_risk_per_trade × 3`, 保证金不超过余额 30%

## 9. System 2 宏观一票否决权

`set_macro_regime(is_high_risk=True)` → 禁止所有自动开仓
`set_dynamic_risk_limit(max_risk)` → 动态调整 Kelly 上限

## 10. V4 五重交易门控

| 门控 | 条件 | 作用 |
|------|------|------|
| G1 冷却期 | 动态 2-4 周期 | 防止频繁交易 |
| G2 熔断器 | 连亏 3 次暂停 12 周期 | 连败保护 |
| G3 方向去重 | 检查持仓+position_manager | 防重复开仓 |
| G4 ADX 门控 | ADX < 15 禁止 | 无趋势不开仓 |
| G5 分数加速度 | 评分变化率 | 防假突破 |
