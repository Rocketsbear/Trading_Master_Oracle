/**
 * TradingStats — 交易统计面板
 * 从 TradingPanel.jsx 提取
 */
const API_BASE = 'http://127.0.0.1:8000'

export default function TradingStats({ riskStats, onReset }) {
  if (!riskStats) return null

  return (
    <div className="bg-surface-3 rounded-xl border border-glass p-4">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[11px] font-bold text-gray-400 flex items-center gap-2">
          📊 风控 · 统计
          {riskStats.config && (
            <span className="text-[8px] text-gray-600 font-normal">
              风险{riskStats.config.max_risk_per_trade}% · 日亏限{riskStats.config.max_daily_loss}% · 最大{riskStats.config.max_leverage}x
            </span>
          )}
        </h4>
        <button onClick={onReset}
          className="px-2 py-1 rounded-md text-[8px] font-bold bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all shrink-0">
          🗑️ 清空
        </button>
      </div>
      <div className="grid grid-cols-5 gap-2">
        <div className="text-center bg-surface-2/50 rounded-lg p-1.5">
          <p className="text-[8px] text-gray-600">胜率</p>
          <p className={`text-[11px] font-bold font-mono ${(riskStats.stats?.win_rate || 0) >= 50 ? 'text-brand-green' : 'text-red-400'}`}>
            {riskStats.stats?.win_rate || 0}%
          </p>
          <p className="text-[7px] text-gray-600">{riskStats.stats?.wins || 0}W / {riskStats.stats?.losses || 0}L</p>
        </div>
        <div className="text-center bg-surface-2/50 rounded-lg p-1.5">
          <p className="text-[8px] text-gray-600">总 PnL</p>
          <p className={`text-[11px] font-bold font-mono ${(riskStats.stats?.total_pnl || 0) >= 0 ? 'text-brand-green' : 'text-red-400'}`}>
            {(riskStats.stats?.total_pnl || 0) >= 0 ? '+' : ''}${(riskStats.stats?.total_pnl || 0).toFixed(2)}
          </p>
        </div>
        <div className="text-center bg-surface-2/50 rounded-lg p-1.5">
          <p className="text-[8px] text-gray-600">盈亏因子</p>
          <p className={`text-[11px] font-bold font-mono ${(riskStats.stats?.profit_factor || 0) >= 1 ? 'text-brand-green' : 'text-red-400'}`}>
            {riskStats.stats?.profit_factor || '—'}
          </p>
        </div>
        <div className="text-center bg-surface-2/50 rounded-lg p-1.5">
          <p className="text-[8px] text-gray-600">最大回撤</p>
          <p className="text-[11px] font-bold text-red-400 font-mono">${riskStats.stats?.max_drawdown || 0}</p>
        </div>
        <div className="text-center bg-surface-2/50 rounded-lg p-1.5">
          <p className="text-[8px] text-gray-600">今日 PnL</p>
          <p className={`text-[11px] font-bold font-mono ${(riskStats.stats?.daily_pnl || 0) >= 0 ? 'text-brand-green' : 'text-red-400'}`}>
            {(riskStats.stats?.daily_pnl || 0) >= 0 ? '+' : ''}${(riskStats.stats?.daily_pnl || 0).toFixed(2)}
          </p>
          <p className="text-[7px] text-gray-600">余额 ${riskStats.stats?.account_balance || '—'}</p>
        </div>
      </div>
      {riskStats.trade_check && !riskStats.trade_check.allowed && (
        <div className="mt-2 bg-red-500/10 border border-red-500/20 rounded-lg p-2 text-[9px] text-red-400 font-bold text-center animate-pulse">
          🔴 {riskStats.trade_check.reason}
        </div>
      )}
    </div>
  )
}
