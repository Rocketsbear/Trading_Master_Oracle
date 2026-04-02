/**
 * HybridAIDashboard — System 1 (XGBoost) + System 2 (Agent Council) 仪表盘
 * 从 TradingPanel.jsx 提取
 */
export default function HybridAIDashboard({ 
  managedStrategy, managedSymbols, crisisMode, managedRunning,
  nextTradeCountdown, formatCountdown, executeRangeStrategy,
  scoreTrend = [],
}) {
  return (
    <div className="bg-surface-3 rounded-xl border border-glass p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-[11px] font-bold text-white flex items-center gap-2">
          🧠 Hybrid AI 控制中心
        </h4>
        {managedRunning && (
          <div className="flex items-center gap-3">
            {/* Score Trend Mini */}
            {scoreTrend.length > 0 && (
              <div className="flex items-end gap-px h-4">
                {scoreTrend.map((s, i) => (
                  <div key={i} className="w-1.5 rounded-sm" style={{
                    height: `${Math.max(15, s)}%`,
                    backgroundColor: s >= 60 ? '#00e887' : s <= 40 ? '#ff4757' : '#ffd93d',
                    opacity: 0.7,
                  }} />
                ))}
              </div>
            )}
            <div className="text-right">
              <span className="text-[8px] text-gray-600 block">⚡引擎循环</span>
              <span className="text-xs font-bold text-purple-400 font-mono">{formatCountdown(nextTradeCountdown)}</span>
            </div>
          </div>
        )}
      </div>

      {managedStrategy ? (
        <>
          <div className="grid grid-cols-2 gap-4">
            {/* LEFT: System 1 (XGB Engine) */}
            <div className="glass-card-accent p-3 rounded-lg border border-purple-500/10 h-full flex flex-col justify-between">
              <div>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-[10px] text-purple-400 font-bold uppercase tracking-wider flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-purple-500 rounded-full animate-pulse" />
                    System 1 · 术
                  </span>
                  <span className="text-[8px] px-1 py-0.5 rounded bg-purple-500/15 text-purple-300">XGBoost DTree</span>
                </div>
                <p className="text-[8px] text-gray-500 mb-3 border-b border-glass pb-1">负责高频量价特征扫描与入场点位精确打击</p>
                
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <div className="bg-surface-1/30 rounded p-1.5 text-center">
                    <span className="text-[8px] text-gray-600 block">战术方向</span>
                    <span className={`text-sm font-bold mt-0.5 block ${
                      managedStrategy.direction === 'bullish' ? 'neon-text-green' : managedStrategy.direction === 'bearish' ? 'neon-text-red' : 'text-gray-400'
                    }`}>
                      {managedStrategy.direction === 'bullish' ? '📈 做多' : managedStrategy.direction === 'bearish' ? '📉 做空' : '➡️ 观望'}
                    </span>
                  </div>
                  <div className="bg-surface-1/30 rounded p-1.5 text-center">
                    <span className="text-[8px] text-gray-600 block">统计胜率 (Prob)</span>
                    <span className={`text-sm font-bold mt-0.5 block font-mono ${managedStrategy.score >= 60 ? 'text-brand-green' : managedStrategy.score <= 40 ? 'text-red-400' : 'text-yellow-400'}`}>
                      {(managedStrategy.riskInfo?.win_probability || managedStrategy.score || 50).toFixed(1)}%
                    </span>
                  </div>
                  <div className="bg-surface-1/30 rounded p-1.5 text-center">
                    <span className="text-[8px] text-gray-600 block">盈亏比 (R:R)</span>
                    <span className="text-[10px] font-bold mt-0.5 block text-white font-mono">{managedStrategy.riskInfo?.rr_ratio?.toFixed(1) || '—'}:1</span>
                  </div>
                  <div className="bg-surface-1/30 rounded p-1.5 text-center">
                    <span className="text-[8px] text-gray-600 block">基础杠杆</span>
                    <span className="text-[10px] font-bold mt-0.5 block text-yellow-400 font-mono">{managedStrategy.leverage || '—'}x</span>
                  </div>
                </div>
              </div>

              {/* XGB Action Plan */}
              {managedStrategy.direction !== 'neutral' && (
                <div className="border border-glass rounded p-2 bg-surface-2/20">
                  <p className="text-[8px] text-gray-500 mb-1">执行计划</p>
                  <div className="flex justify-between text-[9px] font-mono mb-0.5">
                    <span className="text-gray-400">Entry:</span>
                    <span className="text-white">${managedStrategy.entry?.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between text-[9px] font-mono mb-0.5">
                    <span className="text-gray-400">TP Target:</span>
                    <span className="text-brand-green">${managedStrategy.tp?.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between text-[9px] font-mono">
                    <span className="text-gray-400">Hard SL:</span>
                    <span className="text-red-400">${managedStrategy.sl?.toLocaleString()}</span>
                  </div>
                </div>
              )}
            </div>

            {/* RIGHT: System 2 (Agent Council) */}
            <div className="bg-surface-2/30 p-3 rounded-lg border border-brand-green/10 h-full flex flex-col justify-between">
              <div>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-[10px] text-brand-green font-bold uppercase tracking-wider flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-brand-green rounded-full" />
                    System 2 · 道
                  </span>
                  <span className="text-[8px] px-1 py-0.5 rounded bg-brand-green/15 text-brand-green">Multi-Agent LLM</span>
                </div>
                <p className="text-[8px] text-gray-500 mb-3 border-b border-glass pb-1">负责宏观风控、动态仓位压限与叙事猎物筛选</p>

                <div className="grid grid-cols-1 gap-2">
                  <div className={`p-2 rounded flex justify-between items-center border ${crisisMode ? 'bg-red-500/10 border-red-500/20' : 'bg-surface-1/30 border-glass'}`}>
                    <div>
                      <span className="text-[8px] text-gray-600 block">Macro Veto (宏观否决)</span>
                      <span className={`text-[10px] font-bold ${crisisMode ? 'text-red-400' : 'text-gray-400'}`}>
                        {crisisMode ? '🔴 封锁警报：S5双向策略' : '🟢 沉默 (未触发)'}
                      </span>
                    </div>
                  </div>
                  <div className="p-2 rounded flex justify-between items-center border bg-surface-1/30 border-glass">
                    <div>
                      <span className="text-[8px] text-gray-600 block">动态仓位池 (Risk Ceiling)</span>
                      <span className="text-[10px] font-bold text-cyan-400 font-mono">
                        Limit: {managedStrategy.riskInfo?.max_risk_amount ? `$${managedStrategy.riskInfo.max_risk_amount.toFixed(0)}` : '—'}
                      </span>
                    </div>
                    <div className="text-right">
                      <span className="text-[8px] text-gray-600 block">当前分配</span>
                      <span className="text-[10px] font-bold text-white font-mono text-right">{managedStrategy.riskInfo?.position_size || '—'}</span>
                    </div>
                  </div>
                  <div className="p-2 rounded border bg-surface-1/30 border-glass">
                    <span className="text-[8px] text-gray-600 block mb-1">猎池生态 (Watchlist)</span>
                    <div className="flex flex-wrap gap-1">
                      {managedSymbols.slice(0, 4).map(s => (
                        <span key={s} className="text-[8px] bg-brand-green/10 text-brand-green px-1 rounded">{s.replace('USDT','')}</span>
                      ))}
                      {managedSymbols.length > 4 && <span className="text-[8px] text-gray-500">+{managedSymbols.length - 4}</span>}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Score Breakdown */}
          {managedStrategy.scoreBreakdown && managedStrategy.scoreBreakdown.length > 0 && (
            <div className="mt-2 space-y-1.5">
              {/* LLM Review card */}
              {managedStrategy.scoreBreakdown.filter(item => item.includes('🤖')).map((item, i) => {
                const isConfirm = item.includes('✅') || item.includes('CONFIRM')
                const isReject = item.includes('REJECT')
                const isOverride = item.includes('OVERRIDE')
                return (
                  <div key={`llm-${i}`} className={`rounded-lg px-3 py-2 text-[9px] font-bold border ${
                    isConfirm ? 'bg-brand-green/5 border-brand-green/20 text-brand-green'
                    : isReject ? 'bg-red-500/5 border-red-500/20 text-red-400'
                    : isOverride ? 'bg-amber-500/5 border-amber-500/20 text-amber-400'
                    : 'bg-purple-500/5 border-purple-500/20 text-purple-400'
                  }`}>
                    {isConfirm ? '✅' : isReject ? '🚫' : '⚡'} {item.replace('🤖LLM审核: ', '').replace('🤖', '')}
                  </div>
                )
              })}
              {/* Regular breakdown badges */}
              <div className="flex flex-wrap gap-1">
                {managedStrategy.scoreBreakdown.filter(item => !item.includes('🤖')).map((item, i) => {
                  const isV4 = item.includes('V4')
                  const isPos = item.includes('+') && !item.includes('-')
                  const isNeg = item.includes('-') && !item.includes('+')
                  return (
                    <span key={i} className={`text-[8px] px-1.5 py-0.5 rounded-full font-mono ${
                      isV4 ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20 font-bold'
                      : isPos ? 'bg-brand-green/10 text-brand-green border border-brand-green/20'
                      : isNeg ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                      : 'bg-gray-700/30 text-gray-400 border border-gray-600/20'
                    }`}>
                      {item}
                    </span>
                  )
                })}
              </div>
            </div>
          )}

          {/* Range Strategy Card */}
          {managedStrategy.direction === 'neutral' && managedStrategy.rangeStrategy && (
            <div className="bg-amber-500/5 border border-amber-500/15 rounded-xl p-3 space-y-2.5 mt-2">
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-bold text-amber-400">📐 震荡区间策略</p>
                <span className="text-[9px] text-amber-400/60 font-mono">
                  ${managedStrategy.rangeStrategy.range_low?.toLocaleString()} ~ ${managedStrategy.rangeStrategy.range_high?.toLocaleString()}
                </span>
              </div>
              
              {/* Range visual bar */}
              <div className="relative h-6 bg-gray-800 rounded-full overflow-hidden">
                <div className="absolute inset-y-0 bg-gradient-to-r from-brand-green/20 via-amber-400/10 to-red-400/20 rounded-full" style={{ left: '5%', right: '5%' }} />
                <div className="absolute top-0 bottom-0 w-0.5 bg-gray-500" style={{ 
                  left: `${Math.min(95, Math.max(5, ((managedStrategy.rangeStrategy.range_mid - managedStrategy.rangeStrategy.range_low) / (managedStrategy.rangeStrategy.range_high - managedStrategy.rangeStrategy.range_low)) * 90 + 5))}%` 
                }} />
                <div className="absolute top-1/2 -translate-y-1/2 w-2 h-2 bg-white rounded-full shadow-lg" style={{ 
                  left: `${Math.min(95, Math.max(5, ((managedStrategy.entry - managedStrategy.rangeStrategy.range_low) / (managedStrategy.rangeStrategy.range_high - managedStrategy.rangeStrategy.range_low)) * 90 + 5))}%` 
                }} />
                <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[7px] text-brand-green font-bold">做多</span>
                <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[7px] text-red-400 font-bold">做空</span>
              </div>
              
              {/* Long / Short plans */}
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-brand-green/5 border border-brand-green/15 rounded-lg p-2">
                  <p className="text-[9px] font-bold text-brand-green mb-1">📈 做多方案</p>
                  <p className="text-[8px] text-gray-400">入场: <span className="text-white font-mono">${managedStrategy.rangeStrategy.long?.entry?.toLocaleString()}</span></p>
                  <p className="text-[8px] text-gray-400">止盈: <span className="text-brand-green font-mono">${managedStrategy.rangeStrategy.long?.tp?.toLocaleString()}</span></p>
                  <p className="text-[8px] text-gray-400">止损: <span className="text-red-400 font-mono">${managedStrategy.rangeStrategy.long?.sl?.toLocaleString()}</span></p>
                  <button onClick={() => executeRangeStrategy('buy')}
                    className="w-full mt-1.5 py-1.5 rounded-md bg-brand-green/15 text-brand-green text-[9px] font-bold border border-brand-green/20 hover:bg-brand-green/25 transition-all">
                    ✅ 执行做多
                  </button>
                </div>
                <div className="bg-red-500/5 border border-red-500/15 rounded-lg p-2">
                  <p className="text-[9px] font-bold text-red-400 mb-1">📉 做空方案</p>
                  <p className="text-[8px] text-gray-400">入场: <span className="text-white font-mono">${managedStrategy.rangeStrategy.short?.entry?.toLocaleString()}</span></p>
                  <p className="text-[8px] text-gray-400">止盈: <span className="text-brand-green font-mono">${managedStrategy.rangeStrategy.short?.tp?.toLocaleString()}</span></p>
                  <p className="text-[8px] text-gray-400">止损: <span className="text-red-400 font-mono">${managedStrategy.rangeStrategy.short?.sl?.toLocaleString()}</span></p>
                  <button onClick={() => executeRangeStrategy('sell')}
                    className="w-full mt-1.5 py-1.5 rounded-md bg-red-500/15 text-red-400 text-[9px] font-bold border border-red-500/20 hover:bg-red-500/25 transition-all">
                    ✅ 执行做空
                  </button>
                </div>
              </div>
              
              <p className="text-[8px] text-amber-400/50 text-center">
                杠杆 {managedStrategy.rangeStrategy.recommended_leverage}x | 高抛低吸 — 不确定可继续观望
              </p>
            </div>
          )}

          <p className="text-[9px] text-gray-500 mt-2">最后更新: {managedStrategy.updatedAt}</p>
        </>
      ) : (
        <div className="text-center py-8 text-gray-700 text-xs border border-dashed border-glass rounded-lg mt-2">
          {managedRunning ? '⏳ 等待 System 1 & System 2 同步联合推断结果...' : '启辉 AI 神舟号，点火发射！'}
        </div>
      )}
    </div>
  )
}
