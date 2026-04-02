import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTradingStore } from './store/tradingStore'
import { useWebSocket } from './hooks/useWebSocket'
import TradingViewChart from './components/TradingViewChart'
import AgentCard from './components/AgentCard'
import DiscussionPanel from './components/DiscussionPanel'
import UserChatPanel from './components/UserChatPanel'
import FinalDecision from './components/FinalDecision'
import TradingPanel from './components/TradingPanel'
import LongShortPanel from './components/LongShortPanel'
import ApiSettingsModal from './components/ApiSettingsModal'
import MultiCoinCompare from './components/MultiCoinCompare'

const SYMBOLS = [
  // 现货 Spot
  { value: 'BTCUSDT', label: 'BTC / USDT', name: 'Bitcoin', type: 'spot' },
  { value: 'ETHUSDT', label: 'ETH / USDT', name: 'Ethereum', type: 'spot' },
  { value: 'SOLUSDT', label: 'SOL / USDT', name: 'Solana', type: 'spot' },
  { value: 'ADAUSDT', label: 'ADA / USDT', name: 'Cardano', type: 'spot' },
  { value: 'XRPUSDT', label: 'XRP / USDT', name: 'Ripple', type: 'spot' },
  { value: 'DOGEUSDT', label: 'DOGE / USDT', name: 'Dogecoin', type: 'spot' },
  { value: 'BNBUSDT', label: 'BNB / USDT', name: 'BNB', type: 'spot' },
  { value: 'AVAXUSDT', label: 'AVAX / USDT', name: 'Avalanche', type: 'spot' },
  { value: 'LINKUSDT', label: 'LINK / USDT', name: 'Chainlink', type: 'spot' },
  // 永续合约 Swap / Perpetual
  { value: 'BTCUSDT', label: 'BTC / USDT 永续', name: 'Bitcoin Perp', type: 'swap' },
  { value: 'ETHUSDT', label: 'ETH / USDT 永续', name: 'Ethereum Perp', type: 'swap' },
  { value: 'SOLUSDT', label: 'SOL / USDT 永续', name: 'Solana Perp', type: 'swap' },
  { value: 'ADAUSDT', label: 'ADA / USDT 永续', name: 'Cardano Perp', type: 'swap' },
  { value: 'XRPUSDT', label: 'XRP / USDT 永续', name: 'Ripple Perp', type: 'swap' },
  { value: 'DOGEUSDT', label: 'DOGE / USDT 永续', name: 'Dogecoin Perp', type: 'swap' },
  { value: 'BNBUSDT', label: 'BNB / USDT 永续', name: 'BNB Perp', type: 'swap' },
  { value: 'AVAXUSDT', label: 'AVAX / USDT 永续', name: 'Avalanche Perp', type: 'swap' },
  { value: 'LINKUSDT', label: 'LINK / USDT 永续', name: 'Chainlink Perp', type: 'swap' },
]

const INTERVALS = [
  { value: '1m', label: '1min' },
  { value: '5m', label: '5min' },
  { value: '15m', label: '15min' },
  { value: '1h', label: '1H' },
  { value: '4h', label: '4H' },
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
]

const EXCHANGES = [
  { value: 'binance', label: 'Binance', icon: '🟡' },
  { value: 'okx', label: 'OKX', icon: '⚫' },
  { value: 'bybit', label: 'Bybit', icon: '🟠' },
  { value: 'hyperliquid', label: 'Hyper', icon: '🟢' },
]

