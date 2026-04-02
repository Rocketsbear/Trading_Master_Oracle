/**
 * CapitalOverview — 资金概览 + 风控滑块
 * 从 TradingPanel.jsx 提取
 */
import { motion } from 'framer-motion'

const API_BASE = 'http://127.0.0.1:8000'

export default function CapitalOverview({
  balance, setBalance, initialBalanceRef, tradingMode,
  positions, totalPnl, riskPercent, setRiskPercent,
  autoExecThreshold, setAutoExecThreshold,
  managedRunning, managedStrategy,
  fetchPositions, fetchTradeHistory,
}) {
  const usedMargin = (positions || []).reduce((sum, p) => sum + ((p.entry_price || 0) * (p.amount || 0) / (p.leverage || 1)), 0)
  const freeMargin = (balance || 0) - usedMargin
  const marginUsePct = balance > 0 ? (usedMargin / balance * 100) : 0
  const ri = managedStrategy?.riskInfo || {}
  const posValue = ri.position_value || 0
  const posMargin = ri.margin_required || 0
  const maxRisk = ri.max_risk_amount || ((balance || 0) * (riskPercent || 2) / 100)

  return (
    <div className="bg-gradient-to-r from-surface-3 to-surface-2/80 rounded-xl border border-glass p-3 mb-3">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[10px] font-bold text-white flex items-center gap-2">
          💰 资金概览
          <span className="text-[8px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 font-mono">
            {tradingMode === 'paper' ? '模拟盘' : '🔴 实盘'}
          </span>
        </h4>
        {/* Editable balance */}
        <div className="flex items-center gap-1">
          <span className="text-[8px] text-gray-500">$</span>
          <input type="number" value={balance}
            onChange={(e) => { const v = parseFloat(e.target.value) || initialBalanceRef.current; setBalance(v); localStorage.setItem('paperBalance', String(v)) }}
            className="w-24 bg-transparent border-b border-glass text-right text-[11px] font-bold text-white font-mono focus:outline-none focus:border-purple-400" />
          <span className="text-[8px] text-gray-500">USDT</span>
          <button onClick={() => {
            fetch(`${API_BASE}/api/balance/sync`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ balance })
            })
              .then(res => res.json())
              .then(data => {
                if (data.success) {
                  fetchPositions(); fetchTradeHistory()
                  const btn = document.getElementById('balance-sync-btn')
                  if (btn) { btn.style.background = '#22c55e33'; setTimeout(() => btn.style.background = '', 1200) }
                }
              })
              .catch(e => console.error('[BalanceSync] Error:', e))
          }}
            id="balance-sync-btn"
            className="px-2 py-0.5 rounded-md text-[8px] font-bold bg-purple-500/15 text-purple-300 border border-purple-500/30 hover:bg-purple-500/30 transition-all ml-1"
            title="同步资金到后端，更新仓位计算">
            ✓ 确认
          </button>
        </div>
      </div>

      {/* Capital allocation progress bar */}
      <div className="mb-2">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[8px] text-gray-500">资金使用率</span>
          <span className={`text-[9px] font-bold font-mono ${marginUsePct > 80 ? 'text-red-400' : marginUsePct > 50 ? 'text-yellow-400' : 'text-brand-green'}`}>
            {marginUsePct.toFixed(1)}%
          </span>
        </div>
        <div className="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, marginUsePct)}%` }}
            className={`h-full rounded-full transition-all ${
              marginUsePct > 80 ? 'bg-red-400' : marginUsePct > 50 ? 'bg-yellow-400' : 'bg-brand-green'
            }`} />
        </div>
      </div>

      {/* Detail grid */}
      <div className="grid grid-cols-5 gap-2 mb-2">
        <div className="text-center">
          <p className="text-[7px] text-gray-600">总余额</p>
          <p className="text-[10px] font-bold text-white font-mono">${balance.toLocaleString()}</p>
        </div>
        <div className="text-center">
          <p className="text-[7px] text-gray-600">占用保证金</p>
          <p className="text-[10px] font-bold text-yellow-400 font-mono">${usedMargin.toFixed(0)}</p>
        </div>
        <div className="text-center">
          <p className="text-[7px] text-gray-600">可用保证金</p>
          <p className="text-[10px] font-bold text-brand-green font-mono">${freeMargin.toFixed(0)}</p>
        </div>
        <div className="text-center">
          <p className="text-[7px] text-gray-600">本单仓位</p>
          <p className="text-[10px] font-bold text-cyan-400 font-mono">{posValue > 0 ? `$${posValue}` : '—'}</p>
          {posMargin > 0 && <p className="text-[7px] text-gray-600">保证金 ${posMargin}</p>}
        </div>
        <div className="text-center">
          <p className="text-[7px] text-gray-600">单笔最大亏损</p>
          <p className="text-[10px] font-bold text-red-400 font-mono">${maxRisk.toFixed(0)}</p>
          <p className="text-[7px] text-gray-600">({riskPercent}%)</p>
        </div>
      </div>

      {/* User-adjustable risk controls */}
      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-glass/50">
        <div>
          <p className="text-[7px] text-gray-600 mb-1">📏 单笔风险%</p>
          <div className="flex gap-1">
            {[1, 2, 3, 5].map(pct => (
              <button key={pct} onClick={() => !managedRunning && setRiskPercent(pct)}
                disabled={managedRunning}
                className={`flex-1 py-1 rounded text-[9px] font-bold transition-all ${
                  riskPercent === pct ? 'bg-red-500/15 text-red-400 border border-red-500/20'
                    : 'bg-surface-2 text-gray-600 border border-glass'
                } ${managedRunning ? 'opacity-50' : ''}`}>
                {pct}%
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[7px] text-gray-600 mb-1">🎯 自动执行阈值</p>
          <div className="flex items-center gap-1">
            <input type="range" min="45" max="70" value={autoExecThreshold}
              onChange={(e) => setAutoExecThreshold(parseInt(e.target.value))}
              className="flex-1 h-1 accent-purple-400" />
            <span className="text-[9px] font-bold text-purple-400 font-mono w-8 text-center">{autoExecThreshold}</span>
          </div>
          <p className="text-[7px] text-gray-500">≥{autoExecThreshold}做多 / ≤{100-autoExecThreshold}做空</p>
        </div>
        <div>
          <p className="text-[7px] text-gray-600 mb-1">📋 活跃仓位</p>
          <p className="text-[14px] font-bold text-white font-mono text-center">{positions.length}</p>
          <p className="text-[7px] text-gray-500 text-center">
            {positions.length > 0 ? `PnL: ${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}` : '无持仓'}
          </p>
        </div>
      </div>
    </div>
  )
}
