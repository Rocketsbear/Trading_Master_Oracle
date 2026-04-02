import { motion } from 'framer-motion'
import { useTradingStore } from '../store/tradingStore'
import ScoreGauge from './ScoreGauge'

export default function FinalDecision() {
  const { finalDecision, isAnalyzing } = useTradingStore()

  if (!finalDecision && !isAnalyzing) return null

  const getDirectionConfig = (direction) => {
    switch (direction) {
      case 'bullish':
        return {
          gradient: 'linear-gradient(135deg, rgba(0, 232, 135, 0.08), rgba(0, 180, 255, 0.04))',
          borderColor: 'rgba(0, 232, 135, 0.2)',
          textColor: '#00e887',
          emoji: '📈',
          label: 'BULLISH',
          labelCn: '看多',
          glow: '0 0 30px rgba(0, 232, 135, 0.1)',
        }
      case 'bearish':
        return {
          gradient: 'linear-gradient(135deg, rgba(255, 71, 87, 0.08), rgba(255, 107, 129, 0.04))',
          borderColor: 'rgba(255, 71, 87, 0.2)',
          textColor: '#ff4757',
          emoji: '📉',
          label: 'BEARISH',
          labelCn: '看空',
          glow: '0 0 30px rgba(255, 71, 87, 0.1)',
        }
      default:
        return {
          gradient: 'linear-gradient(135deg, rgba(255, 217, 61, 0.06), rgba(255, 217, 61, 0.02))',
          borderColor: 'rgba(255, 217, 61, 0.15)',
          textColor: '#ffd93d',
          emoji: '➡️',
          label: 'NEUTRAL',
          labelCn: '中性',
          glow: 'none',
        }
    }
  }

  const config = finalDecision ? getDirectionConfig(finalDecision.direction) : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="glass-card overflow-hidden"
      style={{
        background: config?.gradient || undefined,
        borderColor: config?.borderColor || 'rgba(255,255,255,0.06)',
        boxShadow: config?.glow || undefined,
      }}
    >
      {finalDecision ? (
        <div className="p-6">
          <div className="flex flex-col md:flex-row items-start md:items-center gap-6">
            {/* Left: Gauge + Direction */}
            <div className="flex items-center gap-5">
              <ScoreGauge
                score={finalDecision.score}
                size={100}
                strokeWidth={7}
                showLabel={true}
                label="/100"
              />
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-2xl">{config.emoji}</span>
                  <span
                    className="text-xl font-black tracking-tight"
                    style={{ color: config.textColor }}
                  >
                    {config.label}
                  </span>
                </div>
                <p className="text-gray-500 text-xs">
                  最终综合决策 — {config.labelCn}
                  {finalDecision.user_opinion_integrated && (
                    <span className="ml-1 text-yellow-400">💬已融合用户意见</span>
                  )}
                </p>
              </div>
            </div>

            {/* Center: Reasoning */}
            <div className="flex-1 min-w-0">
              <div className="space-y-1.5 max-h-[120px] overflow-y-auto pr-2">
                {finalDecision.reasoning?.split('\n').filter(l => l.trim()).map((line, i) => (
                  <p key={i} className="text-xs text-gray-400 leading-relaxed">
                    {line}
                  </p>
                ))}
              </div>
            </div>

            {/* Right: Action Buttons */}
            <div className="flex flex-col gap-2 min-w-[140px]">
              <motion.button
                id="action-long"
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                className="px-5 py-2.5 rounded-xl text-xs font-bold tracking-wide
                  text-black transition-all"
                style={{
                  background: 'linear-gradient(135deg, #00e887, #06d6a0)',
                  boxShadow: '0 4px 15px rgba(0, 232, 135, 0.25)',
                }}
              >
                ▲ Long
              </motion.button>

              <motion.button
                id="action-short"
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                className="px-5 py-2.5 rounded-xl text-xs font-bold tracking-wide
                  text-white transition-all"
                style={{
                  background: 'linear-gradient(135deg, #ff4757, #ff6b81)',
                  boxShadow: '0 4px 15px rgba(255, 71, 87, 0.25)',
                }}
              >
                ▼ Short
              </motion.button>
            </div>
          </div>

          {/* Trading Prices + Leverage */}
          {(finalDecision.entry_price || finalDecision.leverage) && (
            <div className="mt-4 pt-3 border-t border-glass">
              <div className="grid grid-cols-4 gap-3">
                <div className="text-center p-2 rounded-lg bg-surface-3 border border-glass">
                  <p className="text-[10px] text-gray-600 mb-1">入场价</p>
                  <p className="text-sm font-bold text-white">
                    ${finalDecision.entry_price?.toLocaleString() || '—'}
                  </p>
                </div>
                <div className="text-center p-2 rounded-lg bg-surface-3 border border-glass">
                  <p className="text-[10px] text-gray-600 mb-1">止盈价</p>
                  <p className="text-sm font-bold text-brand-green">
                    ${finalDecision.exit_price?.toLocaleString() || '—'}
                  </p>
                </div>
                <div className="text-center p-2 rounded-lg bg-surface-3 border border-glass">
                  <p className="text-[10px] text-gray-600 mb-1">止损价</p>
                  <p className="text-sm font-bold text-red-400">
                    ${finalDecision.stop_loss?.toLocaleString() || '—'}
                  </p>
                </div>
                <div className="text-center p-2 rounded-lg bg-surface-3 border border-glass">
                  <p className="text-[10px] text-gray-600 mb-1">推荐杠杆</p>
                  <p className="text-sm font-bold text-yellow-400">
                    {finalDecision.leverage || '—'}x
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Score Breakdown — V4 Enhanced */}
          {finalDecision.score_breakdown?.length > 0 && (
            <div className="mt-4 pt-3 border-t border-glass space-y-2">
              <p className="text-[10px] text-gray-600 font-bold mb-1">📊 V4 评分明细 ({finalDecision.score_breakdown.length}层)</p>
              {/* LLM Review */}
              {finalDecision.score_breakdown.filter(item => item.includes('🤖')).map((item, i) => {
                const isConfirm = item.includes('✅') || item.includes('CONFIRM')
                const isReject = item.includes('REJECT')
                return (
                  <div key={`llm-${i}`} className={`rounded-lg px-3 py-2 text-[9px] font-bold border ${
                    isConfirm ? 'bg-brand-green/5 border-brand-green/20 text-brand-green'
                    : isReject ? 'bg-red-500/5 border-red-500/20 text-red-400'
                    : 'bg-purple-500/5 border-purple-500/20 text-purple-400'
                  }`}>
                    {isConfirm ? '✅' : isReject ? '🚫' : '⚡'} {item.replace('🤖LLM审核: ', '').replace('🤖', '')}
                  </div>
                )
              })}
              <div className="flex flex-wrap gap-1">
                {finalDecision.score_breakdown.filter(item => !item.includes('🤖')).map((item, i) => {
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

          {/* Risk Warning */}
          <div className="mt-4 pt-3 border-t border-glass">
            <p className="text-[10px] text-gray-600 text-center tracking-wide">
              ⚠️ 风险提示：本分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。
            </p>
          </div>
        </div>
      ) : (
        /* Loading State */
        <div className="p-10 flex flex-col items-center justify-center">
          <div className="relative mb-5">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
              className="w-16 h-16 rounded-full"
              style={{
                border: '2px solid rgba(255,255,255,0.04)',
                borderTopColor: '#00e887',
                borderRightColor: '#00b4ff',
              }}
            />
            <div className="absolute inset-0 flex items-center justify-center text-2xl">
              🧠
            </div>
          </div>
          <p className="text-gray-500 text-sm font-medium">AI Experts Collaborating...</p>
          <p className="text-gray-700 text-xs mt-1">请稍候，正在综合分析</p>
        </div>
      )}
    </motion.div>
  )
}
