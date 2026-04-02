import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { useTradingStore } from '../store/tradingStore'

const API_BASE = 'http://127.0.0.1:8000'

/**
 * Fetch K-line data from backend (supports binance/okx/bybit/hyperliquid)
 */
async function fetchKlines(exchange, symbol, interval, limit = 200, marketType = 'futures') {
  const url = `${API_BASE}/api/klines?exchange=${exchange}&symbol=${symbol}&interval=${interval}&limit=${limit}&market_type=${marketType}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const json = await res.json()
  if (!json.success) throw new Error(json.error || 'Failed to fetch klines')
  return json.data
}

export default function TradingViewChart() {
  const chartContainerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const volumeSeriesRef = useRef(null)

  const { symbol, interval, exchange, marketType, klineData, setKlineData } = useTradingStore()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [price, setPrice] = useState(null)
  const [priceChange, setPriceChange] = useState(null)

  // ── Create chart once ──
  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#4a5568',
        fontFamily: 'Inter, system-ui, sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.02)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.02)' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 420,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(255, 255, 255, 0.04)',
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.04)',
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: 'rgba(0, 232, 135, 0.15)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#00e887',
        },
        horzLine: {
          color: 'rgba(0, 232, 135, 0.15)',
          width: 1,
          style: 2,
          labelBackgroundColor: '#00e887',
        },
      },
    })

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00e887',
      downColor: '#ff4757',
      borderUpColor: '#00e887',
      borderDownColor: '#ff4757',
      wickUpColor: '#00e88780',
      wickDownColor: '#ff475780',
    })

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    })

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  // ── Fetch data when symbol/interval/exchange changes ──
  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await fetchKlines(exchange, symbol, interval, 200, marketType)
        if (cancelled) return

        setKlineData(data)

        // Extract latest price info
        if (data.length >= 2) {
          const last = data[data.length - 1]
          const prev = data[data.length - 2]
          setPrice(last.close)
          setPriceChange(((last.close - prev.close) / prev.close) * 100)
        }
      } catch (e) {
        if (!cancelled) {
          console.error('Failed to fetch K-line data:', e)
          setError(e.message)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()

    // Auto-refresh every 30 seconds
    const timer = setInterval(load, 30000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [symbol, interval, exchange, marketType])

  // ── Update chart when klineData changes ──
  useEffect(() => {
    if (!candleSeriesRef.current || klineData.length === 0) return

    const UTC8_OFFSET = 8 * 3600  // UTC+8

    const candleData = klineData.map((k) => ({
      time: k.time + UTC8_OFFSET,
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }))

    const volumeData = klineData.map((k) => ({
      time: k.time + UTC8_OFFSET,
      value: k.volume,
      color: k.close >= k.open
        ? 'rgba(0, 232, 135, 0.2)'
        : 'rgba(255, 71, 87, 0.2)',
    }))

    candleSeriesRef.current.setData(candleData)
    volumeSeriesRef.current.setData(volumeData)
  }, [klineData])

  // ── Format price ──
  const formatPrice = (p) => {
    if (!p) return '—'
    if (p >= 1000) return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    if (p >= 1) return p.toFixed(4)
    return p.toFixed(6)
  }

  return (
    <div className="relative">
      {/* Top Bar: Symbol + Price */}
      <div className="absolute top-4 left-5 z-10 flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <span className="text-lg font-bold text-white tracking-tight">{symbol}</span>
          <span className="px-2 py-0.5 rounded-md bg-surface-4 text-gray-500 text-[10px] font-mono uppercase">
            {interval}
          </span>
        </div>

        {/* Live Price */}
        {price && (
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold font-mono text-white">{formatPrice(price)}</span>
            {priceChange !== null && (
              <span className={`text-xs font-semibold font-mono px-1.5 py-0.5 rounded ${
                priceChange >= 0 ? 'text-bull bg-bull/10' : 'text-bear bg-bear/10'
              }`}>
                {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)}%
              </span>
            )}
          </div>
        )}
      </div>

      {/* Live Indicator */}
      <div className="absolute top-4 right-5 z-10 flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-brand-green animate-pulse-glow" />
        <span className="text-[10px] text-gray-600 uppercase tracking-widest font-mono">Live</span>
      </div>

      {/* Loading Overlay */}
      {loading && klineData.length === 0 && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface-0/80">
          <div className="flex flex-col items-center gap-3">
            <div
              className="w-8 h-8 rounded-full border-2 border-gray-700 border-t-brand-green animate-spin"
            />
            <span className="text-xs text-gray-500">Loading chart data...</span>
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && klineData.length === 0 && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface-0/80">
          <div className="flex flex-col items-center gap-3 text-center px-8">
            <span className="text-2xl">⚠️</span>
            <p className="text-sm text-gray-400">Failed to load chart data</p>
            <p className="text-xs text-gray-600">{error}</p>
          </div>
        </div>
      )}

      {/* Chart Container */}
      <div ref={chartContainerRef} className="w-full" />
    </div>
  )
}