export default function App() {
  const {
    symbol,
    interval,
    exchange,
    marketType,
    agents,
    isAnalyzing,
    userConfig,
    setSymbol,
    setInterval,
    setExchange,
    setMarketType,
    setUserConfig
  } = useTradingStore()

  const { startAnalysis } = useWebSocket()
  const [showSettings, setShowSettings] = useState(false)
  const [rightTab, setRightTab] = useState('discussion')
  const [globalBalance, setGlobalBalance] = useState(2000)

  // Fetch balance occasionally for the top header
  useEffect(() => {
    const fetchBal = () => {
      try {
        const bal = parseFloat(localStorage.getItem('paperBalance')) || 2000
        setGlobalBalance(bal)
      } catch (e) { /* ignore */ }
    }
    fetchBal()
    const iv = setInterval(fetchBal, 2000)
    return () => clearInterval(iv)
  }, [])

  return (
    <div className="min-h-screen text-white relative">
      {/* ═══ Header ═══ */}
      <header className="sticky top-0 z-50 border-b border-glass"
        style={{
          background: 'rgba(8, 9, 12, 0.85)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
        }}
      >
        <div className="max-w-[1600px] mx-auto px-6 h-16 flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <motion.div
              className="w-9 h-9 rounded-xl flex items-center justify-center text-lg relative"
              style={{
                background: 'linear-gradient(135deg, #00e887, #00b4ff)',
                boxShadow: '0 0 20px rgba(0, 232, 135, 0.25)',
              }}
              whileHover={{ scale: 1.1, rotate: 5 }}
              transition={{ type: 'spring', stiffness: 300 }}
            >
              🔮
            </motion.div>
            <div>
              <h1 className="text-lg font-bold tracking-tight gradient-text">
                Trading Oracle
              </h1>
              <p className="text-[10px] text-gray-500 tracking-widest uppercase">
                Multi-Agent AI System
              </p>
            </div>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3">
            {/* Symbol Selector */}
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-gray-500 uppercase tracking-wider hidden sm:block">Pair</span>
              <select
                id="symbol-select"
                value={`${symbol}:${marketType === 'futures' ? 'swap' : 'spot'}`}
                onChange={(e) => {
                  const [sym, pairType] = e.target.value.split(':')
                  setSymbol(sym)
                  setMarketType(pairType === 'swap' ? 'futures' : 'spot')
                }}
                style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}
                className="border border-glass rounded-lg px-3 py-2 text-sm font-medium
                  focus:outline-none focus:border-brand-green/40 transition-colors min-w-[160px]"
              >
                <option disabled style={{ color: '#666', backgroundColor: '#181c25' }}>── 现货 Spot ──</option>
                <option value="BTCUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>BTC / USDT</option>
                <option value="ETHUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>ETH / USDT</option>
                <option value="SOLUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>SOL / USDT</option>
                <option value="ADAUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>ADA / USDT</option>
                <option value="XRPUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>XRP / USDT</option>
                <option value="DOGEUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>DOGE / USDT</option>
                <option value="BNBUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>BNB / USDT</option>
                <option value="AVAXUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>AVAX / USDT</option>
                <option value="LINKUSDT:spot" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>LINK / USDT</option>
                <option disabled style={{ color: '#666', backgroundColor: '#181c25' }}>── 永续 Swap ──</option>
                <option value="BTCUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>BTC / USDT 永续</option>
                <option value="ETHUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>ETH / USDT 永续</option>
                <option value="SOLUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>SOL / USDT 永续</option>
                <option value="ADAUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>ADA / USDT 永续</option>
                <option value="XRPUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>XRP / USDT 永续</option>
                <option value="DOGEUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>DOGE / USDT 永续</option>
                <option value="BNBUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>BNB / USDT 永续</option>
                <option value="AVAXUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>AVAX / USDT 永续</option>
                <option value="LINKUSDT:swap" style={{ color: '#f0f2f5', backgroundColor: '#181c25' }}>LINK / USDT 永续</option>
              </select>
            </div>

            {/* Exchange Selector */}
            <div className="hidden md:flex items-center bg-surface-3 rounded-lg p-0.5 border border-glass">
              {EXCHANGES.map((ex) => (
                <button
                  key={ex.value}
                  onClick={() => setExchange(ex.value)}
                  className={`px-2 py-1.5 text-[10px] font-medium rounded-md transition-all duration-200 ${
                    exchange === ex.value
                      ? 'bg-brand-green/15 text-brand-green shadow-sm'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {ex.icon} {ex.label}
                </button>
              ))}
            </div>

            {/* Market Type Toggle */}
            <div className="hidden sm:flex items-center bg-surface-3 rounded-lg p-0.5 border border-glass">
              {[{ v: 'spot', l: '现货' }, { v: 'futures', l: '合约' }].map((m) => (
                <button
                  key={m.v}
                  onClick={() => setMarketType(m.v)}
                  className={`px-3 py-1.5 text-[10px] font-bold rounded-md transition-all duration-200 ${
                    marketType === m.v
                      ? m.v === 'futures' ? 'bg-purple-500/15 text-purple-400 shadow-sm' : 'bg-brand-green/15 text-brand-green shadow-sm'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {m.l}
                </button>
              ))}
            </div>

            {/* Interval Pills */}
            <div className="hidden md:flex items-center bg-surface-3 rounded-lg p-0.5 border border-glass">
              {INTERVALS.map((i) => (
                <button
                  key={i.value}
                  onClick={() => setInterval(i.value)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${
                    interval === i.value
                      ? 'bg-brand-green/15 text-brand-green shadow-sm'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {i.label}
                </button>
              ))}
            </div>

            {/* Mobile Interval Select */}
            <div className="md:hidden">
              <select
                id="interval-select-mobile"
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="bg-surface-3 border border-glass rounded-lg px-3 py-2 text-sm text-white
                  focus:outline-none focus:border-brand-green/40 transition-colors"
              >
                {INTERVALS.map((i) => (
                  <option key={i.value} value={i.value}>{i.label}</option>
                ))}
              </select>
            </div>

            {/* Global Balance Display */}
            <div className="hidden lg:flex flex-col justify-center items-end bg-surface-3 rounded-lg px-3 py-1 border border-glass shadow-[0_0_15px_rgba(0,232,135,0.05)]">
              <span className="text-[9px] text-gray-500 uppercase tracking-widest font-bold">Paper Eq.</span>
              <span className={`text-sm font-mono font-bold leading-none ${globalBalance > 2000 ? 'neon-text-green' : globalBalance < 2000 ? 'neon-text-red' : 'text-gray-300'}`}>
                ${globalBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>

            {/* Birth Date (for Metaphysical Agent) */}
            <div className="hidden sm:flex items-center gap-2">
              <span className="text-[11px] text-gray-500 uppercase tracking-wider">🔮 生辰</span>
              <input
                id="birth-date-input"
                type="date"
                value={userConfig?.birth_date || ''}
                onChange={(e) => setUserConfig({ birth_date: e.target.value })}
                style={{ color: '#f0f2f5', backgroundColor: '#181c25', colorScheme: 'dark' }}
                className="border border-glass rounded-lg px-2 py-1.5 text-xs
                  focus:outline-none focus:border-purple-500/40 transition-colors w-[130px]"
                placeholder="出生日期"
              />
            </div>

            {/* Divider */}
            <div className="w-px h-8 bg-glass hidden sm:block" />

            {/* Analyze Button */}
            <motion.button
              id="analyze-button"
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              onClick={startAnalysis}
              disabled={isAnalyzing}
              className={`
                relative px-6 py-2 rounded-xl font-semibold text-sm tracking-wide
                transition-all duration-300 overflow-hidden
                ${isAnalyzing
                  ? 'bg-surface-3 text-gray-400 cursor-not-allowed border border-glass'
                  : 'text-black border-0'
                }
              `}
              style={!isAnalyzing ? {
                background: 'linear-gradient(135deg, #00e887, #00b4ff)',
                boxShadow: '0 0 20px rgba(0, 232, 135, 0.3), 0 4px 12px rgba(0, 0, 0, 0.3)',
              } : undefined}
            >
              {isAnalyzing ? (
                <span className="flex items-center gap-2">
                  <motion.span
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                    className="block w-4 h-4 border-2 border-gray-500 border-t-brand-green rounded-full"
                  />
                  Analyzing...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <span>⚡</span>
                  Start Analysis
                </span>
              )}
            </motion.button>

            {/* Settings Button */}
            <motion.button
              whileHover={{ scale: 1.08 }}
              whileTap={{ scale: 0.92 }}
              onClick={() => setShowSettings(true)}
              className="w-9 h-9 rounded-xl flex items-center justify-center border border-glass
                text-gray-400 hover:text-brand-green hover:border-brand-green/30 transition-all"
              style={{ background: 'rgba(255,255,255,0.03)' }}
              title="API 设置 & 交易配置"
            >
              ⚙️
            </motion.button>
          </div>
        </div>
      </header>

      {/* ═══ Main Content ═══ */}
      <main className="max-w-[1600px] mx-auto px-6 py-5">
        <div className="grid grid-cols-12 gap-5">

          {/* Left Column: Chart + Agent Cards */}
          <div className="col-span-12 xl:col-span-8 space-y-5">
            {/* Chart */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="glass-card overflow-hidden"
            >
              <TradingViewChart />
            </motion.div>

            {/* Long/Short Panel (always visible) */}
            <LongShortPanel />

            {/* Agent Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              <AnimatePresence>
                {Object.entries(agents)
                  .filter(([type]) => ['technical', 'onchain', 'macro', 'sentiment', 'metaphysical'].includes(type))
                  .map(([type, agent], index) => (
                  <motion.div
                    key={type}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.08 }}
                  >
                    <AgentCard type={type} agent={agent} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>

            {/* Multi-Coin Scanner */}
            <MultiCoinCompare />
          </div>

          {/* Right Column: Discussion / Chat Tabs */}
          <div className="col-span-12 xl:col-span-4">
            <div className="h-[calc(100vh-180px)] min-h-[500px] sticky top-20 flex flex-col">
              {/* Tab Switcher */}
              <div className="flex mb-2 bg-surface-3 rounded-lg p-0.5 border border-glass">
                <button
                  onClick={() => setRightTab('discussion')}
                  className={`flex-1 px-3 py-2 text-xs font-bold rounded-md transition-all ${
                    rightTab === 'discussion'
                      ? 'bg-brand-green/15 text-brand-green'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  💬 Expert Discussion
                </button>
                <button
                  onClick={() => setRightTab('chat')}
                  className={`flex-1 px-3 py-2 text-xs font-bold rounded-md transition-all ${
                    rightTab === 'chat'
                      ? 'bg-purple-500/15 text-purple-400'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  🤖 AI Chat
                </button>
              </div>
              <div className="flex-1 min-h-0">
                {rightTab === 'discussion' ? <DiscussionPanel /> : <UserChatPanel />}
              </div>
            </div>
          </div>

          {/* Full Width: Final Decision */}
          <div className="col-span-12">
            <FinalDecision />
          </div>

          {/* Full Width: Trading Terminal */}
          <div className="col-span-12">
            <TradingPanel />
          </div>
        </div>
      </main>

      {/* ═══ Footer ═══ */}
      <footer className="border-t border-glass py-6 mt-4">
        <div className="max-w-[1600px] mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-gray-600 text-xs">
            Trading Oracle © 2026 — Multi-Agent AI Trading System
          </p>
          <p className="text-gray-700 text-[11px]">
            ⚠️ 本系统仅供参考，不构成投资建议
          </p>
        </div>
      </footer>

      {/* API Settings Modal */}
      <ApiSettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} />
    </div>
  )
}
