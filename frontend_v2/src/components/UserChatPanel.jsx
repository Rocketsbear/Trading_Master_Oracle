import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTradingStore } from '../store/tradingStore'

const API_BASE = 'http://127.0.0.1:8000'

export default function UserChatPanel() {
  const { chatMessages, addChatMessage } = useTradingStore()
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [chatMessages])

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const userMsg = { role: 'user', content: input.trim(), timestamp: Date.now() }
    addChatMessage(userMsg)
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMsg.content,
          history: chatMessages.slice(-10).map(m => ({ role: m.role, content: m.content }))
        })
      })
      const data = await res.json()
      if (data.success) {
        addChatMessage({ role: 'assistant', content: data.response, timestamp: Date.now() })
      } else {
        addChatMessage({ role: 'assistant', content: `❌ ${data.error}`, timestamp: Date.now() })
      }
    } catch (e) {
      addChatMessage({ role: 'assistant', content: `❌ 网络错误: ${e.message}`, timestamp: Date.now() })
    } finally {
      setLoading(false)
    }
  }

  const injectOpinion = async () => {
    if (!input.trim() || loading) return
    const opinion = input.trim()
    addChatMessage({ role: 'user', content: `🗳️ 注入意见: ${opinion}`, timestamp: Date.now() })
    setInput('')
    setLoading(true)

    // Show phase 4 in discussion panel
    const { addMessage, setAnalysisPhase, setFinalDecision } = useTradingStore.getState()
    setAnalysisPhase(4)
    addMessage({ type: 'system', content: `🗣️ 第四阶段：用户注入意见 → Agent重新评议...`, timestamp: new Date().toISOString() })
    addMessage({ type: 'user_opinion', content: opinion, timestamp: new Date().toISOString() })

    try {
      const res = await fetch(`${API_BASE}/api/re-deliberate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opinion })
      })
      const data = await res.json()
      if (data.success) {
        // Push all agent re-discussion messages to DiscussionPanel
        if (data.messages && data.messages.length > 0) {
          for (const msg of data.messages) {
            addMessage({
              type: 'discussion',
              agent: msg.agent,
              content: msg.message,
              timestamp: msg.timestamp
            })
          }
        }

        const fd = data.final_decision
        addChatMessage({
          role: 'assistant',
          content: `✅ 重新评议完成！\n\n方向: ${fd.direction === 'bullish' ? '📈看多' : fd.direction === 'bearish' ? '📉看空' : '➡️中性'}\n评分: ${fd.score}/100\n入场: $${fd.entry_price?.toLocaleString() || 'N/A'}\n止盈: $${fd.exit_price?.toLocaleString() || 'N/A'}\n止损: $${fd.stop_loss?.toLocaleString() || 'N/A'}\n杠杆: ${fd.leverage || 'N/A'}x\n\n${fd.reasoning}`,
          timestamp: Date.now()
        })
        // Update finalDecision + reset phase
        setFinalDecision(fd)
        addMessage({ type: 'system', content: '✅ 重新评议完成 — 最终决策已更新', timestamp: new Date().toISOString() })
      } else {
        addChatMessage({ role: 'assistant', content: `❌ ${data.error}`, timestamp: Date.now() })
        setAnalysisPhase(0)
      }
    } catch (e) {
      addChatMessage({ role: 'assistant', content: `❌ ${e.message}`, timestamp: Date.now() })
      setAnalysisPhase(0)
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex flex-col h-full glass-card overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-4 pb-3 border-b border-glass">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold uppercase tracking-wider text-white flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse-glow" />
            AI Trading Chat
          </h3>
          <span className="text-xs text-gray-600 font-mono">{chatMessages.length} msgs</span>
        </div>
        <p className="text-[10px] text-gray-500 mt-1">与 Claude 讨论交易策略 · 输入意见可注入Agent重新评议</p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3" style={{ maxHeight: '400px' }}>
        {chatMessages.length === 0 && (
          <div className="text-center text-gray-600 text-xs py-8">
            <div className="text-2xl mb-2">💬</div>
            <p>开始与 AI 交易助手对话</p>
            <p className="mt-1 text-gray-700">提示：输入你的交易想法，点击「注入意见」可触发Agent重新评议</p>
          </div>
        )}
        <AnimatePresence>
          {chatMessages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-brand-green/15 text-brand-green border border-brand-green/20 rounded-br-sm'
                    : 'bg-surface-3 text-gray-300 border border-glass rounded-bl-sm'
                }`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[10px] font-bold opacity-60">
                    {msg.role === 'user' ? '你' : '🤖 AI'}
                  </span>
                </div>
                <div className="whitespace-pre-wrap">{msg.content}</div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {loading && (
          <div className="flex justify-start">
            <div className="bg-surface-3 border border-glass rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="p-3 border-t border-glass">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息或交易意见..."
            className="flex-1 bg-surface-3 border border-glass rounded-xl px-4 py-2.5 text-sm text-white
              placeholder-gray-600 focus:outline-none focus:border-purple-500/40 transition-colors"
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || loading}
            className="px-4 py-2.5 bg-purple-500/20 text-purple-400 rounded-xl text-xs font-bold
              hover:bg-purple-500/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
          >
            发送
          </button>
          <button
            onClick={injectOpinion}
            disabled={!input.trim() || loading}
            title="将你的意见注入，让所有Agent重新讨论"
            className="px-3 py-2.5 bg-yellow-500/15 text-yellow-400 rounded-xl text-xs font-bold
              hover:bg-yellow-500/25 transition-all disabled:opacity-30 disabled:cursor-not-allowed whitespace-nowrap"
          >
            🗳 注入
          </button>
        </div>
      </div>
    </div>
  )
}
