/**
 * PositionsTable — 持仓表格 + 交易记录 + 权益曲线
 * 从 TradingPanel.jsx 提取
 */
export default function PositionsTable({ positions, orders, totalPnl, onClosePosition, onReset, tradeHistory }) {
  return (
    <div className="grid grid-cols-12 gap-4">
      {/* PnL Summary Cards */}
      <div className="col-span-12">
        <div className="grid grid-cols-4 gap-3">
          <div className="bg-surface-3 rounded-xl border border-glass p-3 text-center">
            <p className="text-[9px] text-gray-600 mb-1">总 PnL</p>
            <p className={`text-lg font-bold font-mono ${totalPnl >= 0 ? 'text-bull' : 'text-bear'}`}>
              {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)} <span className="text-[10px]">USDT</span>
            </p>
          </div>
          <div className="bg-surface-3 rounded-xl border border-glass p-3 text-center">
            <p className="text-[9px] text-gray-600 mb-1">活跃持仓</p>
            <p className="text-lg font-bold text-white">{positions.length}</p>
          </div>
          <div className="bg-surface-3 rounded-xl border border-glass p-3 text-center">
            <p className="text-[9px] text-gray-600 mb-1">AI 下单</p>
            <p className="text-lg font-bold text-purple-400">{orders.filter(o => o.source === 'ai').length}</p>
          </div>
          <div className="bg-surface-3 rounded-xl border border-glass p-3 text-center">
            <p className="text-[9px] text-gray-600 mb-1">人工下单</p>
            <p className="text-lg font-bold text-blue-400">{orders.filter(o => o.source !== 'ai').length}</p>
          </div>
        </div>
        <div className="flex justify-end mt-2">
          <button onClick={onReset}
            className="px-3 py-1.5 rounded-lg text-[9px] font-bold bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all">
            🗑️ 清除所有记录
          </button>
        </div>
      </div>

      {/* Equity Curve */}
      {tradeHistory?.equity_curve?.length > 0 && (
        <div className="col-span-12">
          <div className="bg-surface-3 rounded-xl border border-glass p-3">
            <h4 className="text-[11px] font-bold text-gray-400 mb-2">📈 权益曲线</h4>
            <div className="h-16 flex items-end gap-px">
              {tradeHistory.equity_curve
                .filter((_, i) => i % Math.max(1, Math.floor(tradeHistory.equity_curve.length / 100)) === 0)
                .map((v, i, arr) => {
                  const min = Math.min(...arr)
                  const max = Math.max(...arr)
                  const pct = max > min ? ((v - min) / (max - min)) * 100 : 50
                  return (
                    <div key={i} className="flex-1 rounded-sm" style={{
                      height: `${Math.max(3, pct)}%`,
                      backgroundColor: v >= 0 ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)',
                      opacity: 0.7,
                    }} />
                  )
                })}
            </div>
            <div className="flex justify-between text-[7px] text-gray-600 mt-1">
              <span>首笔交易</span>
              <span className={`font-mono font-bold ${(tradeHistory.stats?.total_pnl || 0) >= 0 ? 'text-brand-green' : 'text-red-400'}`}>
                总计: {(tradeHistory.stats?.total_pnl || 0) >= 0 ? '+' : ''}${(tradeHistory.stats?.total_pnl || 0).toFixed(2)}
              </span>
              <span>最新</span>
            </div>
          </div>
        </div>
      )}

      {/* Positions Table */}
      <div className="col-span-12">
        <h4 className="text-[11px] font-bold text-gray-400 mb-2">📋 当前持仓 <span className="text-gray-600">({positions.length})</span></h4>
        {positions.length === 0 ? (
          <div className="text-center py-4 text-gray-700 text-xs bg-surface-3 rounded-xl border border-glass">暂无持仓</div>
        ) : (
          <div className="overflow-x-auto bg-surface-3 rounded-xl border border-glass">
            <table className="w-full text-[10px]">
              <thead>
                <tr className="text-gray-600 border-b border-glass">
                  <th className="text-left py-2 px-2">来源</th><th className="text-left py-2 px-2">交易对</th>
                  <th className="text-left py-2 px-2">方向</th><th className="text-right py-2 px-2">杠杆</th>
                  <th className="text-right py-2 px-2">入场价</th><th className="text-right py-2 px-2">现价</th>
                  <th className="text-right py-2 px-2">PnL</th><th className="text-right py-2 px-2">ROE%</th>
                  <th className="text-center py-2 px-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(pos => (
                  <tr key={pos.id} className="border-b border-glass/50 hover:bg-white/[0.01]">
                    <td className="py-2 px-2">
                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${pos.source === 'ai' ? 'bg-purple-500/15 text-purple-400' : 'bg-blue-500/15 text-blue-400'}`}>
                        {pos.source === 'ai' ? '🤖 AI' : '🖱️ 手动'}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-white font-semibold">{pos.symbol}</td>
                    <td className="py-2 px-2">
                      <span className={`px-1 py-0.5 rounded text-[9px] font-bold ${pos.side === 'buy' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>
                        {pos.side === 'buy' ? '多' : '空'}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right text-yellow-400">{pos.leverage}x</td>
                    <td className="py-2 px-2 text-right text-gray-300 font-mono">${pos.entry_price?.toFixed(2)}</td>
                    <td className="py-2 px-2 text-right text-white font-mono">${pos.current_price?.toFixed(2)}</td>
                    <td className={`py-2 px-2 text-right font-bold font-mono ${pos.pnl >= 0 ? 'text-bull' : 'text-bear'}`}>
                      {pos.pnl >= 0 ? '+' : ''}{pos.pnl?.toFixed(2)}
                    </td>
                    <td className={`py-2 px-2 text-right font-mono ${pos.roe >= 0 ? 'text-bull' : 'text-bear'}`}>
                      {pos.roe >= 0 ? '+' : ''}{pos.roe?.toFixed(2)}%
                    </td>
                    <td className="py-2 px-2 text-center">
                      <button onClick={() => onClosePosition(pos)} className="px-2 py-1 rounded bg-red-500/10 text-red-400 text-[9px] font-bold hover:bg-red-500/20">平仓</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Order History */}
      <div className="col-span-12">
        <h4 className="text-[11px] font-bold text-gray-400 mb-2">📜 交易记录 <span className="text-gray-600">({orders.length})</span></h4>
        {orders.length === 0 ? (
          <div className="text-center py-4 text-gray-700 text-xs bg-surface-3 rounded-xl border border-glass">暂无交易记录</div>
        ) : (
          <div className="space-y-1 max-h-[200px] overflow-y-auto">
            {orders.slice(0, 30).map(order => (
              <div key={order.id} className="flex items-center justify-between bg-surface-3 rounded-lg px-3 py-2 border border-glass">
                <div className="flex items-center gap-2">
                  <span className={`text-[8px] px-1.5 py-0.5 rounded font-bold ${order.source === 'ai' ? 'bg-purple-500/15 text-purple-400' : 'bg-blue-500/15 text-blue-400'}`}>
                    {order.source === 'ai' ? '🤖 AI' : '🖱️ 手动'}
                  </span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${order.side === 'buy' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'}`}>
                    {order.side === 'buy' ? '买入' : '卖出'}{order.label ? ` · ${order.label}` : ''}
                  </span>
                  <span className="text-[10px] text-white font-semibold">{order.symbol}</span>
                  <span className="text-[9px] text-yellow-400">{order.leverage}x</span>
                  <span className={`text-[8px] px-1 py-0.5 rounded ${order.status === 'success' ? 'bg-brand-green/10 text-brand-green' : order.status === 'failed' ? 'bg-red-500/10 text-red-400' : 'bg-gray-500/10 text-gray-400'}`}>
                    {order.status === 'success' ? '✅成功' : order.status === 'failed' ? '❌失败' : '⏳'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[9px] text-gray-400 font-mono">${order.price?.toLocaleString()}</span>
                  <span className={`text-[8px] px-1 py-0.5 rounded ${order.mode === 'paper' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-red-500/10 text-red-400'}`}>
                    {order.mode === 'paper' ? '模拟' : '实盘'}
                  </span>
                  <span className="text-[9px] text-gray-600 font-mono">{order.time}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
