import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTradingStore } from '../store/tradingStore'

import CapitalOverview from './managed/CapitalOverview'
import HybridAIDashboard from './managed/HybridAIDashboard'
import TradingStats from './managed/TradingStats'
import ExecutionLog from './managed/ExecutionLog'
import PositionsTable from './managed/PositionsTable'

const API_BASE = 'http://127.0.0.1:8000'

export default function TradingPanel() {
  const { symbol, finalDecision, setFinalDecision, autoTrading, setAutoTrading, managedMode, managedSymbols, deepAnalysisSymbols, setManagedMode, setManagedSymbols, setDeepAnalysisSymbols, backendManaged, setBackendManaged, crisisMode, setCrisisMode, crisisInfo, setCrisisInfo, perSymbolStatus, setPerSymbolStatus } = useTradingStore()

  // Clear AI recommendation when symbol changes
  useEffect(() => {
    if (finalDecision) {
      setFinalDecision(null)
    }
  }, [symbol])
  const [tradingMode, setTradingMode] = useState('paper')
  const [side, setSide] = useState('buy')
  const [amount, setAmount] = useState('0.01')
  const [leverage, setLeverage] = useState('5')
  const [tpPrice, setTpPrice] = useState('')
  const [slPrice, setSlPrice] = useState('')
  const [selectedExchange, setSelectedExchange] = useState('binance')
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [balance, setBalance] = useState(() => {
    try { return parseFloat(localStorage.getItem('paperBalance')) || 1000 } catch { return 1000 }
  })
  const initialBalanceRef = useRef(balance)
  const [executing, setExecuting] = useState(false)

  // Position sizing
  const [sizingMode, setSizingMode] = useState('usdt')  // 'qty' | 'usdt' | 'pct'
  const [sizingValue, setSizingValue] = useState('100')  // default 100 USDT
  const [currentPrice, setCurrentPrice] = useState(0)
  const [autoExecThreshold, setAutoExecThreshold] = useState(55)
  const [riskPercent, setRiskPercent] = useState(2.0)
  const [tradeFreq, setTradeFreq] = useState('manual')
  const [customFreqValue, setCustomFreqValue] = useState('15')
  const [customFreqUnit, setCustomFreqUnit] = useState('min')
  const [activeTab, setActiveTab] = useState('trade') // trade | managed | chat
  const [chatInput, setChatInput] = useState('')
  const [chatMessages, setChatMessages] = useState([])
  const [chatLoading, setChatLoading] = useState(false)

  // Trade history state
  const [tradeHistory, setTradeHistory] = useState({ trades: [], stats: {}, daily_summary: [], equity_curve: [] })
  const [historyFilter, setHistoryFilter] = useState('all') // today | 7d | 30d | all
  const [historyView, setHistoryView] = useState('trades') // trades | daily | stats
  const [showHistory, setShowHistory] = useState(true)

  // AI Managed state
  const [riskStats, setRiskStats] = useState(null)
  const [managedRunning, setManagedRunning] = useState(false)
  const [managedStrategy, setManagedStrategy] = useState(null)
  const [managedLogs, setManagedLogs] = useState(() => {
    try { return JSON.parse(localStorage.getItem('managedLogs') || '[]').slice(-500) } catch { return [] }
  })
  // Auto-save logs to localStorage
  useEffect(() => {
    try { localStorage.setItem('managedLogs', JSON.stringify(managedLogs.slice(-500))) } catch {}
  }, [managedLogs])
  const [nextTradeCountdown, setNextTradeCountdown] = useState(0)
  const [managedFreqMins, setManagedFreqMins] = useState(5)
  const managedTimerRef = useRef(null)
  const countdownRef = useRef(null)
  
  // Load state from backend on mount (survive page refresh)
  useEffect(() => {
    fetch(`${API_BASE}/api/managed/status`)
      .then(res => res.json())
      .then(data => {
        if (data.success && data.recent_events?.length) {
          const restored = data.recent_events.map(e => ({
            time: e.time ? new Date(e.time).toLocaleTimeString('zh-CN') : '',
            type: e.event || 'info',
            text: e.reason || e.detail || e.event || JSON.stringify(e),
          }))
          setManagedLogs(prev => prev.length === 0 ? restored : prev)
        }
        // Restore balance from backend
        if (data.config?.balance) {
          setBalance(data.config.balance)
          initialBalanceRef.current = data.config.balance
          localStorage.setItem('paperBalance', String(data.config.balance))
        }
        // Restore managed running state from backend
        if (data.running) {
          setManagedRunning(true)
          setAutoTrading(true)
          setBackendManaged(true)
          // Restore crisis mode
          const la = data.last_analysis || {}
          setCrisisMode(la.mode === 'crisis')
          setCrisisInfo({ mode: la.mode, symbol: la.symbol, score: la.score, direction: la.direction })
          // Restore per-symbol status
          const symStatus = {}
          for (const ev of (data.recent_events || [])) {
            if (ev.symbol) {
              symStatus[ev.symbol] = { direction: ev.direction || 'neutral', score: ev.score || 50, mode: ev.mode || la.mode, event: ev.event, time: ev.time }
            }
          }
          if (Object.keys(symStatus).length > 0) setPerSymbolStatus(symStatus)
          // Restore interval
          if (data.config?.interval) {
            const m = parseInt(data.config.interval)
            if (m > 0) setManagedFreqMins(m)
          }
          // Start countdown timer
          countdownRef.current = setInterval(() => {
            setNextTradeCountdown(prev => Math.max(0, prev - 1))
          }, 1000)
          setManagedLogs(prev => [...prev, {
            time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
            text: `♻️ 后端托管运行中 — 已恢复 (${data.session?.cycles || 0}轮已完成)`
          }])
        }
      })
      .catch(() => {})
  }, [])
  
  // Hybrid cycle state
  const [quickMode, setQuickMode] = useState('tech_llm') // 'pure_tech' | 'tech_llm'
  const [deepFreqHours, setDeepFreqHours] = useState(0) // 0 = manual only
  const [deepBias, setDeepBias] = useState(null) // Last deep analysis result
  const [nextDeepCountdown, setNextDeepCountdown] = useState(0)
  const deepTimerRef = useRef(null)
  const cycleRunningRef = useRef(false)
  const lastTradeTimeRef = useRef(0) // Cooldown: timestamp of last trade
  const autoCloseRunningRef = useRef(false) // Prevent concurrent auto-close

  // Fetch current price for sizing calculations
  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/price?symbol=${symbol}`)
        const data = await res.json()
        if (data.success && data.price) setCurrentPrice(data.price)
      } catch (e) { /* silent */ }
    }
    fetchPrice()
    const iv = setInterval(fetchPrice, 5000)
    return () => clearInterval(iv)
  }, [symbol])

  // Compute actual coin quantity from sizing mode
  const getActualAmount = useCallback(() => {
    const val = parseFloat(sizingValue) || 0
    const price = currentPrice || finalDecision?.entry_price || 1
    const lev = parseInt(leverage) || 1
    if (sizingMode === 'qty') return val
    if (sizingMode === 'usdt') {
      // USDT value → margin. Actual position = margin * leverage / price
      return val * lev / price
    }
    if (sizingMode === 'pct') {
      // % of balance → margin. Actual position = (balance * pct/100) * leverage / price
      const margin = balance * (val / 100)
      return margin * lev / price
    }
    return 0
  }, [sizingMode, sizingValue, currentPrice, leverage, balance, finalDecision])

  // Evolution / Reflection state
  const [reflections, setReflections] = useState([])
  const [evolutionRules, setEvolutionRules] = useState([])
  const [evoStats, setEvoStats] = useState(null)
  const [evoSummary, setEvoSummary] = useState(null)

  // Position stats state
  const [positionStats, setPositionStats] = useState(null)

  // Managed report state
  const [managedReport, setManagedReport] = useState(null)
  const [showReport, setShowReport] = useState(false)

  // One-click AI trade state
  const [autoTradeLoading, setAutoTradeLoading] = useState(false)

  // Multi-scan & Backtest state
  const [multiScan, setMultiScan] = useState([])
  const [scanLoading, setScanLoading] = useState(false)
  const [backtestResult, setBacktestResult] = useState(null)
  const [backtestLoading, setBacktestLoading] = useState(false)

  // Sync deep bias from manual Start Analysis
  useEffect(() => {
    if (finalDecision) {
      if (finalDecision.leverage) setLeverage(String(Math.round(finalDecision.leverage)))
      if (finalDecision.entry_price) setTpPrice(String(finalDecision.exit_price || ''))
      if (finalDecision.stop_loss) setSlPrice(String(finalDecision.stop_loss || ''))
      if (finalDecision.direction === 'bullish') setSide('buy')
      else if (finalDecision.direction === 'bearish') setSide('sell')
      // Update deep bias when full analysis completes (from Start Analysis or deep cycle)
      const newBias = {
        direction: finalDecision.direction, score: finalDecision.score,
        entry_price: finalDecision.entry_price, exit_price: finalDecision.exit_price,
        stop_loss: finalDecision.stop_loss, leverage: finalDecision.leverage,
      }
      setDeepBias(newBias)
      if (managedRunning) {
        setManagedStrategy({
          direction: finalDecision.direction, entry: finalDecision.entry_price,
          tp: finalDecision.exit_price, sl: finalDecision.stop_loss,
          leverage: finalDecision.leverage, score: finalDecision.score,
          reasoning: finalDecision.reasoning,
          updatedAt: new Date().toLocaleTimeString('zh-CN'), source: 'deep',
        })
        setManagedLogs(prev => [...prev, {
          time: new Date().toLocaleTimeString('zh-CN'), type: 'decision',
          text: '🔬 深度分析结果已同步到托管策略'
        }])
      }
    }
  }, [finalDecision, managedRunning])

  // ===== TRADE HISTORY FETCH =====
  const fetchTradeHistory = useCallback(async () => {
    try {
      let url = `${API_BASE}/api/trade/history`
      const params = []
      const now = new Date()
      if (historyFilter === 'today') {
        params.push(`start_date=${now.toISOString().slice(0, 10)}`)
      } else if (historyFilter === '7d') {
        const d = new Date(now - 7 * 86400000)
        params.push(`start_date=${d.toISOString().slice(0, 10)}`)
      } else if (historyFilter === '30d') {
        const d = new Date(now - 30 * 86400000)
        params.push(`start_date=${d.toISOString().slice(0, 10)}`)
      }
      if (params.length) url += '?' + params.join('&')
      const res = await fetch(url)
      const data = await res.json()
      if (data.success) setTradeHistory(data)
    } catch (e) { /* silent */ }
  }, [historyFilter])

  useEffect(() => {
    fetchTradeHistory()
    const iv = setInterval(fetchTradeHistory, 30000)
    return () => clearInterval(iv)
  }, [fetchTradeHistory])

  // ===== BACKEND POSITION POLLING (every 3s) =====
  const fetchPositions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/positions`)
      const data = await res.json()
      if (data.success) {
        setPositions(data.positions || [])
      }
    } catch (e) { /* silent */ }
  }, [])

  useEffect(() => {
    fetchPositions()
    const iv = setInterval(fetchPositions, 3000) // Poll every 3s to get live PnL
    return () => clearInterval(iv)
  }, [fetchPositions])

  // ===== EVOLUTION DATA POLLING (every 30s) =====
  const fetchEvolutionData = useCallback(async () => {
    try {
      const [refRes, ruleRes, sumRes] = await Promise.all([
        fetch(`${API_BASE}/api/reflections?limit=20`),
        fetch(`${API_BASE}/api/reflections/rules`),
        fetch(`${API_BASE}/api/reflections/summary`),
      ])
      const refData = await refRes.json()
      const ruleData = await ruleRes.json()
      const sumData = await sumRes.json()
      if (refData.success) setReflections(refData.reflections || [])
      if (ruleData.success) {
        setEvolutionRules(ruleData.active_rules || [])
        setEvoStats(ruleData.stats || null)
      }
      if (sumData.success) setEvoSummary(sumData)
    } catch (e) { /* silent */ }
  }, [])

  useEffect(() => {
    fetchEvolutionData()
    const iv = setInterval(fetchEvolutionData, 30000)
    return () => clearInterval(iv)
  }, [fetchEvolutionData])

  // ===== POSITION STATS POLLING (every 10s) =====
  const fetchPositionStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/positions/stats`)
      const data = await res.json()
      if (data.success) setPositionStats(data)
    } catch (e) { /* silent */ }
  }, [])

  useEffect(() => {
    fetchPositionStats()
    const iv = setInterval(fetchPositionStats, 10000)
    return () => clearInterval(iv)
  }, [fetchPositionStats])

  // Multi-symbol scanner
  const fetchMultiScan = useCallback(async () => {
    setScanLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/multi-scan?symbols=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT`)
      const data = await res.json()
      if (data.opportunities) setMultiScan(data.opportunities)
    } catch (e) { /* silent */ }
    setScanLoading(false)
  }, [])

  // Backtest runner
  const runBacktest = useCallback(async (sym = 'BTCUSDT', days = 30) => {
    setBacktestLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/backtest?symbol=${sym}&days=${days}&score_threshold=65`, { method: 'POST' })
      const data = await res.json()
      if (data.backtest) setBacktestResult(data.backtest)
    } catch (e) { /* silent */ }
    setBacktestLoading(false)
  }, [])

  // ===== QUICK CYCLE — uses /api/quick-analyze, <10s =====
  const runQuickCycle = useCallback(async () => {
    if (cycleRunningRef.current) {
      setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait', text: '⏳ 上一轮仍在进行，跳过' }])
      return
    }
    cycleRunningRef.current = true
    const now = new Date().toLocaleTimeString('zh-CN')
    const modeLabel = quickMode === 'pure_tech' ? '纯技术指标' : '技术+LLM'
    
    // === MULTI-COIN MODE ===
    if (managedMode === 'multi' && managedSymbols.length > 1) {
      setManagedLogs(prev => [...prev, { time: now, type: 'info', text: `🌐 多币种扫描 (${managedSymbols.length}个) [${modeLabel}]...` }])
      try {
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 60000)
        const res = await fetch(`${API_BASE}/api/multi-analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbols: managedSymbols,
            use_llm: quickMode === 'tech_llm',
            account_balance: balance,
            risk_pct: riskPercent,
            deep_bias: deepBias,
          }),
          signal: controller.signal,
        })
        clearTimeout(timeoutId)
        const data = await res.json()
        if (data.success && data.results) {
          const sb = data.summary || {}
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'decision',
              text: `📊 扫描完成: ${sb.tradeable}/${sb.total_symbols} 有信号 | 风险池 $${sb.total_risk_pool}${sb.strongest ? ` | 最强: ${sb.strongest} (${sb.strongest_score}/100)` : ''}` },
          ])
          // Process each tradeable coin
          for (const r of data.results) {
            if (!r.success) continue
            const coinLabel = r.symbol.replace('USDT', '')
            const dirIcon = r.direction === 'bullish' ? '📈' : r.direction === 'bearish' ? '📉' : '➡️'
            const dirName = r.direction === 'bullish' ? '做多' : r.direction === 'bearish' ? '做空' : '观望'
            if (r.direction === 'neutral') {
              setManagedLogs(prev => [...prev,
                { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait',
                  text: `${coinLabel}: ${dirIcon} ${dirName} (${r.score}/100)` },
              ])
              continue
            }
            const shouldTrade = r.score >= autoExecThreshold || r.score <= (100 - autoExecThreshold)
            setManagedLogs(prev => [...prev,
              { time: new Date().toLocaleTimeString('zh-CN'), type: shouldTrade ? 'decision' : 'wait',
                text: `${coinLabel}: ${dirIcon} ${dirName} ${r.score}/100 | 价格 $${r.current_price?.toLocaleString()} | 份额 ${r.allocated_pct}% ($${r.allocated_risk})${shouldTrade ? ' → 执行' : ' → 信号不足'}` },
            ])
            // Auto-execute if signal is strong enough
            if (shouldTrade && r.weighted_position_size) {
              const tradeDir = r.direction === 'bullish' ? 'buy' : 'sell'
              try {
                const openRes = await fetch(`${API_BASE}/api/trade/execute`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    symbol: r.symbol, side: tradeDir,
                    mode: tradingMode,
                    account_balance: balance,
                    risk_pct: riskPercent,
                  })
                })
                const openData = await openRes.json()
                if (openData.success) {
                  setManagedLogs(prev => [...prev,
                    { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
                      text: `✅ ${coinLabel} ${tradeDir === 'buy' ? '做多' : '做空'} ${r.weighted_position_size.toFixed(6)} @ $${r.entry_price?.toLocaleString()} | 保证金 $${r.weighted_margin} | 份额${r.allocated_pct}%` },
                  ])
                  fetchPositions()
                } else {
                  setManagedLogs(prev => [...prev,
                    { time: new Date().toLocaleTimeString('zh-CN'), type: 'error',
                      text: `❌ ${coinLabel} 开仓失败: ${openData.error}` },
                  ])
                }
              } catch (err) {
                setManagedLogs(prev => [...prev,
                  { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `❌ ${coinLabel} 下单失败: ${err.message}` },
                ])
              }
            }
          }
        } else {
          setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `⚠️ ${data.error || '多币种分析无结果'}` }])
        }
      } catch (e) {
        const msg = e.name === 'AbortError' ? '⏰ 多币种分析超时，下轮重试' : `❌ ${e.message}`
        setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: msg }])
      } finally {
        cycleRunningRef.current = false
      }
      return
    }
    
    // === SINGLE-COIN MODE (original logic) ===
    setManagedLogs(prev => [...prev, { time: now, type: 'info', text: `🔄 快速分析 (${modeLabel})${deepBias ? ' [参考深度偏好]' : ''}...` }])
    
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 30000) // 30s for quick
      
      const res = await fetch(`${API_BASE}/api/quick-analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol, interval: '15m',
          use_llm: quickMode === 'tech_llm',
          deep_bias: deepBias,
          account_balance: balance,
          risk_pct: riskPercent,
        }),
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      
      const data = await res.json()
      
      if (data.success && data.final_decision) {
        const fd = data.final_decision
        const indicators = data.indicators || {}
        const tradeAmount = parseFloat(amount) || 0.01
        const lev = fd.leverage || 3
        const positionValue = tradeAmount * (fd.entry_price || 0)
        const marginUsed = positionValue / lev
        
        setManagedStrategy({
          direction: fd.direction, entry: fd.entry_price,
          tp: fd.exit_price, sl: fd.stop_loss,
          leverage: lev, score: fd.score,
          reasoning: fd.reasoning,
          updatedAt: new Date().toLocaleTimeString('zh-CN'),
          source: 'quick', indicators,
          llmEnhanced: data.llm_enhanced,
          deepBiasApplied: data.deep_bias_applied,
          riskInfo: data.risk_info || null,
          scoreBreakdown: data.score_breakdown || [],
          marketRegime: indicators?.market_regime || null,
        })
        
        const dirLabel = fd.direction === 'bullish' ? '📈 做多' : fd.direction === 'bearish' ? '📉 做空' : '➡️ 观望'
        const llmTag = data.llm_enhanced ? ' [LLM]' : ''
        const biasTag = data.deep_bias_applied ? ' [深度偏好]' : ''
        
        // Calculate risk/reward
        const riskPct = fd.stop_loss && fd.entry_price 
          ? Math.abs((fd.stop_loss - fd.entry_price) / fd.entry_price * 100 * lev).toFixed(2) 
          : '?'
        const rewardPct = fd.exit_price && fd.entry_price 
          ? Math.abs((fd.exit_price - fd.entry_price) / fd.entry_price * 100 * lev).toFixed(2) 
          : '?'
        const riskUSDT = fd.stop_loss && fd.entry_price 
          ? Math.abs((fd.stop_loss - fd.entry_price) * tradeAmount).toFixed(2)
          : '?'
        const rewardUSDT = fd.exit_price && fd.entry_price 
          ? Math.abs((fd.exit_price - fd.entry_price) * tradeAmount).toFixed(2)
          : '?'
        const rrRatio = riskUSDT !== '?' && rewardUSDT !== '?' && parseFloat(riskUSDT) > 0 
          ? (parseFloat(rewardUSDT) / parseFloat(riskUSDT)).toFixed(1)
          : '?'
        
        const ri = data.risk_info || {}
        const rrFromApi = ri.rr_ratio ? ri.rr_ratio.toFixed(1) : rrRatio
        setManagedLogs(prev => [...prev,
          { time: new Date().toLocaleTimeString('zh-CN'), type: 'decision',
            text: `${dirLabel} | 评分 ${fd.score}/100 | 杠杆 ${lev}x${llmTag}${biasTag}` },
          { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
            text: `📍 $${fd.entry_price?.toLocaleString()} | 🎯 TP $${fd.exit_price?.toLocaleString()} | 🛑 SL $${fd.stop_loss?.toLocaleString()}` },
          { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
            text: `💰 仓位 ${ri.position_size || '?'} (≈$${ri.position_value || '?'}) | 保证金 $${ri.margin_required || '?'} | R:R ${rrFromApi}:1 | 胜率 ${ri.win_probability || '?'}%` },
          { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
            text: `RSI=${indicators.rsi} | MACD ${indicators.macd > 0 ? '多头' : '空头'} | BB ${indicators.bb_position}% | 量比${indicators.volume_ratio}` },
        ])
        
        // Auto-execute trades: direction is clear + score passes user threshold
        const shouldExecute = fd.direction !== 'neutral' && (fd.score >= autoExecThreshold || fd.score <= (100 - autoExecThreshold))
        const isNeutralRange = fd.direction === 'neutral' && data.range_strategy
        
        // === EXPOSURE CHECK ===
        const MAX_EXPOSURE_PCT = 0.6 // Max 60% of balance in margin
        const totalMargin = positions.reduce((sum, p) => sum + (p.marginUsed || 0), 0)
        const exposurePct = totalMargin / balance
        const overExposed = exposurePct >= MAX_EXPOSURE_PCT
        
        // === ENTRY DISTANCE CHECK ===
        const MIN_ENTRY_DISTANCE_PCT = 0.003 // 0.3% minimum between entries
        const sameDirectionPositions = positions.filter(p => p.symbol === symbol && p.side === (fd.direction === 'bullish' ? 'buy' : 'sell'))
        const tooCloseToExisting = sameDirectionPositions.some(p => 
          Math.abs(fd.entry_price - p.entry_price) / p.entry_price < MIN_ENTRY_DISTANCE_PCT
        )
        
        if (shouldExecute && overExposed) {
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait',
              text: `⚠️ 总保证金占用 ${(exposurePct * 100).toFixed(1)}% ≥ ${MAX_EXPOSURE_PCT * 100}% 上限，跳过开仓` },
          ])
        } else if (shouldExecute && tooCloseToExisting) {
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait',
              text: `⚠️ 入场价 $${fd.entry_price?.toLocaleString()} 距现有仓位 <0.3%，避免密集建仓` },
          ])
        } else if (shouldExecute) {
          const tradeDir = fd.direction === 'bullish' ? 'buy' : 'sell'
          // Use SIGNAL-SCALED position size (dynamic based on score strength)
          const aiAmount = ri.signal_scaled_size ? parseFloat(ri.signal_scaled_size) : (ri.position_size ? parseFloat(ri.position_size) : parseFloat(amount) || 0.01)
          const aiPositionValue = ri.signal_scaled_value || ri.position_value || (aiAmount * (fd.entry_price || 0))
          const aiMarginUsed = ri.signal_scaled_margin || ri.margin_required || (aiPositionValue / lev)
          const signalTier = ri.signal_tier || '—'
          const positionPct = ri.position_pct || '?'
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
              text: `✅ 信号确认 (${fd.score}/100 ${fd.score >= autoExecThreshold ? '≥' : '≤'}${autoExecThreshold}) → 自动执行 ${dirLabel}` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   ┌ 交易对: ${symbol} | 方向: ${tradeDir === 'buy' ? '做多' : '做空'} | 杠杆: ${lev}x` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 📐 仓位管理: ${signalTier} | 使用余额 ${positionPct}% (信号强度 ${ri.signal_strength || 0}/50)` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 仓位: ${aiAmount.toFixed(6)} ${symbol.replace('USDT','')} (≈$${aiPositionValue.toFixed(0)} / 保证金 $${aiMarginUsed.toFixed(0)})` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 账户余额: $${balance.toLocaleString()} → 占用 ${(aiMarginUsed / balance * 100).toFixed(1)}%` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 入场: $${fd.entry_price?.toLocaleString()} → 止盈: $${fd.exit_price?.toLocaleString()} | 止损: $${fd.stop_loss?.toLocaleString()}` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 盈亏比: ${rrFromApi}:1 | 潜在盈利: +$${rewardUSDT} (+${rewardPct}%) | 潜在亏损: -$${riskUSDT} (-${riskPct}%)` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 技术: RSI=${indicators.rsi} MACD=${indicators.macd > 0 ? '多头' : '空头'} BB=${indicators.bb_position}%` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   └ 理由: ${fd.reasoning?.slice(0, 80) || '技术指标综合判断'}` },
          ])
          try {
            // === PROFESSIONAL POSITION MANAGEMENT ===
            // Check existing positions for this symbol
            const existingSame = positions.filter(p => p.symbol === symbol && p.side === tradeDir)
            const existingOpposite = positions.filter(p => p.symbol === symbol && p.side !== tradeDir)
            const MAX_PYRAMID = 3 // Max positions per symbol per direction
            const PYRAMID_SCORE = 65 // Minimum score for pyramiding
            const PYRAMID_SIZE_FACTOR = 0.5 // Each pyramid layer is 50% of base size
            
            let action = 'new' // new | pyramid | replace | reverse
            let pyramidAmount = aiAmount
            let closedPositions = []

            if (existingOpposite.length > 0) {
              // REVERSE: Close opposite direction positions first
              action = 'reverse'
              for (const p of existingOpposite) {
                try {
                  await fetch(`${API_BASE}/api/positions/close`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ position_id: p.id, reason: 'reverse' }),
                  })
                  closedPositions.push(p)
                } catch (e) { /* continue */ }
              }
              fetchPositions()
              setManagedLogs(prev => [...prev,
                { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
                  text: `🔄 反向信号 → 先平掉 ${existingOpposite.length} 个反向仓位` },
              ])
            } else if (existingSame.length > 0) {
              const profitableCount = existingSame.filter(p => (p.pnl || 0) > 0).length
              const allProfitable = profitableCount === existingSame.length
              
              if (allProfitable && fd.score >= PYRAMID_SCORE && existingSame.length < MAX_PYRAMID) {
                // PYRAMID: Strong trend + all existing positions profitable + under max
                action = 'pyramid'
                const layer = existingSame.length + 1
                pyramidAmount = aiAmount * Math.pow(PYRAMID_SIZE_FACTOR, existingSame.length) // Each layer 50% smaller
                setManagedLogs(prev => [...prev,
                  { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
                    text: `📐 趋势加仓 (第${layer}层) — 评分${fd.score}≥${PYRAMID_SCORE} & ${existingSame.length}个持仓全盈利 → 加仓 ${(pyramidAmount).toFixed(6)} (${(PYRAMID_SIZE_FACTOR*100)}%递减)` },
                ])
              } else if (!allProfitable || fd.score < PYRAMID_SCORE) {
                // REPLACE: Same direction but losing or weak signal → close old, open new
                action = 'replace'
                for (const p of existingSame) {
                  try {
                    await fetch(`${API_BASE}/api/positions/close`, {
                      method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ position_id: p.id, reason: 'replace' }),
                    })
                    closedPositions.push(p)
                  } catch (e) { /* continue */ }
                }
                fetchPositions()
                setManagedLogs(prev => [...prev,
                  { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
                    text: `🔁 平旧开新 — ${existingSame.length}个旧仓${allProfitable ? '(盈利但评分不足加仓)' : '(含亏损仓)'} → 先平仓记录盈亏` },
                ])
              } else {
                // At max pyramid layers, skip
                action = 'skip'
                setManagedLogs(prev => [...prev,
                  { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait',
                    text: `⏸ 已达最大加仓层数 (${MAX_PYRAMID}层)，跳过本次信号` },
                ])
              }
            }
            
            // Record closed positions PnL
            if (closedPositions.length > 0) {
              const closedPnl = closedPositions.reduce((sum, p) => sum + (p.pnl || 0), 0)
              setBalance(prev => prev + closedPnl)
              setManagedLogs(prev => [...prev,
                { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
                  text: `   💰 平仓 ${closedPositions.length} 笔 → 盈亏 ${closedPnl >= 0 ? '+' : ''}$${closedPnl.toFixed(2)} 已记录到历史` },
              ])
              setTimeout(fetchTradeHistory, 500)
            }
            
            if (action !== 'skip') {
              const finalAmount = action === 'pyramid' ? pyramidAmount : aiAmount
              
              // === USE BACKEND trade/execute (registers with position_manager) ===
              const openRes = await fetch(`${API_BASE}/api/trade/execute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  symbol, side: tradeDir,
                  mode: tradingMode,
                  account_balance: balance,
                  risk_pct: riskPercent,
                })
              })
              const openData = await openRes.json()
              
              if (!openData.success) {
                setManagedLogs(prev => [...prev,
                  { time: new Date().toLocaleTimeString('zh-CN'), type: 'error',
                    text: `❌ 开仓被拒: ${openData.error}` },
                ])
              } else {
                const pos = openData.position
                setOrders(prev => [{
                  id: pos.id, time: new Date().toLocaleTimeString('zh-CN'),
                  symbol, side: tradeDir, amount: finalAmount, leverage: lev,
                  price: fd.entry_price, mode: tradingMode, exchange: selectedExchange,
                  label: action === 'pyramid' ? 'AI加仓' : 'AI自动', source: 'ai', status: 'success',
                  positionValue: aiPositionValue, marginUsed: pos.margin_used,
                  riskAmount: ri.max_risk_amount, rrRatio: rrFromApi,
                }, ...prev])
                // Positions will be updated by polling from backend
                fetchPositions()
              }
            }
            
            const actionLabel = { new: '新建', pyramid: '加仓', replace: '换仓', reverse: '反向', skip: '跳过' }[action]
            if (action !== 'skip') {
              lastTradeTimeRef.current = Date.now()
              setManagedLogs(prev => [...prev,
                { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
                  text: `✅ ${actionLabel}成功 → ${tradeDir === 'buy' ? '做多' : '做空'} ${(action === 'pyramid' ? pyramidAmount : aiAmount).toFixed(6)} ${symbol} @ $${fd.entry_price?.toLocaleString()}` },
                { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
                  text: `   📊 当前持仓 ${positions.length + 1} 个 | 📋 下一步: ${managedFreqMins}分钟后重新评估` },
              ])
            }
          } catch (err) {
            setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `❌ 下单失败: ${err.message}` }])
          }
        } else if (isNeutralRange) {
          // Neutral with range strategy — show detailed range trading plan
          const rs = data.range_strategy
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'decision',
              text: `📐 震荡区间策略 — 高抛低吸 (杠杆 ${rs.recommended_leverage}x)` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   ┌ 区间上轨: $${rs.range_high?.toLocaleString()} (接近时做空)` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   │ 区间中轨: $${rs.range_mid?.toLocaleString()} (当前价 $${fd.entry_price?.toLocaleString()})` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   └ 区间下轨: $${rs.range_low?.toLocaleString()} (接近时做多)` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'decision',
              text: `   📈 挂多计划: 入${tradeAmount}个 @ $${rs.long?.entry?.toLocaleString()} → TP $${rs.long?.tp?.toLocaleString()} | SL $${rs.long?.sl?.toLocaleString()}` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'decision',
              text: `   📉 挂空计划: 入${tradeAmount}个 @ $${rs.short?.entry?.toLocaleString()} → TP $${rs.short?.tp?.toLocaleString()} | SL $${rs.short?.sl?.toLocaleString()}` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   👆 可在策略面板中点击执行按钮，或继续等待方向明确` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   📋 下一步: ${managedFreqMins}分钟后重新评估，若突破区间将转为趋势策略` },
          ])
          setManagedStrategy(prev => ({ ...prev, rangeStrategy: rs }))
        } else if (fd.direction !== 'neutral') {
          // Direction clear but moderate score — log details but don't auto-execute
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait',
              text: `⚠️ ${dirLabel} 方向初现 (${fd.score}/100)，尚不满足自动执行条件` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   入场 $${fd.entry_price?.toLocaleString()} | TP $${fd.exit_price?.toLocaleString()} | SL $${fd.stop_loss?.toLocaleString()} | 盈亏比 ${rrRatio}:1` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   📋 下一步: 等待评分突破65(做多)或跌破35(做空)后自动执行，或手动干预` },
          ])
        } else {
          setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'wait',
              text: `⏸ 方向不明 (${fd.score}/100)，继续观望` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info',
              text: `   📋 下一步: ${managedFreqMins}分钟后重新分析` },
          ])
        }
      } else {
        setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `⚠️ ${data.error || '快速分析无结果'}` }])
      }
    } catch (e) {
      const msg = e.name === 'AbortError' ? '⏰ 快速分析超时（30s），下轮重试' : `❌ ${e.message}`
      setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: msg }])
    } finally {
      cycleRunningRef.current = false
    }
  }, [symbol, amount, tradingMode, selectedExchange, quickMode, deepBias, managedFreqMins, managedMode, managedSymbols])

  // ===== DEEP CYCLE — uses /api/analyze, full agent analysis =====
  const runDeepCycle = useCallback(async () => {
    const deepSymbols = managedMode === 'multi' ? deepAnalysisSymbols : [symbol]
    setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'info', text: `🔬 深度分析启动（5 Agent 圆桌）— ${deepSymbols.map(s => s.replace('USDT','')).join(', ')}` }])
    for (const sym of deepSymbols) {
      const coinLabel = sym.replace('USDT', '')
    try {
      const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 180000)
      
      const res = await fetch(`${API_BASE}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: sym, interval: '15m' }),
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      const data = await res.json()
      
      if (data.success && data.final_decision) {
        const fd = data.final_decision
          const newBias = { direction: fd.direction, score: fd.score, entry_price: fd.entry_price, exit_price: fd.exit_price, stop_loss: fd.stop_loss, leverage: fd.leverage }
          if (sym === symbol) setDeepBias(newBias)  // Only set as primary bias if it's the current chart symbol
        setManagedStrategy({
          direction: fd.direction, entry: fd.entry_price, tp: fd.exit_price,
          sl: fd.stop_loss, leverage: fd.leverage, score: fd.score,
          reasoning: fd.reasoning,
          updatedAt: new Date().toLocaleTimeString('zh-CN'), source: 'deep',
        })
        const dirLabel = fd.direction === 'bullish' ? '📈' : fd.direction === 'bearish' ? '📉' : '➡️'
        setManagedLogs(prev => [...prev,
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'decision', text: `🔬 ${coinLabel}: ${dirLabel} ${fd.direction} | ${fd.score}/100 | ${fd.leverage}x` },
            { time: new Date().toLocaleTimeString('zh-CN'), type: 'info', text: `   📍 $${fd.entry_price?.toLocaleString()} | 🎯 $${fd.exit_price?.toLocaleString()} | 🛑 $${fd.stop_loss?.toLocaleString()}` },
          { time: new Date().toLocaleTimeString('zh-CN'), type: 'execute', text: '✅ 深度偏好已更新 — 后续快速分析将参考此方向' },
        ])
      } else {
          setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `⚠️ ${coinLabel} 深度分析无有效结果` }])
      }
    } catch (e) {
        const msg = e.name === 'AbortError' ? `⏰ ${coinLabel} 深度分析超时` : `❌ ${coinLabel} 深度分析失败: ${e.message}`
      setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: msg }])
    }
    }
  }, [symbol, managedMode, deepAnalysisSymbols])

  // Start/stop managed trading
  const toggleManaged = async () => {
    if (managedRunning) {
      // === STOP: Call backend managed/stop ===
      try {
        const res = await fetch(`${API_BASE}/api/managed/stop`, { method: 'POST' })
        const data = await res.json()
        if (data.success) {
          setManagedLogs(prev => [...prev, {
            time: new Date().toLocaleTimeString('zh-CN'), type: 'stop',
            text: `🛑 AI 托管已停止 — ${data.session_summary?.duration || ''}`
          }])
        }
      } catch (e) {
        setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `❌ 停止失败: ${e.message}` }])
      }
      clearInterval(managedTimerRef.current)
      clearInterval(countdownRef.current)
      clearInterval(deepTimerRef.current)
      setManagedRunning(false)
      setAutoTrading(false)
      setBackendManaged(false)
      setCrisisMode(false)
    } else {
      // Always include core symbols — crisis system needs multi-symbol
      const coreSyms = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
      const syms = managedMode === 'multi'
        ? [...new Set([...managedSymbols.filter(s => s), ...coreSyms])]
        : [...new Set([symbol, ...coreSyms])]
      try {
        const res = await fetch(`${API_BASE}/api/managed/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbols: syms,
            mode: tradingMode,
            interval_minutes: managedFreqMins,
            account_balance: balance,
            risk_pct: riskPercent,
            use_llm: quickMode === 'tech_llm',
            auto_threshold: autoExecThreshold,
          }),
        })
        const data = await res.json()
        if (data.success) {
          setManagedRunning(true)
          setAutoTrading(true)
          setBackendManaged(true)
          setNextTradeCountdown(managedFreqMins * 60)
          setManagedLogs(prev => [...prev, {
            time: new Date().toLocaleTimeString('zh-CN'), type: 'start',
            text: `🚀 ${data.message || 'AI 托管启动'}`
          }])
          // Start countdown timer
          countdownRef.current = setInterval(() => {
            setNextTradeCountdown(prev => Math.max(0, prev - 1))
          }, 1000)
        } else {
          setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `❌ 启动失败: ${data.message || data.detail || '未知错误'}` }])
        }
      } catch (e) {
        setManagedLogs(prev => [...prev, { time: new Date().toLocaleTimeString('zh-CN'), type: 'error', text: `❌ 启动失败: ${e.message}` }])
      }
    }
  }

  // === Backend Status Polling (every 10s when managed is running) ===
  const statusPollRef = useRef(null)
  useEffect(() => {
    if (!managedRunning) {
      clearInterval(statusPollRef.current)
      return
    }
    const pollStatus = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/managed/status`)
        const d = await res.json()
        if (!d.success || !d.running) return
        // Update crisis mode
        const la = d.last_analysis || {}
        const isCrisis = la.mode === 'crisis'
        setCrisisMode(isCrisis)
        setCrisisInfo({ mode: la.mode, symbol: la.symbol, score: la.score, direction: la.direction })
        // Update per-symbol status from recent events
        const symStatus = {}
        for (const ev of (d.recent_events || [])) {
          if (ev.symbol) {
            symStatus[ev.symbol] = { direction: ev.direction || 'neutral', score: ev.score || 50, mode: ev.mode || la.mode, event: ev.event, time: ev.time }
          }
        }
        if (Object.keys(symStatus).length > 0) setPerSymbolStatus(symStatus)
        // Update cycle countdown
        if (d.session?.cycles) {
          setNextTradeCountdown(managedFreqMins * 60 - ((Date.now() - new Date(d.last_analysis?.time || Date.now()).getTime()) / 1000))
        }
        // Sync logs from backend events (track by total event count, not cycle)
        const events = d.recent_events || []
        const totalBackendEvents = events.length
        const lastSyncedCount = statusPollRef._lastEventCount || 0
        if (totalBackendEvents > lastSyncedCount) {
          // Only process events we haven't seen yet
          const newEvents = events.slice(lastSyncedCount)
          statusPollRef._lastEventCount = totalBackendEvents
          const newLogs = []
          // Show crisis mode change (once per poll)
          if (isCrisis && newEvents.some(e => e.symbol)) {
            newLogs.push({ time: new Date().toLocaleTimeString('zh-CN'), type: 'info', text: `🔴 危机模式 — FNG低/战争新闻` })
          }
          // Show per-symbol results
          for (const ev of newEvents) {
            if (!ev.symbol) continue
            const dirIcon = ev.direction === 'bearish' ? '📉' : ev.direction === 'bullish' ? '📈' : '➡️'
            const modeTag = ev.mode === 'crisis' ? '🔴' : '🟢'
            const evType = ev.event === 'trade_executed' ? 'execute' : 'wait'
            const reason = ev.reason || ev.detail || ''
            const entryInfo = ev.entry ? ` | $${Number(ev.entry).toLocaleString()}` : ''
            newLogs.push({
              time: ev.time ? new Date(ev.time).toLocaleTimeString('zh-CN') : new Date().toLocaleTimeString('zh-CN'),
              type: evType,
              text: `${modeTag} ${ev.symbol?.replace('USDT','')} ${dirIcon} ${ev.direction || 'neutral'} (${ev.score || 50}/100)${entryInfo} ${reason.slice(0,60)}`,
            })
          }
          if (newLogs.length > 0) {
            setManagedLogs(prev => [...prev, ...newLogs].slice(-500))
          }
        }
        // Refresh positions
        fetchPositions()
      } catch (e) { /* silent */ }
    }
    pollStatus() // poll immediately
    statusPollRef.current = setInterval(pollStatus, 10000)
    return () => clearInterval(statusPollRef.current)
  }, [managedRunning, managedFreqMins])

  // Cleanup on unmount
  useEffect(() => () => {
    clearInterval(managedTimerRef.current)
    clearInterval(countdownRef.current)
    clearInterval(deepTimerRef.current)
    clearInterval(statusPollRef.current)
  }, [])

  // Human intervention — override next trade
  const humanOverride = (overrideDir) => {
    setManagedLogs(prev => [...prev, {
      time: new Date().toLocaleTimeString('zh-CN'), type: 'override',
      text: `🖐️ 人工干预：下一笔改为 ${overrideDir === 'buy' ? '📈做多' : '📉做空'}`
    }])
    setManagedStrategy(prev => prev ? { ...prev, direction: overrideDir === 'buy' ? 'bullish' : 'bearish' } : prev)
  }

  // Execute one side of range strategy (user choice)
  const executeRangeStrategy = async (side) => {
    const rs = managedStrategy?.rangeStrategy
    if (!rs) return
    const plan = side === 'buy' ? rs.long : rs.short
    const dirLabel = side === 'buy' ? '📈 做多' : '📉 做空'
    const lev = rs.recommended_leverage || 2
    
    setManagedLogs(prev => [...prev, {
      time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
      text: `🎯 用户执行震荡策略 ${dirLabel} @ $${plan.entry?.toLocaleString()} | TP $${plan.tp?.toLocaleString()} | SL $${plan.sl?.toLocaleString()} | ${lev}x`
    }])
    
    try {
      // Single call to trade/execute — handles position_manager registration
      const openRes = await fetch(`${API_BASE}/api/trade/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol, side,
          mode: tradingMode,
          account_balance: balance,
          risk_pct: riskPercent,
        })
      })
      const openData = await openRes.json()
      if (openData.success) {
        setOrders(prev => [{
          id: openData.position?.id, time: new Date().toLocaleTimeString('zh-CN'),
          symbol, side, amount: parseFloat(amount), leverage: lev,
          price: plan.entry, mode: tradingMode, exchange: selectedExchange,
          label: 'AI震荡', source: 'ai', status: 'success'
        }, ...prev])
        fetchPositions()
      } else {
        setManagedLogs(prev => [...prev, {
          time: new Date().toLocaleTimeString('zh-CN'), type: 'error',
          text: `❌ 震荡策略开仓失败: ${openData.error}`
        }])
        return
      }
      setManagedLogs(prev => [...prev, {
        time: new Date().toLocaleTimeString('zh-CN'), type: 'execute',
        text: `✅ 震荡策略订单已提交: ${side === 'buy' ? '做多' : '做空'} ${symbol} ${lev}x`
      }])
    } catch (err) {
      setManagedLogs(prev => [...prev, {
        time: new Date().toLocaleTimeString('zh-CN'), type: 'error',
        text: `❌ 震荡策略下单失败: ${err.message}`
      }])
    }
  }

  const formatCountdown = (seconds) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${String(s).padStart(2, '0')}`
  }

  const executeOrder = async () => {
    if (executing) return
    setExecuting(true)
    try {
      const entryPrice = currentPrice || finalDecision?.entry_price || 67000
      const actualAmount = getActualAmount()
      if (actualAmount <= 0) { setExecuting(false); return }
      const res = await fetch(`${API_BASE}/api/trade/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol, side,
          mode: tradingMode,
          account_balance: balance,
          risk_pct: riskPercent,
        })
      })
      const data = await res.json()
      if (data.success) {
        setOrders(prev => [{
          id: data.position.id, time: new Date().toLocaleTimeString('zh-CN'),
          symbol, side, amount: actualAmount, leverage: parseInt(leverage),
          price: entryPrice, tp: tpPrice, sl: slPrice,
          mode: tradingMode, exchange: selectedExchange,
          source: 'manual', status: 'success'
        }, ...prev])
        fetchPositions()
      }
    } catch (e) { console.error('Trade failed:', e) }
    finally { setExecuting(false) }
  }

  // === ONE-CLICK AI TRADE (auto-analyze + auto-execute) ===
  const executeAutoTrade = async () => {
    setAutoTradeLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/trade/auto`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          mode: tradingMode,
          account_balance: balance,
          risk_pct: riskPercent,
        })
      })
      const data = await res.json()
      if (data.success) {
        setOrders(prev => [{
          id: data.position?.id, time: new Date().toLocaleTimeString('zh-CN'),
          symbol, side: data.summary?.action?.includes('做多') ? 'buy' : 'sell',
          amount: parseFloat(data.summary?.amount || '0'),
          leverage: parseInt(data.summary?.leverage || '3'),
          price: parseFloat(data.summary?.entry?.replace('$', '').replace(',', '') || '0'),
          mode: tradingMode, source: 'auto', status: 'success',
          label: '🎯 一键AI'
        }, ...prev])
        fetchPositions()
        fetchPositionStats()
      } else {
        alert(`一键交易失败: ${data.error || '未知错误'}`)
      }
    } catch (e) { alert(`一键交易异常: ${e.message}`) }
    finally { setAutoTradeLoading(false) }
  }

  // === MANAGED REPORT FETCHER ===
  const fetchManagedReport = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/managed/report`)
      const data = await res.json()
      if (data.success !== false) {
        setManagedReport(data)
        setShowReport(true)
      }
    } catch (e) { /* silent */ }
  }

  const closePosition = async (pos) => {
    try {
      // Call backend to properly close and record PnL
      const res = await fetch(`${API_BASE}/api/positions/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position_id: pos.id, reason: 'manual' }),
      })
      const data = await res.json()
      if (data.success) {
        setBalance(prev => prev + (data.pnl || 0))
      } else {
        setBalance(prev => prev + (pos.pnl || 0))
      }
    } catch (e) {
      setBalance(prev => prev + (pos.pnl || 0))
    }
    // Backend is source of truth, just refresh
    fetchPositions()
    setOrders(prev => [{
      id: Date.now(), time: new Date().toLocaleTimeString('zh-CN'),
      symbol: pos.symbol, side: pos.side === 'buy' ? 'sell' : 'buy',
      amount: pos.amount, leverage: pos.leverage, price: pos.current_price,
      mode: pos.mode, exchange: pos.exchange, label: '平仓',
      source: pos.source || 'manual', status: 'success',
      pnl: pos.pnl, roe: pos.roe,
    }, ...prev])
    // Refresh trade history after close
    setTimeout(fetchTradeHistory, 500)
  }

  // Strategy chat with AI
  const sendChat = async () => {
    if (!chatInput.trim() || chatLoading) return
    const msg = chatInput.trim()
    setChatMessages(prev => [...prev, { role: 'user', content: msg }])
    setChatInput('')
    setChatLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `[交易策略讨论] 当前标的: ${symbol}, 我的持仓: ${positions.length}个, 交易模式: ${tradingMode}, AI托管: ${managedRunning ? '运行中' : '未启动'}, 交易频率: ${managedFreqMins}分钟。用户问题: ${msg}`,
          history: chatMessages.slice(-8).map(m => ({ role: m.role, content: m.content })),
        })
      })
      const data = await res.json()
      if (data.success) {
        setChatMessages(prev => [...prev, { role: 'assistant', content: data.response }])
      }
    } catch (e) { console.error('Chat failed:', e) }
    finally { setChatLoading(false) }
  }

  // === REAL-TIME PRICE + TP/SL: Handled by backend PriceMonitor (every 3s) ===
  // Frontend relies on fetchPositions() polling to get updated PnL from backend.
  // Previously there was a duplicate price-fetch + local PnL recalc here that
  // raced with backend data, causing the PnL display to flicker.

  // Fetch risk stats periodically when managed trading is running
  useEffect(() => {
    if (!managedRunning) return
    const fetchRiskStats = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/risk-status`)
        const data = await res.json()
        if (data.success) setRiskStats(data)
      } catch (e) { /* ignore */ }
    }
    fetchRiskStats()
    const timer = setInterval(fetchRiskStats, 30000)
    return () => clearInterval(timer)
  }, [managedRunning])

  const totalPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0)
  const logTypeColors = {
    info: 'text-blue-400', decision: 'text-purple-400', execute: 'text-brand-green',
    wait: 'text-yellow-400', error: 'text-red-400', start: 'text-brand-green',
    stop: 'text-red-400', override: 'text-orange-400',
  }

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="glass-card overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 border-b border-glass">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${managedRunning ? (crisisMode ? 'bg-red-500' : 'bg-purple-400') : 'bg-brand-green'} animate-pulse-glow`} />
            Trading Terminal
            {managedRunning && <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${crisisMode ? 'bg-red-500/15 text-red-400' : 'bg-purple-500/15 text-purple-400'}`}>{crisisMode ? '🔴 危机模式' : 'AI 托管中'}</span>}
          </h3>
          <div className="flex items-center gap-3">
            <span className={`text-xs font-mono px-2 py-0.5 rounded-md ${totalPnl >= 0 ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>
              PnL: {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)} USDT
            </span>
            <span className="text-xs text-gray-500 font-mono">余额: ${balance.toLocaleString()}</span>
            <button onClick={() => {
              console.log('[Reset] Sending request...')
              fetch(`${API_BASE}/api/positions/reset`, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                  console.log('[Reset] Response:', data)
                  if (data.success) {
                    setPositions([]); setOrders([]); setManagedLogs([])
                    setBalance(initialBalanceRef.current); setManagedStrategy(null); setDeepBias(null)
                    setTradeHistory({ trades: [], stats: {}, daily_summary: [], equity_curve: [] })
                    fetchPositions(); fetchTradeHistory()
                  }
                })
                .catch(e => console.error('[Reset] Error:', e))
            }}
              className="px-2 py-1 rounded-md text-[9px] font-bold bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all"
              title="清除所有持仓、交易记录，余额重置为$10,000">
              🗑️ 重置
            </button>
            {/* Tab switcher */}
            <div className="flex bg-surface-3 rounded-md p-0.5 border border-glass">
              {[
                { key: 'trade', icon: '📋', label: '下单' },
                { key: 'managed', icon: '🤖', label: 'AI托管' },
                { key: 'chat', icon: '💬', label: '策略' },
                { key: 'evolution', icon: '🧠', label: '进化' },
              ].map(t => (
                <button key={t.key} onClick={() => setActiveTab(t.key)}
                  className={`px-2 py-1 text-[10px] font-bold rounded transition-all ${
                    activeTab === t.key
                      ? t.key === 'managed' ? 'bg-purple-500/15 text-purple-400'
                        : t.key === 'chat' ? 'bg-blue-500/15 text-blue-400'
                        : t.key === 'evolution' ? 'bg-amber-500/15 text-amber-400'
                        : 'bg-brand-green/15 text-brand-green'
                      : 'text-gray-600'
                  }`}>
                  {t.icon} {t.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* =================== AI MANAGED TAB =================== */}
      {activeTab === 'managed' && (
        <div className="p-5 space-y-4">
          {/* Capital Overview — extracted component */}
          <CapitalOverview
            balance={balance} setBalance={setBalance} initialBalanceRef={initialBalanceRef}
            tradingMode={tradingMode} positions={positions} totalPnl={totalPnl}
            riskPercent={riskPercent} setRiskPercent={setRiskPercent}
            autoExecThreshold={autoExecThreshold} setAutoExecThreshold={setAutoExecThreshold}
            managedRunning={managedRunning} managedStrategy={managedStrategy}
            fetchPositions={fetchPositions} fetchTradeHistory={fetchTradeHistory}
          />

          {/* Top: Controls + Strategy Overview */}
          <div className="grid grid-cols-12 gap-4">
            {/* Left: Controls (kept inline — too many state interdependencies) */}
            <div className="col-span-12 lg:col-span-4 space-y-3">
              {/* Trade Mode: Single vs Multi */}
              <div>
                <label className="text-[10px] text-gray-600 mb-1 block">🎯 交易模式</label>
                <div className="flex bg-surface-3 rounded-lg p-0.5 border border-glass">
                  <button onClick={() => !managedRunning && setManagedMode('single')}
                    className={`flex-1 px-2 py-1.5 text-[10px] font-bold rounded-md transition-all ${
                      managedMode === 'single' ? 'bg-purple-500/15 text-purple-400' : 'text-gray-600'
                    } ${managedRunning ? 'opacity-50' : ''}`}>
                    📍 单币种
                  </button>
                  <button onClick={() => !managedRunning && setManagedMode('multi')}
                    className={`flex-1 px-2 py-1.5 text-[10px] font-bold rounded-md transition-all ${
                      managedMode === 'multi' ? 'bg-cyan-500/15 text-cyan-400' : 'text-gray-600'
                    } ${managedRunning ? 'opacity-50' : ''}`}>
                    🌐 多币种
                  </button>
                </div>
              </div>

              {/* Crisis Mode Indicator */}
              {managedRunning && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className={`rounded-lg px-3 py-2.5 border text-[10px] ${
                    crisisMode ? 'bg-red-500/10 border-red-500/25' : 'bg-brand-green/5 border-brand-green/20'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${crisisMode ? 'bg-red-500 animate-pulse' : 'bg-brand-green'}`} />
                      {crisisMode ? (
                        <span className="text-red-400">🔴 危机模式 — S5危机策略</span>
                      ) : (
                        <span className="text-brand-green">🟢 正常模式 — Trend+SMC策略</span>
                      )}
                    </span>
                    {crisisInfo?.score != null && (
                      <span className="text-gray-500 font-mono text-[9px]">评分 {crisisInfo.score}/100</span>
                    )}
                  </div>
                  {crisisMode && (
                    <p className="text-[8px] text-red-400/60 mt-1">FNG低+战争新闻 → 双向交易(趋势确认), FNG/FR/LS动态仓位, 3xATR止损</p>
                  )}
                </motion.div>
              )}

              {/* Per-Symbol Status Dashboard */}
              {managedRunning && Object.keys(perSymbolStatus).length > 0 && (
                <div className="bg-surface-3 rounded-xl border border-glass p-2.5">
                  <p className="text-[9px] text-gray-500 font-bold mb-1.5">📊 各币种状态</p>
                  <div className="space-y-1">
                    {Object.entries(perSymbolStatus).map(([sym, info]) => (
                      <div key={sym} className="flex items-center justify-between text-[9px]">
                        <span className="text-white font-bold w-12">{sym.replace('USDT','')}</span>
                        <span className={`px-1 py-0.5 rounded text-[8px] font-bold ${
                          info.direction === 'bullish' ? 'bg-brand-green/10 text-brand-green' :
                          info.direction === 'bearish' ? 'bg-red-500/10 text-red-400' : 'bg-gray-500/10 text-gray-400'
                        }`}>
                          {info.direction === 'bullish' ? '多' : info.direction === 'bearish' ? '空' : '平'}
                        </span>
                        <span className="text-gray-500 font-mono">{info.score || '—'}</span>
                        <span className={`text-[8px] px-1 rounded ${info.mode === 'crisis' ? 'bg-red-500/10 text-red-400' : 'bg-surface-2 text-gray-600'}`}>
                          {info.mode === 'crisis' ? '危机' : '正常'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Multi-symbol selection (multi mode) */}
              {managedMode === 'multi' && (
                <div>
                  <label className="text-[10px] text-gray-600 mb-1 block">🌐 监控币种</label>
                  <div className="flex flex-wrap gap-1">
                    {['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','DOGEUSDT','AVAXUSDT','LINKUSDT','ADAUSDT'].map(s => {
                      const checked = managedSymbols.includes(s)
                      const label = s.replace('USDT','')
                      return (
                        <button key={s}
                          onClick={() => {
                            if (managedRunning) return
                            setManagedSymbols(checked ? managedSymbols.filter(x => x !== s) : [...managedSymbols, s])
                          }}
                          disabled={managedRunning}
                          className={`px-2 py-1 rounded-md text-[9px] font-bold transition-all ${
                            checked ? 'bg-amber-500/15 text-amber-400 border border-amber-500/20'
                              : 'bg-surface-2 text-gray-600 border border-glass'
                          } ${managedRunning ? 'opacity-50' : ''}`}
                        >
                          {checked ? '☑' : '☐'} {label}
                        </button>
                      )
                    })}
                  </div>
                  <p className="text-[8px] text-gray-600 mt-1">深度分析每个币约2分钟，建议选核心关注的</p>
                </div>
              )}

              {/* Quick Cycle Frequency */}
              <div>
                <label className="text-[10px] text-gray-600 mb-1 block">⚡ 快速循环频率</label>
                <div className="flex items-center gap-1.5">
                  {[1, 3, 5, 15].map(m => (
                    <button key={m} onClick={() => setManagedFreqMins(m)} disabled={managedRunning}
                      className={`px-2 py-1.5 rounded-md text-[10px] font-bold transition-all ${
                        managedFreqMins === m ? 'bg-purple-500/15 text-purple-400 border border-purple-500/20'
                          : 'bg-surface-3 text-gray-600 border border-glass'
                      } ${managedRunning ? 'opacity-50' : ''}`}>
                      {m}分
                    </button>
                  ))}
                  <input type="number" min="1" max="120" value={managedFreqMins}
                    onChange={(e) => setManagedFreqMins(parseInt(e.target.value) || 5)}
                    disabled={managedRunning}
                    className="w-12 bg-surface-3 border border-glass rounded-lg px-1.5 py-1.5 text-[10px] text-white text-center" />
                  <span className="text-[9px] text-gray-600">分</span>
                </div>
              </div>

              {/* Quick Mode Selector */}
              <div>
                <label className="text-[10px] text-gray-600 mb-1 block">🧠 快速分析模式</label>
                <div className="flex bg-surface-3 rounded-lg p-0.5 border border-glass">
                  <button onClick={() => !managedRunning && setQuickMode('pure_tech')}
                    className={`flex-1 px-2 py-1.5 text-[10px] font-bold rounded-md transition-all ${
                      quickMode === 'pure_tech' ? 'bg-blue-500/15 text-blue-400' : 'text-gray-600'}`}>
                    📊 纯技术指标
                  </button>
                  <button onClick={() => !managedRunning && setQuickMode('tech_llm')}
                    className={`flex-1 px-2 py-1.5 text-[10px] font-bold rounded-md transition-all ${
                      quickMode === 'tech_llm' ? 'bg-purple-500/15 text-purple-400' : 'text-gray-600'}`}>
                    🤖 技术+LLM
                  </button>
                </div>
              </div>

              {/* Deep Cycle Frequency */}
              <div>
                <label className="text-[10px] text-gray-600 mb-1 block">🔬 深度循环（Agent圆桌）</label>
                <div className="flex items-center gap-1.5">
                  {[{ v: 0, l: '手动' }, { v: 10/60, l: '10分' }, { v: 0.5, l: '30分' }, { v: 1, l: '1时' }, { v: 2, l: '2时' }, { v: 4, l: '4时' }].map(opt => (
                    <button key={opt.v} onClick={() => setDeepFreqHours(opt.v)} disabled={managedRunning}
                      className={`px-2 py-1.5 rounded-md text-[10px] font-bold transition-all ${
                        deepFreqHours === opt.v ? 'bg-amber-500/15 text-amber-400 border border-amber-500/20'
                          : 'bg-surface-3 text-gray-600 border border-glass'
                      } ${managedRunning ? 'opacity-50' : ''}`}>
                      {opt.l}
                    </button>
                  ))}
                </div>
              </div>

              {/* Deep Bias Indicator */}
              {deepBias && (
                <div className={`rounded-lg px-3 py-2 border text-[10px] ${
                  deepBias.direction === 'bullish' ? 'bg-brand-green/5 border-brand-green/15 text-brand-green'
                  : deepBias.direction === 'bearish' ? 'bg-red-500/5 border-red-500/15 text-red-400'
                  : 'bg-gray-500/5 border-gray-500/15 text-gray-400'
                }`}>
                  <span className="font-bold">深度偏好: </span>
                  {deepBias.direction === 'bullish' ? '📈' : deepBias.direction === 'bearish' ? '📉' : '➡️'} {deepBias.direction} | {deepBias.score}/100 | {deepBias.leverage}x
                </div>
              )}

              {/* Manual Deep Analysis Button */}
              {managedRunning && (
                <button onClick={runDeepCycle}
                  className="w-full py-2 rounded-lg bg-amber-500/10 text-amber-400 text-[10px] font-bold border border-amber-500/15 hover:bg-amber-500/20 transition-all">
                  🔬 手动触发深度分析
                </button>
              )}

              {/* Mode & Exchange */}
              <div className="flex gap-2">
                <div className="flex bg-surface-3 rounded-lg p-0.5 border border-glass flex-1">
                  <button onClick={() => !managedRunning && setTradingMode('paper')}
                    className={`flex-1 px-3 py-1.5 text-[10px] font-bold rounded-md ${tradingMode === 'paper' ? 'bg-yellow-500/15 text-yellow-400' : 'text-gray-600'}`}>
                    📝 模拟盘
                  </button>
                  <button onClick={() => !managedRunning && setTradingMode('live')}
                    className={`flex-1 px-3 py-1.5 text-[10px] font-bold rounded-md ${tradingMode === 'live' ? 'bg-red-500/15 text-red-400' : 'text-gray-600'}`}>
                    🔴 实盘
                  </button>
                </div>
                <select value={selectedExchange} onChange={(e) => !managedRunning && setSelectedExchange(e.target.value)}
                  className="bg-surface-3 border border-glass rounded-lg px-2 py-1.5 text-[10px] text-white">
                  <option value="binance">Binance</option>
                  <option value="okx">OKX</option>
                  <option value="bybit">Bybit</option>
                  <option value="hyperliquid">Hyperliquid</option>
                </select>
              </div>

              {/* Start / Stop Button */}
              <motion.button onClick={toggleManaged}
                whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                className={`w-full py-3.5 rounded-xl text-sm font-bold transition-all ${
                  managedRunning
                    ? 'bg-gradient-to-r from-red-500 to-rose-500 text-white'
                    : 'bg-gradient-to-r from-purple-500 to-indigo-500 text-white'
                }`}
                style={{ boxShadow: managedRunning ? '0 4px 20px rgba(255,71,87,0.3)' : '0 4px 20px rgba(139,92,246,0.3)' }}>
                {managedRunning ? '🛑 停止 AI 托管' : '🚀 启动 AI 托管交易'}
              </motion.button>

              {/* Managed Report Button */}
              <motion.button onClick={fetchManagedReport}
                whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                className="w-full py-2 rounded-xl text-[11px] font-bold transition-all
                  bg-surface-3 text-gray-400 hover:text-white border border-glass hover:border-purple-500/30 mt-1">
                📋 查看托管报告
              </motion.button>

              {/* Report display */}
              {showReport && managedReport && (
                <div className="bg-purple-500/5 border border-purple-500/15 rounded-xl p-3 space-y-2 mt-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[10px] text-purple-400 font-bold">📊 托管报告</p>
                    <button onClick={() => setShowReport(false)} className="text-[9px] text-gray-600 hover:text-gray-400">✖</button>
                  </div>
                  <div className="grid grid-cols-3 gap-1.5 text-center text-[9px]">
                    <div className="bg-surface-3/50 rounded p-1.5">
                      <div className="text-gray-600">总轮数</div>
                      <div className="text-white font-bold">{managedReport.total_cycles || 0}</div>
                    </div>
                    <div className="bg-surface-3/50 rounded p-1.5">
                      <div className="text-gray-600">交易执行</div>
                      <div className="text-white font-bold">{managedReport.trades_executed || 0}</div>
                    </div>
                    <div className="bg-surface-3/50 rounded p-1.5">
                      <div className="text-gray-600">总 PnL</div>
                      <div className={`font-bold ${(managedReport.total_pnl || 0) >= 0 ? 'text-brand-green' : 'text-red-400'}`}>
                        {(managedReport.total_pnl || 0) >= 0 ? '+' : ''}${(managedReport.total_pnl || 0).toFixed(2)}
                      </div>
                    </div>
                  </div>
                  {managedReport.symbols && (
                    <div className="text-[8px] text-gray-500">
                      币种: {(managedReport.symbols || []).join(', ')}
                    </div>
                  )}
                </div>
              )}

              {/* Human Intervention */}
              {managedRunning && (
                <div className="bg-orange-500/5 border border-orange-500/15 rounded-xl p-3 space-y-2">
                  <p className="text-[10px] text-orange-400 font-bold">🖐️ 人工干预</p>
                  <p className="text-[9px] text-orange-400/60">覆盖 AI 下一笔方向</p>
                  <div className="flex gap-2">
                    <button onClick={() => humanOverride('buy')}
                      className="flex-1 py-2 rounded-lg bg-brand-green/15 text-brand-green text-[10px] font-bold border border-brand-green/20 hover:bg-brand-green/25">
                      📈 改做多
                    </button>
                    <button onClick={() => humanOverride('sell')}
                      className="flex-1 py-2 rounded-lg bg-red-500/15 text-red-400 text-[10px] font-bold border border-red-500/20 hover:bg-red-500/25">
                      📉 改做空
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Right: Strategy Dashboard — extracted components */}
            <div className="col-span-12 lg:col-span-8 space-y-3">
              <HybridAIDashboard
                managedStrategy={managedStrategy} managedSymbols={managedSymbols}
                crisisMode={crisisMode} managedRunning={managedRunning}
                nextTradeCountdown={nextTradeCountdown} formatCountdown={formatCountdown}
                executeRangeStrategy={executeRangeStrategy}
              />

              <TradingStats riskStats={riskStats} onReset={async () => {
                if (!window.confirm('确定清除所有交易统计和历史记录？')) return
                try {
                  await fetch(`${API_BASE}/api/positions/reset`, { method: 'POST' })
                  setPositions([]); setOrders([]); setManagedLogs([])
                  setBalance(initialBalanceRef.current); setManagedStrategy(null); setDeepBias(null)
                  fetchPositions(); fetchTradeHistory()
                } catch (e) { console.error(e) }
              }} />

              <ExecutionLog logs={managedLogs} onClear={() => { setManagedLogs([]); localStorage.removeItem('managedLogs') }} />
            </div>
          </div>

          {/* Positions & Orders — extracted component */}
          <PositionsTable
            positions={positions} orders={orders} totalPnl={totalPnl}
            onClosePosition={closePosition}
            onReset={async () => {
              if (!window.confirm('确定清除所有持仓和交易记录？此操作不可撤销。')) return
              try {
                const res = await fetch(`${API_BASE}/api/positions/reset`, { method: 'POST' })
                const data = await res.json()
                if (data.success) {
                  setPositions([]); setOrders([]); setManagedLogs([])
                  setBalance(initialBalanceRef.current); setManagedStrategy(null); setDeepBias(null)
                  fetchPositions()
                }
              } catch (e) { console.error(e) }
            }}
            tradeHistory={tradeHistory}
          />
        </div>
      )}

      {/* =================== CHAT TAB =================== */}
      {activeTab === 'chat' && (
        <div className="p-5 flex flex-col" style={{ minHeight: 300 }}>
          <div className="flex-1 overflow-y-auto space-y-2 mb-3" style={{ maxHeight: 250 }}>
            {chatMessages.length === 0 && (
              <div className="text-center py-8 text-gray-700 text-xs">
                <p className="text-3xl mb-3">🤖</p>
                <p>与 AI 讨论你的交易策略</p>
                <p className="text-[10px] text-gray-600 mt-1">例如：调整止盈止损 / 修改频率 / 讨论仓位管理</p>
              </div>
            )}
            {chatMessages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-xl px-3 py-2 text-xs leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-brand-green/10 text-brand-green border border-brand-green/20'
                    : 'bg-surface-3 text-gray-300 border border-glass'
                }`}>
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
            ))}
            {chatLoading && <div className="text-xs text-gray-600">🤖 AI 思考中...</div>}
          </div>
          <div className="flex gap-2">
            <input value={chatInput} onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendChat()}
              placeholder="讨论交易策略..."
              className="flex-1 bg-surface-3 border border-glass rounded-lg px-3 py-2 text-sm text-white placeholder-gray-700" />
            <button onClick={sendChat} disabled={chatLoading}
              className="px-4 py-2 rounded-lg bg-purple-500/20 text-purple-400 text-xs font-bold border border-purple-500/20 hover:bg-purple-500/30">
              发送
            </button>
          </div>
        </div>
      )}

      {/* =================== TRADE TAB =================== */}
      {activeTab === 'trade' && (
        <div className="grid grid-cols-12 gap-4 p-5">
          {/* Left: Order Form */}
          <div className="col-span-12 lg:col-span-4 space-y-3">
            {/* Mode & Exchange */}
            <div className="flex gap-2">
              <div className="flex bg-surface-3 rounded-lg p-0.5 border border-glass flex-1">
                <button onClick={() => setTradingMode('paper')}
                  className={`flex-1 px-3 py-1.5 text-[10px] font-bold rounded-md transition-all ${tradingMode === 'paper' ? 'bg-yellow-500/15 text-yellow-400' : 'text-gray-600'}`}>
                  📝 模拟盘
                </button>
                <button onClick={() => setTradingMode('live')}
                  className={`flex-1 px-3 py-1.5 text-[10px] font-bold rounded-md transition-all ${tradingMode === 'live' ? 'bg-red-500/15 text-red-400' : 'text-gray-600'}`}>
                  🔴 实盘
                </button>
              </div>
              <select value={selectedExchange} onChange={(e) => setSelectedExchange(e.target.value)}
                className="bg-surface-3 border border-glass rounded-lg px-2 py-1.5 text-[10px] text-white">
                <option value="binance">Binance</option>
                <option value="okx">OKX</option>
                <option value="bybit">Bybit</option>
                <option value="hyperliquid">Hyperliquid</option>
              </select>
            </div>

            {/* Direction */}
            <div className="flex gap-2">
              <button onClick={() => setSide('buy')}
                className={`flex-1 py-2.5 rounded-xl text-xs font-bold transition-all ${side === 'buy' ? 'bg-brand-green/20 text-brand-green border border-brand-green/30' : 'bg-surface-3 text-gray-600 border border-glass'}`}>
                📈 做多 / Long
              </button>
              <button onClick={() => setSide('sell')}
                className={`flex-1 py-2.5 rounded-xl text-xs font-bold transition-all ${side === 'sell' ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-surface-3 text-gray-600 border border-glass'}`}>
                📉 做空 / Short
              </button>
            </div>

            {/* Amount & Leverage */}
            <div className="space-y-2">
              <div>
                <label className="text-[10px] text-gray-600 mb-1 block">📐 仓位大小</label>
                <div className="flex bg-surface-3 rounded-lg p-0.5 border border-glass mb-1.5">
                  {[
                    { key: 'usdt', label: 'USDT 金额' },
                    { key: 'pct', label: '% 余额' },
                    { key: 'qty', label: '币数量' },
                  ].map(m => (
                    <button key={m.key} onClick={() => setSizingMode(m.key)}
                      className={`flex-1 px-2 py-1.5 text-[9px] font-bold rounded-md transition-all ${
                        sizingMode === m.key ? 'bg-cyan-500/15 text-cyan-400' : 'text-gray-600'
                      }`}>
                      {m.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <input type="number" step={sizingMode === 'pct' ? '1' : sizingMode === 'usdt' ? '10' : '0.001'}
                    value={sizingValue}
                    onChange={(e) => setSizingValue(e.target.value)}
                    className="flex-1 bg-surface-3 border border-glass rounded-lg px-3 py-2 text-sm text-white font-mono" />
                  <span className="text-[10px] text-gray-500 w-16 text-right">
                    {sizingMode === 'usdt' ? 'USDT' : sizingMode === 'pct' ? '% 余额' : symbol.replace('USDT','')}
                  </span>
                </div>
                {/* Quick percentage buttons */}
                {sizingMode === 'pct' && (
                  <div className="flex gap-1 mt-1">
                    {[10, 25, 50, 75, 100].map(p => (
                      <button key={p} onClick={() => setSizingValue(String(p))}
                        className={`flex-1 py-1 rounded text-[9px] font-bold transition-all ${
                          sizingValue === String(p) ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/20' : 'bg-surface-2 text-gray-600 border border-glass'
                        }`}>
                        {p}%
                      </button>
                    ))}
                  </div>
                )}
                {sizingMode === 'usdt' && (
                  <div className="flex gap-1 mt-1">
                    {[50, 100, 200, 500, 1000].map(v => (
                      <button key={v} onClick={() => setSizingValue(String(v))}
                        className={`flex-1 py-1 rounded text-[9px] font-bold transition-all ${
                          sizingValue === String(v) ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/20' : 'bg-surface-2 text-gray-600 border border-glass'
                        }`}>
                        ${v}
                      </button>
                    ))}
                  </div>
                )}
                {/* Live calculation preview */}
                {(() => {
                  const qty = getActualAmount()
                  const price = currentPrice || finalDecision?.entry_price || 0
                  const lev = parseInt(leverage) || 1
                  const posValue = qty * price
                  const margin = posValue / lev
                  if (qty <= 0 || price <= 0) return null
                  return (
                    <div className="mt-1.5 grid grid-cols-3 gap-1 text-center bg-surface-2 rounded-md p-1.5 border border-glass/50">
                      <div>
                        <p className="text-[7px] text-gray-600">数量</p>
                        <p className="text-[9px] font-bold text-white font-mono">{qty < 0.01 ? qty.toFixed(6) : qty.toFixed(4)}</p>
                      </div>
                      <div>
                        <p className="text-[7px] text-gray-600">仓位价值</p>
                        <p className="text-[9px] font-bold text-cyan-400 font-mono">${posValue.toFixed(2)}</p>
                      </div>
                      <div>
                        <p className="text-[7px] text-gray-600">保证金</p>
                        <p className="text-[9px] font-bold text-yellow-400 font-mono">${margin.toFixed(2)}</p>
                      </div>
                    </div>
                  )
                })()}
              </div>
              <div>
                <label className="text-[10px] text-gray-600 mb-1 block">杠杆倍数</label>
                <div className="flex items-center gap-1">
                  <input type="range" min="1" max="50" value={leverage} onChange={(e) => setLeverage(e.target.value)} className="flex-1 h-1 accent-brand-green" />
                  <span className="text-sm font-bold text-yellow-400 w-10 text-right">{leverage}x</span>
                </div>
              </div>
            </div>

            {/* TP / SL */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-brand-green mb-1 block">止盈价 (TP)</label>
                <input type="number" step="0.01" value={tpPrice} onChange={(e) => setTpPrice(e.target.value)}
                  placeholder={finalDecision?.exit_price ? `AI: $${finalDecision.exit_price}` : '输入止盈价'}
                  className="w-full bg-surface-3 border border-brand-green/20 rounded-lg px-3 py-2 text-sm text-brand-green placeholder-gray-700" />
              </div>
              <div>
                <label className="text-[10px] text-red-400 mb-1 block">止损价 (SL)</label>
                <input type="number" step="0.01" value={slPrice} onChange={(e) => setSlPrice(e.target.value)}
                  placeholder={finalDecision?.stop_loss ? `AI: $${finalDecision.stop_loss}` : '输入止损价'}
                  className="w-full bg-surface-3 border border-red-500/20 rounded-lg px-3 py-2 text-sm text-red-400 placeholder-gray-700" />
              </div>
            </div>

            {/* AI Recommendation */}
            {finalDecision && (
              <div className="bg-surface-3 rounded-lg p-2.5 border border-glass">
                <p className="text-[10px] text-gray-600 mb-1.5">🤖 AI推荐</p>
                <div className="grid grid-cols-4 gap-1.5 text-center">
                  <div><p className="text-[9px] text-gray-600">入场</p><p className="text-[10px] font-bold text-white">${finalDecision.entry_price?.toLocaleString() || '—'}</p></div>
                  <div><p className="text-[9px] text-gray-600">止盈</p><p className="text-[10px] font-bold text-brand-green">${finalDecision.exit_price?.toLocaleString() || '—'}</p></div>
                  <div><p className="text-[9px] text-gray-600">止损</p><p className="text-[10px] font-bold text-red-400">${finalDecision.stop_loss?.toLocaleString() || '—'}</p></div>
                  <div><p className="text-[9px] text-gray-600">杠杆</p><p className="text-[10px] font-bold text-yellow-400">{finalDecision.leverage || '—'}x</p></div>
                </div>
              </div>
            )}

            {/* Execute */}
            <motion.button onClick={executeOrder} disabled={executing}
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
              className={`w-full py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-40 ${
                side === 'buy' ? 'bg-gradient-to-r from-brand-green to-emerald-400 text-black' : 'bg-gradient-to-r from-red-500 to-rose-400 text-white'
              }`}
              style={{ boxShadow: side === 'buy' ? '0 4px 15px rgba(0,232,135,0.25)' : '0 4px 15px rgba(255,71,87,0.25)' }}>
              {executing ? '⏳ 执行中...' : `${side === 'buy' ? '📈 开多' : '📉 开空'} ${symbol} ${leverage}x`}
            </motion.button>

            {tradingMode === 'live' && <p className="text-[9px] text-red-400 text-center">⚠️ 实盘交易模式 — 需要先在设置中配置交易所 API</p>}

            {/* One-click AI Trade */}
            <motion.button onClick={executeAutoTrade} disabled={autoTradeLoading || executing}
              whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
              className="w-full py-2.5 rounded-xl text-sm font-bold transition-all disabled:opacity-40
                bg-gradient-to-r from-purple-500 to-indigo-500 text-white mt-2"
              style={{ boxShadow: '0 4px 15px rgba(139,92,246,0.25)' }}>
              {autoTradeLoading ? '🔄 分析+下单中...' : `🎯 单次AI诊断并下单 ${symbol}`}
            </motion.button>
            <p className="text-[9px] text-gray-600 text-center mt-1">单次立刻执行：AI分析方向 → 计算仓位 → 下单 (非连续托管)</p>
          </div>

          {/* Right: Positions & Orders */}
          <div className="col-span-12 lg:col-span-8 space-y-3">
            {/* Positions */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-[11px] font-bold text-gray-400">📋 当前持仓 <span className="text-gray-600">({positions.length})</span></h4>
                {positionStats && (
                  <div className="flex items-center gap-3 text-[9px]">
                    <span className={`font-bold ${(positionStats.total_pnl || 0) >= 0 ? 'text-brand-green' : 'text-red-400'}`}>
                      PnL: {(positionStats.total_pnl || 0) >= 0 ? '+' : ''}${(positionStats.total_pnl || 0).toFixed(2)}
                    </span>
                    <span className="text-gray-500">胜率: {positionStats.win_rate || 0}%</span>
                    <span className="text-gray-500">总交易: {positionStats.total_trades || 0}</span>
                  </div>
                )}
              </div>
              {positions.length === 0 ? (
                <div className="text-center py-6 text-gray-700 text-xs">暂无持仓</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="text-gray-600 border-b border-glass">
                        <th className="text-left py-2 px-1.5">来源</th><th className="text-left py-2 px-1.5">交易对</th><th className="text-left py-2 px-1.5">方向</th>
                        <th className="text-right py-2 px-1.5">杠杆</th><th className="text-right py-2 px-1.5">入场价</th>
                        <th className="text-right py-2 px-1.5">现价</th>
                        <th className="text-right py-2 px-1.5">本金</th><th className="text-right py-2 px-1.5">保证金</th>
                        <th className="text-right py-2 px-1.5">PnL</th>
                        <th className="text-right py-2 px-1.5">ROE%</th><th className="text-center py-2 px-1.5">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.map(pos => {
                        const posValue = (pos.entry_price || 0) * (pos.original_amount || pos.amount || 0)
                        const margin = pos.margin_used || (posValue / (pos.leverage || 1))
                        return (
                        <tr key={pos.id} className="border-b border-glass/50 hover:bg-white/[0.01]">
                          <td className="py-2 px-1.5"><span className={`text-[8px] px-1 py-0.5 rounded font-bold ${pos.source === 'ai' ? 'bg-purple-500/15 text-purple-400' : 'bg-blue-500/15 text-blue-400'}`}>{pos.source === 'ai' ? '🤖' : '🖱️'}</span></td>
                          <td className="py-2 px-1.5 text-white font-semibold">{pos.symbol}</td>
                          <td className="py-2 px-1.5"><span className={`px-1 py-0.5 rounded text-[9px] font-bold ${pos.side === 'buy' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>{pos.side === 'buy' ? '多' : '空'}</span></td>
                          <td className="py-2 px-1.5 text-right text-yellow-400">{pos.leverage}x</td>
                          <td className="py-2 px-1.5 text-right text-gray-300 font-mono">${pos.entry_price?.toFixed(2)}</td>
                          <td className="py-2 px-1.5 text-right text-white font-mono">${pos.current_price?.toFixed(2)}</td>
                          <td className="py-2 px-1.5 text-right text-purple-400 font-mono">{pos.account_balance ? `$${pos.account_balance.toLocaleString()}` : '—'}</td>
                          <td className="py-2 px-1.5 text-right text-yellow-400 font-mono">${margin.toFixed(0)}</td>
                          <td className={`py-2 px-1.5 text-right font-bold font-mono ${pos.pnl >= 0 ? 'text-bull' : 'text-bear'}`}>{pos.pnl >= 0 ? '+' : ''}{pos.pnl?.toFixed(2)}</td>
                          <td className={`py-2 px-1.5 text-right font-mono ${pos.roe >= 0 ? 'text-bull' : 'text-bear'}`}>{pos.roe >= 0 ? '+' : ''}{pos.roe?.toFixed(2)}%</td>
                          <td className="py-2 px-1.5 text-center">
                            <button onClick={() => closePosition(pos)} className="px-2 py-1 rounded bg-red-500/10 text-red-400 text-[9px] font-bold hover:bg-red-500/20">平仓</button>
                          </td>
                        </tr>
                      )})}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Orders */}
            <div>
              <h4 className="text-[11px] font-bold text-gray-400 mb-2">📜 交易记录 <span className="text-gray-600">({orders.length})</span></h4>
              {orders.length === 0 ? (
                <div className="text-center py-4 text-gray-700 text-xs">暂无交易记录</div>
              ) : (
                <div className="space-y-1 max-h-[150px] overflow-y-auto">
                  {orders.slice(0, 20).map(order => (
                    <div key={order.id} className="flex items-center justify-between bg-surface-3 rounded-lg px-3 py-2 border border-glass">
                      <div className="flex items-center gap-2">
                        <span className={`text-[8px] px-1.5 py-0.5 rounded font-bold ${order.source === 'ai' ? 'bg-purple-500/15 text-purple-400' : 'bg-blue-500/15 text-blue-400'}`}>
                          {order.source === 'ai' ? '🤖' : '🖱️'}
                        </span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${order.side === 'buy' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>
                          {order.side === 'buy' ? '买入' : '卖出'}{order.label ? ` · ${order.label}` : ''}
                        </span>
                        <span className="text-[10px] text-white font-semibold">{order.symbol}</span>
                        <span className="text-[9px] text-yellow-400">{order.leverage}x</span>
                        {order.positionValue > 0 && (
                          <span className="text-[8px] bg-cyan-500/10 text-cyan-400 px-1.5 py-0.5 rounded font-mono">
                            仓位 ${order.positionValue?.toFixed(0)}
                          </span>
                        )}
                        {order.marginUsed > 0 && (
                          <span className="text-[8px] bg-yellow-500/10 text-yellow-400 px-1.5 py-0.5 rounded font-mono">
                            保证金 ${order.marginUsed?.toFixed(0)}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] text-gray-400 font-mono">${order.price?.toLocaleString()}</span>
                        <span className={`text-[8px] px-1 py-0.5 rounded ${order.mode === 'paper' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-red-500/10 text-red-400'}`}>
                          {order.mode === 'paper' ? '模拟' : '实盘'}
                        </span>
                        <span className="text-[9px] text-gray-600 font-mono">{order.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* ===== TRADE HISTORY & PnL DASHBOARD ===== */}
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <button onClick={() => setShowHistory(!showHistory)} className="flex items-center gap-2 text-[11px] font-bold text-gray-400 hover:text-white transition-colors">
                  <span>{showHistory ? '▼' : '▶'}</span>
                  <span>📊 历史交易 & PnL 面板</span>
                  <span className="text-gray-600">({tradeHistory.count || 0}笔)</span>
                  {tradeHistory.stats?.total_pnl !== undefined && (
                    <span className={`ml-2 font-mono ${tradeHistory.stats.total_pnl >= 0 ? 'text-bull' : 'text-bear'}`}>
                      {tradeHistory.stats.total_pnl >= 0 ? '+' : ''}${tradeHistory.stats.total_pnl?.toFixed(2)}
                    </span>
                  )}
                </button>
                <button onClick={fetchTradeHistory} className="text-[9px] text-gray-600 hover:text-gray-400 transition-colors">🔄 刷新</button>
                <button onClick={() => {
                  console.log('[ClearHistory] Sending request...')
                  fetch(`${API_BASE}/api/positions/reset`, { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                      console.log('[ClearHistory] Response:', data)
                      if (data.success) {
                        setPositions([]); setOrders([]); setManagedLogs([])
                        setBalance(initialBalanceRef.current); setManagedStrategy(null); setDeepBias(null)
                        setTradeHistory({ trades: [], stats: {}, daily_summary: [], equity_curve: [] })
                        fetchPositions(); fetchTradeHistory()
                      }
                    })
                    .catch(e => console.error('[ClearHistory] Error:', e))
                }}
                  className="px-2 py-1 rounded-md text-[8px] font-bold bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all">
                  🗑️ 清空记录
                </button>
              </div>

              {showHistory && (
                <div className="bg-surface-2 rounded-xl border border-glass p-3 space-y-3">
                  {/* Time filter + view switcher */}
                  <div className="flex items-center justify-between">
                    <div className="flex gap-1">
                      {[{ k: 'today', l: '今日' }, { k: '7d', l: '7天' }, { k: '30d', l: '30天' }, { k: 'all', l: '全部' }].map(f => (
                        <button key={f.k} onClick={() => setHistoryFilter(f.k)}
                          className={`px-2 py-1 rounded text-[9px] font-bold transition-all ${historyFilter === f.k ? 'bg-brand-blue/20 text-brand-blue' : 'bg-surface-3 text-gray-500 hover:text-gray-300'}`}>
                          {f.l}
                        </button>
                      ))}
                    </div>
                    <div className="flex gap-1">
                      {[{ k: 'stats', l: '📈 总览' }, { k: 'daily', l: '📅 按日' }, { k: 'trades', l: '📋 逐笔' }].map(v => (
                        <button key={v.k} onClick={() => setHistoryView(v.k)}
                          className={`px-2 py-1 rounded text-[9px] font-bold transition-all ${historyView === v.k ? 'bg-white/10 text-white' : 'bg-surface-3 text-gray-500 hover:text-gray-300'}`}>
                          {v.l}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Stats Overview */}
                  {historyView === 'stats' && (
                    <div className="space-y-3">
                      {/* Stats cards */}
                      <div className="grid grid-cols-4 gap-2">
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">总盈亏</div>
                          <div className={`text-sm font-bold font-mono ${(tradeHistory.stats?.total_pnl || 0) >= 0 ? 'text-bull' : 'text-bear'}`}>
                            {(tradeHistory.stats?.total_pnl || 0) >= 0 ? '+' : ''}${(tradeHistory.stats?.total_pnl || 0).toFixed(2)}
                          </div>
                        </div>
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">胜率</div>
                          <div className={`text-sm font-bold ${(tradeHistory.stats?.win_rate || 0) >= 50 ? 'text-bull' : 'text-bear'}`}>
                            {(tradeHistory.stats?.win_rate || 0).toFixed(1)}%
                          </div>
                          <div className="text-[8px] text-gray-600">{tradeHistory.stats?.wins || 0}W / {tradeHistory.stats?.losses || 0}L</div>
                        </div>
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">盈亏因子</div>
                          <div className={`text-sm font-bold ${(tradeHistory.stats?.profit_factor || 0) >= 1.5 ? 'text-bull' : (tradeHistory.stats?.profit_factor || 0) >= 1 ? 'text-yellow-400' : 'text-bear'}`}>
                            {(tradeHistory.stats?.profit_factor || 0).toFixed(2)}
                          </div>
                        </div>
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">总交易</div>
                          <div className="text-sm font-bold text-white">{tradeHistory.stats?.total_trades || 0}</div>
                        </div>
                      </div>
                      {/* Second row */}
                      <div className="grid grid-cols-4 gap-2">
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">平均盈亏</div>
                          <div className={`text-xs font-bold font-mono ${(tradeHistory.stats?.avg_pnl || 0) >= 0 ? 'text-bull' : 'text-bear'}`}>
                            ${(tradeHistory.stats?.avg_pnl || 0).toFixed(2)}
                          </div>
                        </div>
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">平均盈利</div>
                          <div className="text-xs font-bold font-mono text-bull">+${(tradeHistory.stats?.avg_win || 0).toFixed(2)}</div>
                        </div>
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">平均亏损</div>
                          <div className="text-xs font-bold font-mono text-bear">-${(tradeHistory.stats?.avg_loss || 0).toFixed(2)}</div>
                        </div>
                        <div className="bg-surface-3 rounded-lg p-2 text-center border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">最佳 / 最差</div>
                          <div className="text-[9px] font-mono">
                            <span className="text-bull">+${(tradeHistory.stats?.best_trade || 0).toFixed(2)}</span>
                            <span className="text-gray-600"> / </span>
                            <span className="text-bear">${(tradeHistory.stats?.worst_trade || 0).toFixed(2)}</span>
                          </div>
                        </div>
                      </div>
                      {/* Equity curve mini */}
                      {tradeHistory.equity_curve?.length > 1 && (
                        <div className="bg-surface-3 rounded-lg p-2 border border-glass">
                          <div className="text-[9px] text-gray-500 mb-1">📈 权益曲线</div>
                          <div className="flex items-end gap-[2px] h-[40px]">
                            {(() => {
                              const curve = tradeHistory.equity_curve
                              const min = Math.min(...curve)
                              const max = Math.max(...curve)
                              const range = max - min || 1
                              return curve.map((v, i) => (
                                <div key={i} className="flex-1 rounded-t-sm" style={{
                                  height: `${Math.max(4, ((v - min) / range) * 36)}px`,
                                  backgroundColor: v >= 0 ? 'rgba(16,185,129,0.6)' : 'rgba(239,68,68,0.6)',
                                }} />
                              ))
                            })()}
                          </div>
                          <div className="flex justify-between mt-1 text-[8px] text-gray-600 font-mono">
                            <span>$0</span>
                            <span>${tradeHistory.equity_curve[tradeHistory.equity_curve.length - 1]?.toFixed(2)}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Daily PnL View */}
                  {historyView === 'daily' && (
                    <div className="space-y-1 max-h-[200px] overflow-y-auto">
                      {(!tradeHistory.daily_summary || tradeHistory.daily_summary.length === 0) ? (
                        <div className="text-center py-4 text-gray-700 text-xs">暂无交易历史</div>
                      ) : tradeHistory.daily_summary.map(day => (
                        <div key={day.date} className="flex items-center justify-between bg-surface-3 rounded-lg px-3 py-2 border border-glass hover:bg-white/[0.02] transition-colors">
                          <div className="flex items-center gap-3">
                            <span className="text-[10px] text-gray-400 font-mono w-[70px]">{day.date}</span>
                            <span className="text-[9px] text-gray-500">{day.trades}笔</span>
                            <span className="text-[9px] text-gray-600">{day.wins}W/{day.losses}L ({day.win_rate}%)</span>
                          </div>
                          <div className={`text-[11px] font-bold font-mono ${day.pnl >= 0 ? 'text-bull' : 'text-bear'}`}>
                            {day.pnl >= 0 ? '+' : ''}${day.pnl.toFixed(2)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Per-Trade Detail View */}
                  {historyView === 'trades' && (
                    <div className="max-h-[250px] overflow-y-auto">
                      {(!tradeHistory.trades || tradeHistory.trades.length === 0) ? (
                        <div className="text-center py-4 text-gray-700 text-xs">暂无交易历史</div>
                      ) : (
                        <table className="w-full text-[9px]">
                          <thead>
                            <tr className="text-gray-600 border-b border-glass sticky top-0 bg-surface-2">
                              <th className="text-left py-1.5 px-1">时间</th>
                              <th className="text-left py-1.5 px-1">交易对</th>
                              <th className="text-left py-1.5 px-1">方向</th>
                              <th className="text-right py-1.5 px-1">杠杆</th>
                              <th className="text-right py-1.5 px-1">入场</th>
                              <th className="text-right py-1.5 px-1">平仓</th>
                              <th className="text-right py-1.5 px-1">本金</th>
                              <th className="text-right py-1.5 px-1">保证金</th>
                              <th className="text-right py-1.5 px-1">PnL</th>
                              <th className="text-right py-1.5 px-1">ROE%</th>
                              <th className="text-center py-1.5 px-1">原因</th>
                            </tr>
                          </thead>
                          <tbody>
                            {tradeHistory.trades.map((t, i) => (
                              <tr key={t.id || i} className="border-b border-glass/30 hover:bg-white/[0.01]">
                                <td className="py-1.5 px-1 text-gray-500 font-mono">{t.closed_at?.slice(5, 16)?.replace('T', ' ')}</td>
                                <td className="py-1.5 px-1 text-white font-semibold">{t.symbol}</td>
                                <td className="py-1.5 px-1">
                                  <span className={`px-1 py-0.5 rounded text-[8px] font-bold ${t.side === 'buy' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>
                                    {t.side === 'buy' ? '多' : '空'}
                                  </span>
                                </td>
                                <td className="py-1.5 px-1 text-right text-yellow-400">{t.leverage}x</td>
                                <td className="py-1.5 px-1 text-right text-gray-400 font-mono">${t.entry_price?.toFixed(1)}</td>
                                <td className="py-1.5 px-1 text-right text-gray-300 font-mono">${t.close_price?.toFixed(1)}</td>
                                <td className="py-1.5 px-1 text-right text-purple-400 font-mono">{t.account_balance ? `$${t.account_balance.toLocaleString()}` : '—'}</td>
                                <td className="py-1.5 px-1 text-right text-yellow-400 font-mono">${t.margin_used?.toFixed(0) || '—'}</td>
                                <td className={`py-1.5 px-1 text-right font-bold font-mono ${t.pnl >= 0 ? 'text-bull' : 'text-bear'}`}>
                                  {t.pnl >= 0 ? '+' : ''}${t.pnl?.toFixed(2)}
                                </td>
                                <td className={`py-1.5 px-1 text-right font-mono ${t.roe >= 0 ? 'text-bull' : 'text-bear'}`}>
                                  {t.roe >= 0 ? '+' : ''}{t.roe?.toFixed(1)}%
                                </td>
                                <td className="py-1.5 px-1 text-center">
                                  <span className={`text-[8px] px-1 py-0.5 rounded ${
                                    t.close_reason === 'tp' ? 'bg-green-500/10 text-green-400' :
                                    t.close_reason === 'sl' ? 'bg-red-500/10 text-red-400' :
                                    t.close_reason === 'trailing' ? 'bg-blue-500/10 text-blue-400' :
                                    'bg-gray-500/10 text-gray-400'
                                  }`}>{t.close_reason === 'tp' ? '止盈' : t.close_reason === 'sl' ? '止损' : t.close_reason === 'trailing' ? '移动止损' : '手动'}</span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* =================== EVOLUTION TAB =================== */}
      {activeTab === 'evolution' && (
        <div className="p-5 space-y-4">
          {/* Evolution Stats Header */}
          <div className="bg-gradient-to-r from-amber-500/5 to-surface-2/80 rounded-xl border border-amber-500/20 p-3">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-[10px] font-bold text-white flex items-center gap-2">
                🧠 AI 自我进化系统
                <span className="text-[8px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 font-mono">
                  {reflections.length} 条反思 · {evolutionRules.length} 条规则
                </span>
              </h4>
              <button onClick={fetchEvolutionData} className="text-[8px] text-gray-500 hover:text-amber-400 transition">
                🔄 刷新
              </button>
            </div>
            {evoStats && (
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-surface-3/50 rounded-lg p-2">
                  <div className="text-[9px] text-gray-500">总规则</div>
                  <div className="text-sm font-bold text-white">{evoStats.total_rules}</div>
                </div>
                <div className="bg-surface-3/50 rounded-lg p-2">
                  <div className="text-[9px] text-gray-500">活跃规则</div>
                  <div className="text-sm font-bold text-amber-400">{evoStats.active_rules}</div>
                </div>
                <div className="bg-surface-3/50 rounded-lg p-2">
                  <div className="text-[9px] text-gray-500">平均信心</div>
                  <div className="text-sm font-bold text-cyan-400">{((evoStats.avg_confidence || 0) * 100).toFixed(0)}%</div>
                </div>
              </div>
            )}
          </div>

          {/* Active Evolution Rules */}
          <div>
            {/* Evolution Summary (from /api/reflections/summary) */}
            {evoSummary && (
              <div className="bg-cyan-500/5 border border-cyan-500/15 rounded-xl p-3 mb-3">
                <h5 className="text-[10px] font-bold text-cyan-400 mb-1.5">📝 进化摘要</h5>
                <div className="grid grid-cols-2 gap-1.5 text-[9px]">
                  {evoSummary.most_improved && (
                    <div className="bg-surface-3/50 rounded p-1.5">
                      <span className="text-gray-500">最大进步:</span>{' '}
                      <span className="text-brand-green font-bold">{evoSummary.most_improved}</span>
                    </div>
                  )}
                  {evoSummary.biggest_weakness && (
                    <div className="bg-surface-3/50 rounded p-1.5">
                      <span className="text-gray-500">最大弱点:</span>{' '}
                      <span className="text-red-400 font-bold">{evoSummary.biggest_weakness}</span>
                    </div>
                  )}
                </div>
                {evoSummary.key_learnings && (
                  <p className="text-[8px] text-gray-500 mt-1.5">{evoSummary.key_learnings}</p>
                )}
              </div>
            )}
            <h5 className="text-[10px] font-bold text-gray-400 mb-2">⚡ 活跃进化规则</h5>
            {evolutionRules.length === 0 ? (
              <div className="text-center py-4 text-gray-700 text-[10px]">
                暂无进化规则 — 系统会从交易反思中自动提取
              </div>
            ) : (
              <div className="space-y-1.5">
                {evolutionRules.map((rule, i) => (
                  <div key={rule.id || i} className="bg-surface-3/50 rounded-lg border border-glass p-2.5">
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] font-bold text-white">{rule.name}</span>
                        <span className={`text-[7px] px-1 py-0.5 rounded font-bold ${
                          rule.category === 'discipline' ? 'bg-red-500/10 text-red-400' :
                          rule.category === 'sentiment_trap' ? 'bg-purple-500/10 text-purple-400' :
                          rule.category === 'market_regime' ? 'bg-blue-500/10 text-blue-400' :
                          rule.category === 'structure' ? 'bg-cyan-500/10 text-cyan-400' :
                          rule.category === 'position' ? 'bg-yellow-500/10 text-yellow-400' :
                          'bg-gray-500/10 text-gray-400'
                        }`}>{rule.category}</span>
                      </div>
                      <span className={`text-[9px] font-mono font-bold ${
                        rule.base_adjustment < 0 ? 'text-red-400' : 'text-green-400'
                      }`}>
                        {rule.base_adjustment > 0 ? '+' : ''}{(rule.base_adjustment * rule.confidence).toFixed(1)}分
                      </span>
                    </div>
                    {/* Confidence bar */}
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all ${
                          rule.confidence >= 0.7 ? 'bg-green-500' :
                          rule.confidence >= 0.4 ? 'bg-amber-500' : 'bg-red-500'
                        }`} style={{ width: `${(rule.confidence * 100)}%` }} />
                      </div>
                      <span className="text-[8px] text-gray-500 font-mono w-8 text-right">
                        {(rule.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="text-[8px] text-gray-600 mt-1">
                      条件: {rule.condition} · 应用{rule.times_applied}次 · 验证{rule.times_validated}次
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Trade Reflections */}
          <div>
            <h5 className="text-[10px] font-bold text-gray-400 mb-2">📝 交易反思记录</h5>
            {reflections.length === 0 ? (
              <div className="text-center py-6 text-gray-700 text-[10px]">
                暂无反思记录 — 每笔交易平仓后自动分析
              </div>
            ) : (
              <div className="space-y-2 max-h-[350px] overflow-y-auto">
                {[...reflections].reverse().map((ref, i) => (
                  <div key={ref.trade_id || i} className={`rounded-lg border p-3 ${
                    ref.is_loss
                      ? 'bg-red-500/[0.03] border-red-500/20'
                      : 'bg-green-500/[0.03] border-green-500/20'
                  }`}>
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] font-bold text-white">{ref.symbol}</span>
                        <span className={`text-[8px] px-1 py-0.5 rounded font-bold ${
                          ref.side === 'buy' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'
                        }`}>{ref.side === 'buy' ? '多' : '空'}</span>
                        <span className={`text-[9px] font-mono font-bold ${
                          ref.pnl >= 0 ? 'text-bull' : 'text-bear'
                        }`}>${ref.pnl >= 0 ? '+' : ''}{ref.pnl?.toFixed(2)}</span>
                      </div>
                      <span className="text-[8px] text-gray-600">
                        {ref.close_reason === 'sl' ? '🛑止损' : ref.close_reason === 'tp' || ref.close_reason?.startsWith('tp') ? '🎯止盈' : ref.close_reason === 'trailing_sl' ? '🔄移动止损' : '✋' + (ref.close_reason || '手动')}
                      </span>
                    </div>

                    {ref.root_cause && (
                      <div className="text-[9px] text-amber-300/90 mb-1">
                        <span className="text-gray-500">原因:</span> {ref.root_cause}
                      </div>
                    )}
                    {ref.lesson && (
                      <div className="text-[9px] text-cyan-300/80 mb-1">
                        <span className="text-gray-500">教训:</span> {ref.lesson}
                      </div>
                    )}
                    {ref.pattern && (
                      <div className="text-[9px]">
                        <span className="text-gray-500">模式:</span>
                        <span className="ml-1 px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 text-[8px] font-bold">{ref.pattern}</span>
                      </div>
                    )}
                    {ref.suggestion && (
                      <div className="text-[9px] text-gray-500 mt-1 border-t border-glass/30 pt-1">
                        💡 {ref.suggestion}
                      </div>
                    )}
                    {ref.error && !ref.root_cause && (
                      <div className="text-[8px] text-gray-600 mt-1">
                        ⚠️ LLM分析待完成 (评分={ref.score}, 杠杆={ref.leverage}x)
                      </div>
                    )}

                    <div className="text-[7px] text-gray-700 mt-1.5">
                      {ref.timestamp?.slice(0, 16).replace('T', ' ')} · 评分{ref.score} · {ref.leverage}x · 
                      {ref.duration_mins ? `持仓${ref.duration_mins < 60 ? ref.duration_mins.toFixed(0) + '分' : (ref.duration_mins / 60).toFixed(1) + '时'}` : ''}
                      {ref.max_profit > 0 && ` · 最大浮盈+$${ref.max_profit.toFixed(2)}`}
                      {ref.max_drawdown > 0 && ` · 最大浮亏-$${ref.max_drawdown.toFixed(2)}`}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Multi-Symbol Scanner */}
          <div className="bg-surface-2/50 rounded-xl border border-glass/30 p-3">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-[10px] font-bold text-white flex items-center gap-2">
                📡 多币种扫描器
              </h4>
              <button
                onClick={fetchMultiScan}
                disabled={scanLoading}
                className="text-[8px] px-2 py-1 rounded bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition disabled:opacity-50"
              >
                {scanLoading ? '扫描中...' : '🔍 扫描'}
              </button>
            </div>
            {multiScan.length > 0 ? (
              <div className="space-y-1.5">
                {multiScan.map((s, i) => (
                  <div key={s.symbol} className="flex items-center gap-2 bg-surface-3/40 rounded-lg p-1.5">
                    <span className="text-[9px] font-bold text-white w-16">{s.symbol?.replace('USDT','')}</span>
                    <span className={`text-[7px] px-1 py-0.5 rounded font-bold ${
                      s.direction === 'bullish' ? 'bg-green-500/15 text-green-400' :
                      s.direction === 'bearish' ? 'bg-red-500/15 text-red-400' :
                      'bg-gray-500/15 text-gray-400'
                    }`}>{s.direction === 'bullish' ? '多' : s.direction === 'bearish' ? '空' : '平'}</span>
                    <div className="flex-1 bg-surface-3/60 rounded-full h-2 overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${
                        s.score >= 65 ? 'bg-gradient-to-r from-green-500 to-emerald-400' :
                        s.score <= 35 ? 'bg-gradient-to-r from-red-500 to-rose-400' :
                        'bg-gradient-to-r from-gray-500 to-gray-400'
                      }`} style={{ width: `${s.score}%` }} />
                    </div>
                    <span className="text-[8px] font-mono text-white w-6 text-right">{s.score}</span>
                    <span className="text-[7px] font-mono text-gray-500 w-12 text-right">${s.price?.toLocaleString()}</span>
                    <span className={`text-[7px] font-mono w-10 text-right ${s.change_4h >= 0 ? 'text-bull' : 'text-bear'}`}>
                      {s.change_4h >= 0 ? '+' : ''}{s.change_4h}%
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[9px] text-gray-600 text-center py-3">
                点击 "扫描" 分析多币种机会
              </div>
            )}
          </div>

          {/* Backtest Panel */}
          <div className="bg-surface-2/50 rounded-xl border border-glass/30 p-3">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-[10px] font-bold text-white flex items-center gap-2">
                🔬 策略回测
              </h4>
              <div className="flex gap-1">
                {['BTCUSDT', 'ETHUSDT', 'SOLUSDT'].map(sym => (
                  <button
                    key={sym}
                    onClick={() => runBacktest(sym, 30)}
                    disabled={backtestLoading}
                    className="text-[7px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 transition disabled:opacity-50"
                  >
                    {sym.replace('USDT','')}
                  </button>
                ))}
              </div>
            </div>
            {backtestLoading && (
              <div className="text-[9px] text-purple-400 text-center py-3 animate-pulse">
                ⏳ 回测中... (加载历史K线并模拟交易)
              </div>
            )}
            {backtestResult && !backtestLoading && (
              <div className="space-y-2">
                <div className="grid grid-cols-4 gap-1.5 text-center">
                  <div className="bg-surface-3/50 rounded-lg p-1.5">
                    <div className="text-[7px] text-gray-500">总PnL</div>
                    <div className={`text-[11px] font-bold ${backtestResult.total_pnl >= 0 ? 'text-bull' : 'text-bear'}`}>
                      {backtestResult.total_pnl >= 0 ? '+' : ''}${backtestResult.total_pnl?.toFixed(0)}
                    </div>
                  </div>
                  <div className="bg-surface-3/50 rounded-lg p-1.5">
                    <div className="text-[7px] text-gray-500">胜率</div>
                    <div className="text-[11px] font-bold text-amber-400">{backtestResult.win_rate}%</div>
                  </div>
                  <div className="bg-surface-3/50 rounded-lg p-1.5">
                    <div className="text-[7px] text-gray-500">最大回撤</div>
                    <div className="text-[11px] font-bold text-red-400">{backtestResult.max_drawdown_pct}%</div>
                  </div>
                  <div className="bg-surface-3/50 rounded-lg p-1.5">
                    <div className="text-[7px] text-gray-500">Sharpe</div>
                    <div className="text-[11px] font-bold text-cyan-400">{backtestResult.sharpe_ratio}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[8px] text-gray-500">
                  <span>{backtestResult.total_trades}笔交易</span>
                  <span>·</span>
                  <span>盈亏比 {backtestResult.rr_ratio}:1</span>
                  <span>·</span>
                  <span>利润因子 {backtestResult.profit_factor}</span>
                </div>
                {/* Mini equity curve */}
                {backtestResult.equity_curve?.length > 0 && (
                  <div className="h-8 flex items-end gap-px">
                    {backtestResult.equity_curve
                      .filter((_, i) => i % Math.max(1, Math.floor(backtestResult.equity_curve.length / 80)) === 0)
                      .map((v, i, arr) => {
                        const min = Math.min(...arr)
                        const max = Math.max(...arr)
                        const pct = max > min ? ((v - min) / (max - min)) * 100 : 50
                        return (
                          <div key={i} className="flex-1 rounded-sm" style={{
                            height: `${Math.max(2, pct)}%`,
                            backgroundColor: v >= backtestResult.initial_balance ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)',
                            opacity: 0.6,
                          }} />
                        )
                      })}
                  </div>
                )}
              </div>
            )}
            {!backtestResult && !backtestLoading && (
              <div className="text-[9px] text-gray-600 text-center py-3">
                选择币种运行 30天策略回测
              </div>
            )}
          </div>

        </div>
      )}
    </motion.div>
  )
}
