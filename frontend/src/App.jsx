import { useState, useEffect } from 'react'
import axios from 'axios'

const API_BASE = 'http://localhost:8000'

function App() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)

  const analyze = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.post(`${API_BASE}/api/analyze`, {
        symbol,
        interval: '1h'
      })
      setReport(res.data.data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    analyze()
  }, [])

  const getScoreColor = (score) => {
    if (score >= 70) return 'text-green-500'
    if (score >= 50) return 'text-yellow-500'
    return 'text-red-500'
  }

  const getDirectionColor = (direction) => {
    if (direction.includes('多') || direction.includes('看涨')) return 'text-green-400'
    if (direction.includes('空') || direction.includes('看跌')) return 'text-red-400'
    return 'text-gray-400'
  }

  return (
    <div className="min-h-screen p-6">
      {/* 头部 */}
      <header className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-pink-500 to-purple-500 bg-clip-text text-transparent">
            Trading Oracle
          </h1>
          <p className="text-gray-400 text-sm mt-1">AI 驱动的多维度交易决策系统</p>
        </div>
        
        <div className="flex gap-4">
          <select 
            value={symbol} 
            onChange={(e) => setSymbol(e.target.value)}
            className="bg-dark-200 border border-dark-300 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-pink-500"
          >
            <option value="BTCUSDT">BTC/USDT</option>
            <option value="ETHUSDT">ETH/USDT</option>
            <option value="SOLUSDT">SOL/USDT</option>
          </select>
          
          <button 
            onClick={analyze}
            disabled={loading}
            className="bg-gradient-to-r from-pink-500 to-purple-600 px-6 py-2 rounded-lg font-medium hover:opacity-90 disabled:opacity-50 transition"
          >
            {loading ? '分析中...' : '重新分析'}
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-red-500/20 border border-red-500 rounded-lg p-4 mb-6">
          <p className="text-red-400">错误: {error}</p>
        </div>
      )}

      {report && (
        <>
          {/* 评分卡片 */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
            <ScoreCard 
              label="综合评分" 
              score={report.final_score} 
              subLabel={report.recommendation.action}
            />
            <ScoreCard 
              label="技术面" 
              score={report.individual_scores.technical}
            />
            <ScoreCard 
              label="链上" 
              score={report.individual_scores.onchain}
            />
            <ScoreCard 
              label="宏观" 
              score={report.individual_scores.macro}
            />
            <ScoreCard 
              label="玄学" 
              score={report.individual_scores.metaphysical}
            />
          </div>

          {/* 主要建议 */}
          <div className="bg-dark-200 rounded-xl p-6 mb-6 border border-dark-300">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">交易建议</h2>
              <span className={`text-2xl font-bold ${getDirectionColor(report.recommendation.direction)}`}>
                {report.recommendation.direction}
              </span>
            </div>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="bg-dark-300 rounded-lg p-4">
                <p className="text-gray-400 text-sm">置信度</p>
                <p className="text-xl font-semibold">{report.recommendation.confidence}</p>
              </div>
              <div className="bg-dark-300 rounded-lg p-4">
                <p className="text-gray-400 text-sm">评分</p>
                <p className={`text-xl font-semibold ${getScoreColor(report.final_score)}`}>
                  {report.final_score}/100
                </p>
              </div>
            </div>

            {/* 理由 */}
            <div className="border-t border-dark-300 pt-4 mt-4">
              <h3 className="text-gray-400 text-sm mb-2">分析理由:</h3>
              <ul className="space-y-1">
                {report.recommendation.reasons.map((reason, i) => (
                  <li key={i} className="text-gray-300">• {reason}</li>
                ))}
              </ul>
            </div>
          </div>

          {/* 风险提示 */}
          {report.risk_warnings && report.risk_warnings.length > 0 && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 mb-6">
              <h3 className="text-yellow-400 font-semibold mb-2">⚠️ 风险提示</h3>
              <ul className="space-y-1">
                {report.risk_warnings.map((warning, i) => (
                  <li key={i} className="text-yellow-300 text-sm">{warning}</li>
                ))}
              </ul>
            </div>
          )}

          {/* 详细分析 */}
          <div className="bg-dark-200 rounded-xl p-6 border border-dark-300">
            <h2 className="text-xl font-semibold mb-4">详细分析</h2>
            <div className="prose prose-invert max-w-none whitespace-pre-line text-gray-300">
              {report.detailed_analysis}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function ScoreCard({ label, score, subLabel }) {
  const getScoreColor = (score) => {
    if (score === null || score === undefined) return 'text-gray-500'
    if (score >= 70) return 'text-green-500'
    if (score >= 50) return 'text-yellow-500'
    return 'text-red-500'
  }

  return (
    <div className="bg-dark-200 rounded-xl p-4 border border-dark-300">
      <p className="text-gray-400 text-sm mb-1">{label}</p>
      <p className={`text-3xl font-bold ${getScoreColor(score)}`}>
        {score !== null && score !== undefined ? score : '--'}
      </p>
      {subLabel && <p className="text-gray-500 text-xs mt-1">{subLabel}</p>}
    </div>
  )
}

export default App
