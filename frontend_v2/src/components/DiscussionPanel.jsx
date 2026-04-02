import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTradingStore } from '../store/tradingStore'

const agentConfig = {
  technical: { name: '技术分析师', accent: '#3b82f6', icon: '📊' },
  onchain: { name: '链上分析师', accent: '#a855f7', icon: '⛓️' },
  macro: { name: '宏观分析师', accent: '#f59e0b', icon: '🌍' },
  sentiment: { name: '情绪分析师', accent: '#ec4899', icon: '💬' },
  metaphysical: { name: '玄学顾问', accent: '#6366f1', icon: '🔮' },
  主持人: { name: '主持人', accent: '#00e887', icon: '🎯' },
}

const agentNameMap = {}
Object.entries(agentConfig).forEach(([key, val]) => {
  agentNameMap[val.name] = key
})

function resolveAgent(agentId) {
  return agentConfig[agentId] || agentConfig[agentNameMap[agentId]] || null
}

const phaseSteps = [
  { phase: 1, label: '独立分析', icon: '🔍' },
  { phase: 2, label: '专家讨论', icon: '💬' },
  { phase: 3, label: '最终决策', icon: '🎯' },
  { phase: 4, label: '用户意见', icon: '🗣️' },
]

/** Simple markdown-like formatting */
function FormatContent({ text }) {
  if (!text) return null
  const lines = text.split('\n')
  
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        const trimmed = line.trim()
        if (!trimmed) return <div key={i} className="h-1" />
        
        // Section headers (lines starting with emoji + text or ===)
        if (/^[📊📈📉🔧💰📏⚠️💬🔮⭐📰🌍📡✅❌🗓️💡🎯📋]/.test(trimmed)) {
          return (
            <p key={i} className="text-[11px] text-gray-300 font-semibold mt-1.5">
              {trimmed}
            </p>
          )
        }
        
        // Lines starting with - or * (bullet points)
        if (/^[-*•]\s/.test(trimmed)) {
          return (
            <p key={i} className="text-[11px] text-gray-400 pl-3 leading-relaxed">
              <span className="text-gray-600 mr-1">•</span>
              {formatInline(trimmed.slice(2))}
            </p>
          )
        }
        
        // Lines starting with number (numbered list)
        if (/^\d+[.)]\s/.test(trimmed)) {
          const match = trimmed.match(/^(\d+[.)]\s*)(.*)/)
          return (
            <p key={i} className="text-[11px] text-gray-400 pl-3 leading-relaxed">
              <span className="text-gray-500 font-mono mr-1">{match[1]}</span>
              {formatInline(match[2])}
            </p>
          )
        }
        
        // Lines with → arrow (sub-observations)  
        if (trimmed.startsWith('→') || trimmed.startsWith('->')) {
          return (
            <p key={i} className="text-[11px] text-gray-500 pl-5 leading-relaxed italic">
              {formatInline(trimmed)}
            </p>
          )
        }
        
        // Default text
        return (
          <p key={i} className="text-[11px] text-gray-400 leading-relaxed">
            {formatInline(trimmed)}
          </p>
        )
      })}
    </div>
  )
}

/** Inline formatting: **bold**, numbers$, percentages */
function formatInline(text) {
  if (!text) return text
  // Bold **text** or @text
  const parts = text.split(/(\*\*[^*]+\*\*|@\w+)/)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <span key={i} className="text-gray-200 font-semibold">{part.slice(2, -2)}</span>
    }
    if (part.startsWith('@')) {
      return <span key={i} className="text-purple-400 font-semibold">{part}</span>
    }
    return part
  })
}

