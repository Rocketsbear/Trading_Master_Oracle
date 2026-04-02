import { useEffect, useRef, useCallback } from 'react'
import { useTradingStore } from '../store/tradingStore'

export function useWebSocket() {
  const ws = useRef(null)
  const {
    symbol,
    interval,
    userConfig,
    startAnalysis,
    updateAgent,
    addMessage,
    setAnalysisPhase,
    setFinalDecision,
    isAnalyzing,
    reset
  } = useTradingStore()

  const handleMessage = useCallback((data) => {
    const type = data.type

    if (type === 'phase') {
      setAnalysisPhase(data.phase)
      addMessage({
        type: 'system',
        content: data.message,
        timestamp: new Date().toISOString()
      })
    } else if (type === 'agent_start') {
      updateAgent(data.agent, { status: 'analyzing' })
    } else if (type === 'agent_complete') {
      updateAgent(data.agent, {
        score: data.score,
        direction: data.direction,
        status: 'complete'
      })
    } else if (type === 'agent_result') {
      addMessage({
        type: 'agent',
        agent: data.agent,
        content: data.reasoning,
        score: data.score,
        direction: data.direction,
        entry_price: data.entry_price,
        exit_price: data.exit_price,
        stop_loss: data.stop_loss,
        leverage: data.leverage,
        timestamp: data.timestamp
      })
    } else if (type === 'discussion') {
      addMessage({
        type: 'discussion',
        agent: data.agent,
        content: data.message,
        timestamp: data.timestamp
      })
    } else if (type === 'user_opinion') {
      addMessage({
        type: 'user_opinion',
        content: data.message,
        timestamp: data.timestamp
      })
    } else if (type === 'final_decision') {
      setFinalDecision(data)
      addMessage({
        type: 'system',
        content: '✅ 分析完成 — 最终决策已生成',
        timestamp: new Date().toISOString()
      })
    } else if (type === 'complete') {
      // Backend sends full result at end
      if (data.data?.final_decision) {
        setFinalDecision(data.data.final_decision)
      } else {
        setFinalDecision(data.data || data)
      }
      setAnalysisPhase(0)
    } else if (type === 'error') {
      console.error('Analysis error:', data.message)
      addMessage({
        type: 'system',
        content: `❌ Error: ${data.message}`,
        timestamp: new Date().toISOString()
      })
      // Reset analyzing state so button becomes clickable again
      reset()
    }
  }, [updateAgent, addMessage, setAnalysisPhase, setFinalDecision, reset])

  const connect = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) return

    ws.current = new WebSocket('ws://localhost:8000/ws/analyze')

    ws.current.onopen = () => {
      console.log('WebSocket connected')
    }

    ws.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        handleMessage(data)
      } catch (e) {
        console.error('Failed to parse message:', e)
      }
    }

    ws.current.onclose = () => {
      console.log('WebSocket disconnected')
    }

    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error)
      // Reset state if WS connection itself fails
      reset()
    }
  }, [handleMessage, reset])

  const analysisTimeoutRef = useRef(null)

  const sendAnalysis = useCallback(() => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      startAnalysis()
      ws.current.send(JSON.stringify({
        symbol,
        interval,
        user_config: userConfig
      }))

      // Safety timeout: auto-reset if analysis hangs for 60s
      if (analysisTimeoutRef.current) clearTimeout(analysisTimeoutRef.current)
      analysisTimeoutRef.current = setTimeout(() => {
        const state = useTradingStore.getState()
        if (state.isAnalyzing) {
          console.warn('Analysis timeout after 60s — resetting state')
          state.addMessage({
            type: 'system',
            content: '⚠️ 分析超时，请重试',
            timestamp: new Date().toISOString()
          })
          state.setFinalDecision(state.finalDecision || {
            score: 0,
            direction: 'neutral',
            reasoning: '分析超时，请重新运行分析'
          })
        }
      }, 120000)
    } else {
      console.error('WebSocket not connected')
      reset()
    }
  }, [symbol, interval, userConfig, startAnalysis, reset])

  const startAnalysisWS = useCallback(() => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
      connect()
      // Wait for connection then send
      setTimeout(() => {
        sendAnalysis()
      }, 1500)
    } else {
      sendAnalysis()
    }
  }, [connect, sendAnalysis])

  const disconnect = useCallback(() => {
    if (ws.current) {
      ws.current.close()
      ws.current = null
    }
  }, [])

  useEffect(() => {
    return () => disconnect()
  }, [disconnect])

  return {
    connect,
    disconnect,
    startAnalysis: startAnalysisWS,
    isAnalyzing
  }
}
