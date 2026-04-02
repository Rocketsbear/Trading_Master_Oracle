import { motion } from 'framer-motion'
import ScoreGauge from './ScoreGauge'

const agentMeta = {
  technical: {
    icon: '📊',
    label: 'Technical',
    gradient: 'from-blue-500/20 to-cyan-500/10',
    accent: '#3b82f6',
    glowColor: 'rgba(59, 130, 246, 0.15)',
  },
  onchain: {
    icon: '⛓️',
    label: 'On-Chain',
    gradient: 'from-purple-500/20 to-violet-500/10',
    accent: '#a855f7',
    glowColor: 'rgba(168, 85, 247, 0.15)',
  },
  macro: {
    icon: '🌍',
    label: 'Macro',
    gradient: 'from-amber-500/20 to-yellow-500/10',
    accent: '#f59e0b',
    glowColor: 'rgba(245, 158, 11, 0.15)',
  },
  sentiment: {
    icon: '💬',
    label: 'Sentiment',
    gradient: 'from-pink-500/20 to-rose-500/10',
    accent: '#ec4899',
    glowColor: 'rgba(236, 72, 153, 0.15)',
  },
  metaphysical: {
    icon: '🔮',
    label: 'Mystic',
    gradient: 'from-indigo-500/20 to-blue-500/10',
    accent: '#6366f1',
    glowColor: 'rgba(99, 102, 241, 0.15)',
  },
}

export default function AgentCard({ agent, type }) {
  const meta = agentMeta[type] || agentMeta.technical

  const getStatusDot = (status) => {
    if (status === 'analyzing') {
      return (
        <motion.span
          animate={{ scale: [1, 1.5, 1], opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
          className="w-2.5 h-2.5 rounded-full shadow-[0_0_8px_rgba(255,255,255,0.8)] z-10"
          style={{ backgroundColor: meta.accent }}
        />
      )
    }
    if (status === 'complete') {
      return <span className="w-2 h-2 rounded-full shadow-[0_0_8px_rgba(0,232,135,0.6)] bg-brand-green" />
    }
    return <span className="w-2 h-2 rounded-full border border-gray-600 bg-gray-800" />
  }

  return (
    <motion.div
      whileHover={{ y: -6, scale: 1.02 }}
      transition={{ type: 'spring', stiffness: 350, damping: 20 }}
      className="glass-card p-4 cursor-default group relative overflow-hidden backdrop-blur-xl border border-white/5 shadow-[0_8px_32px_rgba(0,0,0,0.3)] transition-all duration-300 hover:shadow-[0_12px_40px_rgba(0,0,0,0.5)] hover:border-white/10"
      style={{
        borderColor: agent.status === 'complete' ? `${meta.accent}40` : undefined,
      }}
    >
      {/* Subtle gradient background */}
      <div className={`absolute inset-0 opacity-50 bg-gradient-to-br ${meta.gradient} mix-blend-overlay pointer-events-none`} />

      {/* Top-right glow dot when analyzing */}
      {agent.status === 'analyzing' && (
        <motion.div
          className="absolute -top-6 -right-6 w-20 h-20 rounded-full"
          style={{ background: `radial-gradient(circle, ${meta.glowColor}, transparent 70%)` }}
          animate={{ scale: [1, 1.8, 1], opacity: [0.4, 0.8, 0.4], rotate: [0, 90, 0] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      <div className="relative z-10">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">{meta.icon}</span>
            <span className="text-xs font-semibold tracking-wide" style={{ color: meta.accent }}>
              {meta.label}
            </span>
          </div>
          {getStatusDot(agent.status)}
        </div>

        {/* Score Gauge */}
        <div className="flex justify-center mb-2">
          <ScoreGauge
            score={agent.score}
            size={72}
            strokeWidth={5}
            showLabel={true}
          />
        </div>

        {/* Direction Badge */}
        <div className="flex justify-center">
          {agent.direction ? (
            <motion.span
              initial={{ opacity: 0, scale: 0.8, y: 5 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ type: 'spring' }}
              className={`
                px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border
                ${agent.direction === 'bullish'
                  ? 'bg-bull/10 text-bull border-bull/30 shadow-[0_0_10px_rgba(0,232,135,0.2)]'
                  : agent.direction === 'bearish'
                  ? 'bg-bear/10 text-bear border-bear/30 shadow-[0_0_10px_rgba(255,71,87,0.2)]'
                  : 'bg-gray-500/10 text-yellow-500 border-yellow-500/30 shadow-[0_0_10px_rgba(234,179,8,0.2)]'
                }
              `}
            >
              {agent.direction === 'bullish' ? '▲ BULL' : agent.direction === 'bearish' ? '▼ BEAR' : '— NEUTRAL'}
            </motion.span>
          ) : (
            <span className="text-[10px] text-gray-600 uppercase tracking-wider">
              {agent.status === 'analyzing' ? 'Processing...' : 'Standby'}
            </span>
          )}
        </div>
      </div>
    </motion.div>
  )
}
