import { create } from 'zustand'

export const useTradingStore = create((set, get) => ({
  // 交易配置
  symbol: 'BTCUSDT',
  interval: '1h',
  exchange: 'binance',
  marketType: 'futures',
  
  // 交易所配置
  exchangeConfig: {
    binance: { apiKey: '', apiSecret: '' },
    okx: { apiKey: '', apiSecret: '', passphrase: '' }
  },
  
  // 用户配置（八字等）
  userConfig: {
    birth_date: null,
    birth_time: null,
    birth_place: null
  },
  
  // 分析状态
  isAnalyzing: false,
  analysisPhase: 0,
  
  // Agent状态
  agents: {
    technical: { name: '技术分析师', score: null, direction: null, status: 'idle' },
    onchain: { name: '链上分析师', score: null, direction: null, status: 'idle' },
    macro: { name: '宏观分析师', score: null, direction: null, status: 'idle' },
    sentiment: { name: '情绪分析师', score: null, direction: null, status: 'idle' },
    metaphysical: { name: '玄学顾问', score: null, direction: null, status: 'idle' }
  },
  
  // 讨论消息
  messages: [],
  
  // 最终决策
  finalDecision: null,
  
  // K线数据
  klineData: [],
  
  // Chat 消息
  chatMessages: [],
  
  // 自动交易
  autoTrading: false,
  
  // 多币种托管
  managedMode: 'single',   // 'single' | 'multi'
  managedSymbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT', 'DOGEUSDT'],
  deepAnalysisSymbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],

  // 后端托管状态 (crisis mode + multi-symbol)
  backendManaged: false,      // 后端 managed loop 是否在运行
  crisisMode: false,          // 是否处于危机模式
  crisisInfo: {},             // { fng, war_news_count, reason }
  perSymbolStatus: {},        // { BTCUSDT: { score, direction, mode, ... }, ... }
  
  // Actions
  setSymbol: (symbol) => set({ symbol }),
  setInterval: (interval) => set({ interval }),
  setExchange: (exchange) => set({ exchange }),
  setMarketType: (marketType) => set({ marketType }),
  setExchangeConfig: (exchange) => set((state) => ({
    exchangeConfig: { ...state.exchangeConfig, ...exchange }
  })),
  setUserConfig: (config) => set((state) => ({
    userConfig: { ...state.userConfig, ...config }
  })),
  
  startAnalysis: () => set({ 
    isAnalyzing: true, 
    analysisPhase: 1,
    messages: [],
    finalDecision: null,
    agents: {
      technical: { ...get().agents.technical, status: 'analyzing' },
      onchain: { ...get().agents.onchain, status: 'analyzing' },
      macro: { ...get().agents.macro, status: 'analyzing' },
      sentiment: { ...get().agents.sentiment, status: 'analyzing' },
      metaphysical: { ...get().agents.metaphysical, status: 'analyzing' }
    }
  }),
  
  updateAgent: (agentType, data) => set((state) => ({
    agents: {
      ...state.agents,
      [agentType]: { ...state.agents[agentType], ...data }
    }
  })),
  
  addMessage: (message) => set((state) => ({
    messages: [...state.messages, { ...message, id: Date.now() }]
  })),
  
  setAnalysisPhase: (phase) => set({ analysisPhase: phase }),
  
  setFinalDecision: (decision) => set({ 
    finalDecision: decision,
    isAnalyzing: false,
    analysisPhase: 0,
  }),
  
  setKlineData: (data) => set({ klineData: data }),
  
  addChatMessage: (msg) => set((state) => ({
    chatMessages: [...state.chatMessages, msg]
  })),
  
  setAutoTrading: (val) => set({ autoTrading: val }),
  setManagedMode: (mode) => set({ managedMode: mode }),
  setManagedSymbols: (syms) => set({ managedSymbols: syms }),
  setDeepAnalysisSymbols: (syms) => set({ deepAnalysisSymbols: syms }),
  setBackendManaged: (val) => set({ backendManaged: val }),
  setCrisisMode: (val) => set({ crisisMode: val }),
  setCrisisInfo: (info) => set({ crisisInfo: info }),
  setPerSymbolStatus: (status) => set({ perSymbolStatus: status }),
  
  reset: () => set({
    isAnalyzing: false,
    analysisPhase: 0,
    messages: [],
    finalDecision: null,
    agents: {
      technical: { name: '技术分析师', score: null, direction: null, status: 'idle' },
      onchain: { name: '链上分析师', score: null, direction: null, status: 'idle' },
      macro: { name: '宏观分析师', score: null, direction: null, status: 'idle' },
      sentiment: { name: '情绪分析师', score: null, direction: null, status: 'idle' },
      metaphysical: { name: '玄学顾问', score: null, direction: null, status: 'idle' }
    }
  })
}))
