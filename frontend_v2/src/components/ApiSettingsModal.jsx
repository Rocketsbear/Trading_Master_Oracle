import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const API_BASE = 'http://127.0.0.1:8000'

const EXCHANGES = [
  { id: 'binance', name: 'Binance', icon: '🟡', fields: ['api_key', 'api_secret'] },
  { id: 'okx', name: 'OKX', icon: '⚫', fields: ['api_key', 'api_secret', 'passphrase'] },
  { id: 'bybit', name: 'Bybit', icon: '🟠', fields: ['api_key', 'api_secret'] },
  { id: 'hyperliquid', name: 'Hyperliquid', icon: '🟢', fields: ['api_key', 'api_secret'] },
]

export default function ApiSettingsModal({ isOpen, onClose }) {
  const [settings, setSettings] = useState({})
  const [paperTrading, setPaperTrading] = useState({ enabled: true, balance: 10000 })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [activeTab, setActiveTab] = useState('exchanges')

  useEffect(() => {
    if (isOpen) {
      fetch(`${API_BASE}/api/settings`)
        .then(r => r.json())
        .then(d => {
          if (d.success) {
            setSettings(d.data)
            setPaperTrading(d.data.paper_trading || { enabled: true, balance: 10000 })
          }
        })
        .catch(() => {})
    }
  }, [isOpen])

  const handleSave = async () => {
    setSaving(true)
    setMessage('')
    try {
      const res = await fetch(`${API_BASE}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...settings, paper_trading: paperTrading }),
      })
      const json = await res.json()
      setMessage(json.success ? '✅ 设置已保存' : `❌ ${json.error}`)
    } catch (e) {
      setMessage('❌ 保存失败')
    } finally {
      setSaving(false)
      setTimeout(() => setMessage(''), 3000)
    }
  }

  const updateExchange = (exchange, field, value) => {
    setSettings(prev => ({
      ...prev,
      [exchange]: { ...prev[exchange], [field]: value }
    }))
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[100] flex items-center justify-center"
        onClick={onClose}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

        {/* Modal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          onClick={e => e.stopPropagation()}
          className="relative w-full max-w-xl mx-4 rounded-2xl border border-glass overflow-hidden"
          style={{ background: 'rgba(15, 17, 23, 0.98)', boxShadow: '0 25px 50px rgba(0,0,0,0.5)' }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-glass">
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              ⚙️ API 设置 & 交易配置
            </h2>
            <button onClick={onClose} className="text-gray-500 hover:text-white text-lg transition-colors">✕</button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-glass">
            {[
              { id: 'exchanges', label: '交易所 API', icon: '🔑' },
              { id: 'trading', label: '交易配置', icon: '💰' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex-1 px-4 py-2.5 text-xs font-medium transition-all ${
                  activeTab === tab.id
                    ? 'text-brand-green border-b-2 border-brand-green'
                    : 'text-gray-500 hover:text-gray-300'
                }`}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="p-5 max-h-[60vh] overflow-y-auto space-y-4">
            {activeTab === 'exchanges' && (
              <>
                <p className="text-[10px] text-gray-500 mb-3">
                  输入交易所 API Key 即可接入实盘交易。所有密钥仅存储在本地。
                </p>
                {EXCHANGES.map(ex => (
                  <div key={ex.id} className="bg-surface-3/50 rounded-xl p-3 space-y-2">
                    <div className="text-xs font-bold text-gray-300 flex items-center gap-1.5">
                      <span>{ex.icon}</span> {ex.name}
                    </div>
                    {ex.fields.map(field => (
                      <div key={field}>
                        <label className="text-[10px] text-gray-500 uppercase tracking-wider">{field.replace(/_/g, ' ')}</label>
                        <input
                          type="password"
                          value={settings[ex.id]?.[field] || ''}
                          onChange={e => updateExchange(ex.id, field, e.target.value)}
                          placeholder={`输入 ${ex.name} ${field}`}
                          className="w-full mt-0.5 bg-surface-2 border border-glass rounded-lg px-3 py-1.5 text-xs text-white
                            focus:outline-none focus:border-brand-green/40 transition-colors"
                          style={{ colorScheme: 'dark' }}
                        />
                      </div>
                    ))}
                  </div>
                ))}
              </>
            )}

            {activeTab === 'trading' && (
              <div className="space-y-4">
                {/* Paper Trading Toggle */}
                <div className="bg-surface-3/50 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-bold text-gray-300">📝 模拟交易</div>
                      <div className="text-[10px] text-gray-500">使用虚拟资金测试交易策略</div>
                    </div>
                    <button
                      onClick={() => setPaperTrading(p => ({ ...p, enabled: !p.enabled }))}
                      className={`w-10 h-5 rounded-full transition-all duration-200 ${
                        paperTrading.enabled ? 'bg-brand-green' : 'bg-gray-600'
                      }`}
                    >
                      <motion.div
                        className="w-4 h-4 bg-white rounded-full shadow"
                        animate={{ x: paperTrading.enabled ? 21 : 2 }}
                        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                      />
                    </button>
                  </div>

                  {paperTrading.enabled && (
                    <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} className="space-y-2">
                      <label className="text-[10px] text-gray-500 uppercase tracking-wider">初始资金 (USDT)</label>
                      <input
                        type="number"
                        value={paperTrading.balance}
                        onChange={e => setPaperTrading(p => ({ ...p, balance: Number(e.target.value) }))}
                        className="w-full bg-surface-2 border border-glass rounded-lg px-3 py-2 text-sm text-white font-mono
                          focus:outline-none focus:border-brand-green/40 transition-colors"
                      />
                      <div className="flex gap-2">
                        {[1000, 5000, 10000, 50000, 100000].map(amount => (
                          <button
                            key={amount}
                            onClick={() => setPaperTrading(p => ({ ...p, balance: amount }))}
                            className={`px-2 py-1 rounded text-[10px] border transition-all ${
                              paperTrading.balance === amount
                                ? 'border-brand-green/50 text-brand-green bg-brand-green/10'
                                : 'border-glass text-gray-500 hover:text-gray-300'
                            }`}
                          >
                            {amount >= 1000 ? `${amount/1000}K` : amount}
                          </button>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </div>

                {/* Live Trading Warning */}
                {!paperTrading.enabled && (
                  <div className="text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                    ⚠️ <strong>实盘模式</strong>：将使用真实资金进行交易，请确保已设置好交易所 API 且已了解风险。
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-5 py-3 border-t border-glass">
            <span className="text-[10px] text-gray-500">{message}</span>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="px-4 py-1.5 text-xs text-gray-400 hover:text-white transition-colors"
              >
                取消
              </button>
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={handleSave}
                disabled={saving}
                className="px-5 py-1.5 text-xs font-bold text-black rounded-lg transition-all"
                style={{ background: 'linear-gradient(135deg, #00e887, #00b4ff)' }}
              >
                {saving ? '保存中...' : '💾 保存'}
              </motion.button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
