import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTradingStore } from '../store/tradingStore'

const API_BASE = 'http://127.0.0.1:8000'

const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT', 'DOGEUSDT']

const SYMBOL_LABELS = {
  BTCUSDT: 'BTC', ETHUSDT: 'ETH', SOLUSDT: 'SOL', ADAUSDT: 'ADA',
  XRPUSDT: 'XRP', DOGEUSDT: 'DOGE', BNBUSDT: 'BNB', AVAXUSDT: 'AVAX',
  DOTUSDT: 'DOT', MATICUSDT: 'MATIC', LINKUSDT: 'LINK', UNIUSDT: 'UNI',
  ATOMUSDT: 'ATOM', LTCUSDT: 'LTC', NEARUSDT: 'NEAR',
}

export default function MultiCoinCompare() {
  const { setSymbol, setMarketType } = useTradingStore()
  const [results, setResults] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [scanMode, setScanMode] = useState('core') // 'core' | 'hot'

  const runScan = useCallback(async () => {
    setLoading(true)
    try {
      const symbolsToScan = scanMode === 'hot' ? ['HOT'] : DEFAULT_SYMBOLS
      const res = await fetch(`${API_BASE}/api/multi-analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: symbolsToScan, use_llm: false }),
      })
      const data = await res.json()
      if (data.success) {
        setResults(data.results)
        setSummary(data.summary)
        setExpanded(true)
      }
    } catch (e) { /* silent */ }
    setLoading(false)
  }, [scanMode])

  const switchToCoin = (sym) => {
    setSymbol(sym)
    setMarketType('futures')
  }

  const dirIcon = (d) => d === 'bullish' ? '🟢' : d === 'bearish' ? '🔴' : '⚪'
  const dirLabel = (d) => d === 'bullish' ? '做多' : d === 'bearish' ? '做空' : '中性'

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card overflow-hidden"
    >
      {/* Header */}
      <div className="px-5 py-3 border-b border-glass flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse-glow" />
          <h3 className="text-sm font-bold uppercase tracking-wider text-white">
            🌐 Multi-Coin Scanner
          </h3>
          <div className="flex bg-surface-3 rounded-lg p-0.5 border border-glass ml-2">
            <button onClick={() => setScanMode('core')}
              className={`px-3 py-1 text-[10px] font-bold rounded-md transition-all ${scanMode === 'core' ? 'bg-cyan-500/15 text-cyan-400' : 'text-gray-600'}`}>
              ⭐ 核心6币
            </button>
            <button onClick={() => setScanMode('hot')}
              className={`px-3 py-1 text-[10px] font-bold rounded-md transition-all ${scanMode === 'hot' ? 'bg-brand-orange/15 text-brand-orange' : 'text-gray-600'}`}>
              🔥 动态Top10热点
            </button>
          </div>
          {summary && (
            <span className="text-[9px] bg-cyan-500/10 text-cyan-400 px-1.5 py-0.5 rounded font-bold ml-2">
              {summary.tradeable}/{summary.total_symbols} 有信号
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {summary?.strongest && (
            <span className="text-[10px] text-brand-green font-bold">
              最强: {SYMBOL_LABELS[summary.strongest] || summary.strongest} ({summary.strongest_score}/100)
            </span>
          )}
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={runScan}
            disabled={loading}
            className={`px-4 py-1.5 rounded-lg text-[11px] font-bold transition-all ${
              loading
                ? 'bg-surface-3 text-gray-500 cursor-not-allowed'
                : 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/25'
            }`}
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                  className="block w-3 h-3 border-2 border-gray-600 border-t-cyan-400 rounded-full" />
                扫描中...
              </span>
            ) : '⚡ 一键扫描'}
          </motion.button>
          {results.length > 0 && (
            <button onClick={() => setExpanded(!expanded)}
              className="text-gray-500 hover:text-gray-300 text-xs transition-colors">
              {expanded ? '▲ 收起' : '▼ 展开'}
            </button>
          )}
        </div>
      </div>

      {/* Results Table */}
      <AnimatePresence>
        {expanded && results.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-gray-500 border-b border-glass">
                    <th className="px-4 py-2 text-left font-bold">币种</th>
                    <th className="px-3 py-2 text-center font-bold">方向</th>
                    <th className="px-3 py-2 text-center font-bold">评分</th>
                    <th className="px-3 py-2 text-right font-bold">价格</th>
                    <th className="px-3 py-2 text-center font-bold">RSI</th>
                    <th className="px-3 py-2 text-center font-bold">ADX</th>
                    <th className="px-3 py-2 text-center font-bold">市场</th>
                    <th className="px-3 py-2 text-center font-bold">R:R</th>
                    <th className="px-3 py-2 text-center font-bold">风险份额</th>
                    <th className="px-3 py-2 text-center font-bold">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <motion.tr
                      key={r.symbol}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="border-b border-glass/50 hover:bg-white/[0.02] cursor-pointer transition-colors"
                      onClick={() => switchToCoin(r.symbol)}
                    >
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-white text-xs">{SYMBOL_LABELS[r.symbol] || r.symbol}</span>
                          {i === 0 && r.direction !== 'neutral' && (
                            <span className="text-[8px] bg-brand-green/15 text-brand-green px-1 py-0.5 rounded">TOP</span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <span className={`font-bold ${
                          r.direction === 'bullish' ? 'text-brand-green' :
                          r.direction === 'bearish' ? 'text-red-400' : 'text-gray-500'
                        }`}>
                          {dirIcon(r.direction)} {dirLabel(r.direction)}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <span className={`font-bold font-mono ${
                          r.score >= 70 ? 'text-brand-green' :
                          r.score <= 30 ? 'text-red-400' :
                          r.score >= 60 ? 'text-green-400/70' :
                          r.score <= 40 ? 'text-red-400/70' : 'text-gray-400'
                        }`}>
                          {r.score}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-white">
                        ${r.current_price?.toLocaleString(undefined, { maximumFractionDigits: r.current_price > 100 ? 0 : 4 })}
                      </td>
                      <td className="px-3 py-2.5 text-center font-mono">
                        <span className={r.rsi > 70 ? 'text-red-400' : r.rsi < 30 ? 'text-brand-green' : 'text-gray-400'}>
                          {r.rsi}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-center font-mono text-gray-400">{r.adx}</td>
                      <td className="px-3 py-2.5 text-center">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${
                          r.market_regime === 'trending' ? 'bg-brand-green/10 text-brand-green' :
                          r.market_regime === 'ranging' ? 'bg-yellow-500/10 text-yellow-400' :
                          'bg-gray-500/10 text-gray-400'
                        }`}>
                          {r.market_regime === 'trending' ? '趋势' : r.market_regime === 'ranging' ? '震荡' : '过渡'}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-center font-mono">
                        <span className={r.rr_ratio >= 1.5 ? 'text-brand-green' : 'text-yellow-400'}>
                          {r.rr_ratio?.toFixed(1) || '—'}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        {r.allocated_pct > 0 ? (
                          <div className="flex items-center gap-1 justify-center">
                            <div className="w-12 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                              <div className="h-full bg-cyan-400 rounded-full" style={{ width: `${Math.min(100, r.allocated_pct * 2)}%` }} />
                            </div>
                            <span className="text-cyan-400 font-bold font-mono text-[9px]">{r.allocated_pct}%</span>
                          </div>
                        ) : (
                          <span className="text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); switchToCoin(r.symbol) }}
                          className="text-[9px] px-2 py-1 rounded bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition-all"
                        >
                          查看 →
                        </button>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Summary bar */}
            {summary && (
              <div className="px-5 py-2 border-t border-glass flex items-center justify-between text-[10px] text-gray-500">
                <span>共享风险池: <span className="text-cyan-400 font-bold">${summary.total_risk_pool}</span></span>
                <span>可交易: <span className="text-brand-green font-bold">{summary.tradeable}</span> / {summary.total_symbols}</span>
                <span className="text-[9px] text-gray-600">点击任意行切换到该币种分析</span>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
