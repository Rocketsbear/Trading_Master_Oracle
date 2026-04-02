import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { useTradingStore } from '../store/tradingStore'

const API_BASE = 'http://127.0.0.1:8000'

function RatioBar({ label, longPct, shortPct, ratio }) {
  const longW = Math.min(Math.max(longPct, 5), 95)
  const isExtreme = ratio < 0.8 || ratio > 2.8
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-gray-400 uppercase tracking-wider">{label}</span>
        <span className={`font-mono font-bold ${isExtreme ? (ratio < 0.8 ? 'text-green-400' : 'text-red-400') : 'text-gray-300'}`}>
          {ratio?.toFixed(2)}
        </span>
      </div>
      <div className="flex h-2.5 rounded-full overflow-hidden bg-surface-3">
        <motion.div
          className="rounded-l-full"
          style={{ width: `${longW}%`, background: 'linear-gradient(90deg, #00e887, #00b868)' }}
          initial={{ width: 0 }}
          animate={{ width: `${longW}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
        <motion.div
          className="rounded-r-full"
          style={{ width: `${100 - longW}%`, background: 'linear-gradient(90deg, #e84060, #ff6080)' }}
          initial={{ width: 0 }}
          animate={{ width: `${100 - longW}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
      </div>
      <div className="flex justify-between text-[9px]">
        <span className="text-green-400/70">多 {longPct?.toFixed(1)}%</span>
        <span className="text-red-400/70">空 {shortPct?.toFixed(1)}%</span>
      </div>
    </div>
  )
}

export default function LongShortPanel() {
  const { symbol } = useTradingStore()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/long-short?symbol=${symbol}`)
      const json = await res.json()
      if (json.success) setData(json.data)
    } catch (e) {
      console.error('Failed to fetch L/S data:', e)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60000) // 60s refresh
    return () => clearInterval(interval)
  }, [fetchData])

  if (loading && !data) {
    return (
      <div className="glass-card p-3 animate-pulse">
        <div className="h-4 bg-surface-3 rounded w-1/3 mb-3" />
        <div className="space-y-3">
          <div className="h-6 bg-surface-3 rounded" />
          <div className="h-6 bg-surface-3 rounded" />
        </div>
      </div>
    )
  }

  if (!data) return null

  const ls = data.long_short_ratios || {}
  const oi = data.open_interests || {}
  const fr = data.funding_rates || {}
  const oiTrend = data.oi_trend
  const oiChange = data.oi_change_pct
  const avgFr = data.avg_funding_rate

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card p-4"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold text-gray-300 tracking-wide uppercase flex items-center gap-1.5">
          📊 多空比 · OI · 费率
          <span className="text-[9px] text-gray-500 font-normal">实时</span>
        </h3>
        <motion.button
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
          onClick={fetchData}
          className="text-gray-500 hover:text-brand-green text-xs transition-colors"
          title="刷新"
        >🔄</motion.button>
      </div>

      {/* Long/Short Ratio Bars */}
      <div className="space-y-2.5 mb-3">
        {Object.entries(ls).map(([ex, v]) => (
          <RatioBar
            key={ex}
            label={ex}
            longPct={v.long_pct}
            shortPct={v.short_pct}
            ratio={v.ratio}
          />
        ))}
      </div>

      {/* Threshold Signal */}
      {data.avg_long_pct && (() => {
        const ratios = Object.values(ls).map(v => v.ratio)
        const avg = ratios.reduce((a, b) => a + b, 0) / ratios.length
        if (avg < 0.8) return <div className="text-[10px] text-green-400 bg-green-500/10 border border-green-500/20 rounded px-2 py-1 mb-2 text-center">🟢 多空比 {avg.toFixed(2)} &lt; 0.8 — 做多信号增强</div>
        if (avg > 2.8) return <div className="text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1 mb-2 text-center">🔴 多空比 {avg.toFixed(2)} &gt; 2.8 — 做空信号增强</div>
        return null
      })()}

      {/* OI + Funding Grid */}
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        {/* OI */}
        <div className="bg-surface-3/50 rounded-lg p-2">
          <div className="text-gray-500 uppercase tracking-wider mb-1">持仓量 OI</div>
          {Object.entries(oi).map(([ex, v]) => (
            <div key={ex} className="flex justify-between text-gray-300">
              <span className="text-gray-500">{ex}</span>
              <span className="font-mono">{Number(v).toLocaleString()}</span>
            </div>
          ))}
          {oiChange != null && (
            <div className={`mt-1 font-bold ${oiTrend === 'increasing' ? 'text-green-400' : oiTrend === 'decreasing' ? 'text-red-400' : 'text-gray-400'}`}>
              Δ {oiChange > 0 ? '+' : ''}{oiChange}%
            </div>
          )}
        </div>

        {/* Funding */}
        <div className="bg-surface-3/50 rounded-lg p-2">
          <div className="text-gray-500 uppercase tracking-wider mb-1">资金费率</div>
          {Object.entries(fr).map(([ex, v]) => (
            <div key={ex} className="flex justify-between text-gray-300">
              <span className="text-gray-500">{ex}</span>
              <span className={`font-mono ${v > 0.0005 ? 'text-red-400' : v < -0.0005 ? 'text-green-400' : ''}`}>
                {(v * 100).toFixed(4)}%
              </span>
            </div>
          ))}
          {avgFr != null && (
            <div className={`mt-1 font-bold ${avgFr > 0.0005 ? 'text-red-400' : avgFr < -0.0005 ? 'text-green-400' : 'text-gray-400'}`}>
              Avg: {(avgFr * 100).toFixed(4)}%
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}