export default function DiscussionPanel() {
  const { messages, analysisPhase } = useTradingStore()
  const scrollRef = useRef(null)
  const [expandedIds, setExpandedIds] = useState(new Set())

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [messages])

  const toggleExpand = (id) => {
    setExpandedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const formatTime = (timestamp) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  return (
    <div className="flex flex-col h-full glass-card overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 border-b border-glass">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-brand-green animate-pulse-glow" />
            Expert Discussion
          </h3>
          <span className="text-xs text-gray-600 font-mono">
            {messages.length} msgs
          </span>
        </div>

        {/* Phase Stepper */}
        <div className="flex items-center gap-1">
          {phaseSteps.map((step, idx) => (
            <div key={step.phase} className="flex items-center flex-1">
              <div className="flex items-center gap-1.5 flex-1">
                <motion.div
                  className="w-7 h-7 rounded-lg flex items-center justify-center text-xs shrink-0 transition-all duration-500"
                  style={{
                    background: analysisPhase >= step.phase
                      ? 'linear-gradient(135deg, #00e887, #00b4ff)'
                      : 'rgba(255,255,255,0.04)',
                    boxShadow: analysisPhase >= step.phase
                      ? '0 0 12px rgba(0, 232, 135, 0.2)'
                      : 'none',
                    color: analysisPhase >= step.phase ? '#000' : '#4a5568',
                  }}
                  animate={analysisPhase === step.phase ? { scale: [1, 1.1, 1] } : {}}
                  transition={{ duration: 1.5, repeat: Infinity }}
                >
                  {step.icon}
                </motion.div>
                <span className={`text-[10px] hidden lg:block ${
                  analysisPhase >= step.phase ? 'text-gray-300' : 'text-gray-700'
                }`}>
                  {step.label}
                </span>
              </div>
              {idx < phaseSteps.length - 1 && (
                <div className="flex-shrink-0 mx-1">
                  <div
                    className="w-4 h-px transition-colors duration-500"
                    style={{
                      background: analysisPhase > step.phase
                        ? 'linear-gradient(90deg, #00e887, #00b4ff)'
                        : 'rgba(255,255,255,0.06)',
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        <AnimatePresence>
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full text-center py-16"
            >
              <motion.div
                className="text-5xl mb-5"
                animate={{ y: [0, -8, 0] }}
                transition={{ duration: 3, repeat: Infinity }}
              >
                🧠
              </motion.div>
              <p className="text-gray-500 text-sm font-medium">Waiting for Analysis</p>
              <p className="text-gray-700 text-xs mt-2 max-w-[200px]">
                点击 Start Analysis 启动 5 位 AI 专家协作
              </p>
            </motion.div>
          )}

          {messages.map((msg, index) => {
            const config = resolveAgent(msg.agent)
            const isSystem = msg.type === 'system'
            const isUserOpinion = msg.type === 'user_opinion'
            const msgId = msg.id || index
            const isExpanded = expandedIds.has(msgId)
            const contentLength = (msg.content || '').length

            return (
              <motion.div
                key={msgId}
                initial={{ opacity: 0, y: 10, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ delay: Math.min(index * 0.03, 0.3) }}
              >
                {isSystem ? (
                  /* System / Phase Message */
                  <div className="flex items-center gap-2 px-3 py-2">
                    <div className="flex-1 h-px bg-glass" />
                    <span className="text-[10px] text-gray-500 tracking-wider whitespace-nowrap">
                      {msg.content}
                    </span>
                    <div className="flex-1 h-px bg-glass" />
                  </div>
                ) : isUserOpinion ? (
                  /* User Opinion Injection */
                  <div className="rounded-xl p-3 border border-yellow-500/20 bg-yellow-500/5">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm">🗣️</span>
                      <span className="text-xs font-semibold text-yellow-400">用户意见</span>
                      <span className="text-[10px] text-gray-700 font-mono ml-auto">
                        {formatTime(msg.timestamp)}
                      </span>
                    </div>
                    <p className="text-xs text-yellow-300/80 leading-relaxed">{msg.content}</p>
                  </div>
                ) : (
                  /* Agent Message */
                  <div
                    className="rounded-xl p-3 border transition-colors cursor-pointer"
                    style={{
                      background: `linear-gradient(135deg, ${config?.accent}08, transparent)`,
                      borderColor: `${config?.accent || '#333'}20`,
                    }}
                  >
                    {/* Message Header */}
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{config?.icon || '👤'}</span>
                        <span
                          className="text-xs font-semibold"
                          style={{ color: config?.accent || '#8b95a5' }}
                        >
                          {config?.name || msg.agent}
                        </span>
                        {msg.type === 'discussion' && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">
                            讨论
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">

                        <span className="text-[10px] text-gray-700 font-mono">
                          {formatTime(msg.timestamp)}
                        </span>
                      </div>
                    </div>

                    {/* Message Content — always show full text */}
                    <div>
                      <FormatContent text={msg.content} />
                    </div>

                    {/* Score + Direction + Entry/Exit/Leverage Tags */}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {msg.score !== undefined && msg.score !== null && (
                        <span className={`
                          px-2 py-0.5 rounded-md text-[10px] font-bold font-mono
                          ${msg.score >= 60 ? 'bg-bull/10 text-bull' : ''}
                          ${msg.score >= 45 && msg.score < 60 ? 'bg-yellow-500/10 text-yellow-400' : ''}
                          ${msg.score < 45 ? 'bg-bear/10 text-bear' : ''}
                        `}>
                          Score: {msg.score}
                        </span>
                      )}
                      {msg.direction && (
                        <span className="text-[10px] text-gray-500">
                          {msg.direction === 'bullish' ? '📈 看多' : msg.direction === 'bearish' ? '📉 看空' : '➡️ 中性'}
                        </span>
                      )}
                      {msg.entry_price && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-3 text-gray-400 border border-glass">
                          入场 ${msg.entry_price?.toLocaleString()}
                        </span>
                      )}
                      {msg.exit_price && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-3 text-brand-green border border-glass">
                          止盈 ${msg.exit_price?.toLocaleString()}
                        </span>
                      )}
                      {msg.stop_loss && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-3 text-red-400 border border-glass">
                          止损 ${msg.stop_loss?.toLocaleString()}
                        </span>
                      )}
                      {msg.leverage && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">
                          {msg.leverage}x 杠杆
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>

      {/* Bottom Phase Banner */}
      {analysisPhase > 0 && (
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="px-4 py-2.5 border-t border-glass"
          style={{ background: 'rgba(0, 232, 135, 0.03)' }}
        >
          <div className="flex items-center justify-center gap-2">
            <motion.span
              animate={{ rotate: 360 }}
              transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
              className="w-3 h-3 border border-brand-green border-t-transparent rounded-full block"
            />
            <p className="text-[11px] text-gray-500">
              {analysisPhase === 1 && '各专家正在独立分析...'}
              {analysisPhase === 2 && '专家们正在讨论交流...'}
              {analysisPhase === 3 && '主持人正在综合决策...'}
              {analysisPhase === 4 && '融合用户意见，重新评议...'}
            </p>
          </div>
        </motion.div>
      )}
    </div>
  )
}
