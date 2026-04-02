/**
 * ExecutionLog — 执行日志面板
 * 从 TradingPanel.jsx 提取
 */
const LOG_TYPE_COLORS = {
  info: 'text-blue-400', decision: 'text-purple-400', execute: 'text-brand-green',
  wait: 'text-yellow-400', error: 'text-red-400', start: 'text-brand-green',
  stop: 'text-red-400', override: 'text-orange-400',
}

export default function ExecutionLog({ logs, onClear }) {
  return (
    <div className="bg-surface-3 rounded-xl border border-glass p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[11px] font-bold text-gray-400">📜 执行日志</h4>
        <div className="flex items-center gap-2">
          <span className="text-[8px] text-gray-600 font-mono">{logs.length} 条</span>
          <button onClick={onClear}
            className="px-1.5 py-0.5 rounded text-[7px] font-bold bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all">
            🗑️ 清空
          </button>
        </div>
      </div>
      <div className="space-y-1 max-h-[400px] overflow-y-auto font-mono text-[10px]">
        {logs.length === 0 ? (
          <p className="text-gray-700 text-center py-4">暂无日志</p>
        ) : (
          logs.slice(-200).map((log, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-gray-700 shrink-0">{log.time}</span>
              <span className={LOG_TYPE_COLORS[log.type] || 'text-gray-400'}>{log.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
