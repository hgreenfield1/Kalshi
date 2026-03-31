import { useState } from 'react'
import {
  useBacktestFilters,
  useBacktestMetrics,
  useBacktestGames,
  useBacktestCumulativePnL,
  useBacktestDistribution,
  useBacktestGameDetail,
  type BacktestGame,
} from '../api/backtest'
import StatCard from '../components/StatCard'
import DataTable, { type Column } from '../components/DataTable'
import CumulativePnLChart from '../charts/CumulativePnLChart'
import PriceChart from '../charts/PriceChart'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

function FilterBar({
  strategies, models, strategy, model,
  onStrategy, onModel,
}: {
  strategies: string[]; models: string[]
  strategy: string; model: string
  onStrategy: (v: string) => void; onModel: (v: string) => void
}) {
  const pillStyle = (active: boolean): React.CSSProperties => ({
    padding: '5px 12px',
    borderRadius: 20,
    fontSize: 12,
    fontWeight: 500,
    cursor: 'pointer',
    border: '1px solid',
    borderColor: active ? 'var(--accent)' : 'var(--border-default)',
    background: active ? 'rgba(124,58,237,0.15)' : 'transparent',
    color: active ? 'var(--accent-light)' : 'var(--text-secondary)',
    transition: 'all 0.1s',
  })

  return (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 24, flexWrap: 'wrap' }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Strategy
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={pillStyle(!strategy)} onClick={() => onStrategy('')}>All</button>
        {strategies.map(s => (
          <button key={s} style={pillStyle(strategy === s)} onClick={() => onStrategy(s)}>{s}</button>
        ))}
      </div>
      <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />
      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Model
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={pillStyle(!model)} onClick={() => onModel('')}>All</button>
        {models.map(m => (
          <button key={m} style={pillStyle(model === m)} onClick={() => onModel(m)}>{m}</button>
        ))}
      </div>
    </div>
  )
}

function DistributionChart({ pnls, height = 200 }: { pnls: number[]; height?: number }) {
  if (!pnls.length) return null

  // Bin into 20 buckets
  const min = Math.min(...pnls)
  const max = Math.max(...pnls)
  const binSize = (max - min) / 20 || 1
  const bins: Record<string, number> = {}

  for (const p of pnls) {
    const bin = Math.floor((p - min) / binSize) * binSize + min
    const k = bin.toFixed(2)
    bins[k] = (bins[k] ?? 0) + 1
  }

  const data = Object.entries(bins)
    .sort((a, b) => parseFloat(a[0]) - parseFloat(b[0]))
    .map(([k, count]) => ({ pnl: parseFloat(k), count }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="pnl" tickFormatter={v => v.toFixed(1)} minTickGap={30} />
        <YAxis />
        <Tooltip
          formatter={(v: any) => [v, 'Games']}
          labelFormatter={(v: any) => `P&L ~${parseFloat(v).toFixed(2)}`}
          contentStyle={{
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border-default)',
            borderRadius: 6,
            fontSize: 12,
          }}
        />
        <Bar
          dataKey="count"
          fill="var(--accent)"
          opacity={0.7}
          radius={[2, 2, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function BacktestPage() {
  const [strategy, setStrategy] = useState('')
  const [model, setModel] = useState('')
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null)
  const [tradesCollapsed, setTradesCollapsed] = useState(false)

  const { data: filters } = useBacktestFilters()
  const { data: metrics, loading: mLoading } = useBacktestMetrics(strategy, model)
  const { data: gamesData, loading: gLoading } = useBacktestGames(strategy, model, undefined, undefined)
  const { data: pnlData } = useBacktestCumulativePnL(strategy, model)
  const { data: distData } = useBacktestDistribution(strategy, model)
  const { data: gameDetail, loading: detailLoading } = useBacktestGameDetail(selectedGameId)

  const games = gamesData?.games ?? []
  const pnlSeries = pnlData?.series ?? []
  const pnls = distData?.pnls ?? []

  const rows = gameDetail?.rows ?? []
  const ticks = rows.filter((r: any) => r.timestamp !== 'FINAL').map((r: any) => ({
    ts: r.timestamp,
    bid: r.bid_price,
    ask: r.ask_price,
    model_prob: r.predicted_prob * 100,
  }))
  const backtestTrades = rows
    .filter((r: any) => r.timestamp !== 'FINAL' && r.signal != null && r.signal !== 0)
    .map((r: any) => ({
      action: r.signal > 0 ? 'buy' : 'sell',
      price: r.signal > 0 ? r.ask_price : r.bid_price,
      quantity: 1,
      ts: r.timestamp,
      positions: r.positions,
    }))

  const gameColumns: Column<BacktestGame>[] = [
    { key: 'game_id', label: 'Game ID' },
    {
      key: 'start_time',
      label: 'Date',
      render: row => row.start_time?.slice(0, 10) ?? '—',
    },
    {
      key: 'pnl',
      label: 'P&L',
      align: 'right',
      render: row => (
        <span style={{ color: row.pnl > 0 ? 'var(--green)' : row.pnl < 0 ? 'var(--red)' : 'var(--text-muted)', fontWeight: 600 }}>
          {row.pnl >= 0 ? '+' : ''}{row.pnl?.toFixed(2)}
        </span>
      ),
    },
    { key: 'trade_count', label: 'Trades', align: 'right' },
    {
      key: 'actual_outcome',
      label: 'Outcome',
      align: 'center',
      render: row => row.actual_outcome == null ? '—' : row.actual_outcome ? 'Home Win' : 'Away Win',
    },
    { key: 'strategy_version', label: 'Strategy' },
    { key: 'model_version', label: 'Model' },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
          Backtest
        </h1>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {metrics?.total_games ?? '…'} games · {metrics?.total_trades ?? '…'} trades
        </div>
      </div>

      {filters && (
        <FilterBar
          strategies={filters.strategies}
          models={filters.models}
          strategy={strategy}
          model={model}
          onStrategy={setStrategy}
          onModel={setModel}
        />
      )}

      {/* Metrics */}
      {!mLoading && metrics && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
          <StatCard
            label="Total P&L"
            value={`${(metrics.total_pnl ?? 0) >= 0 ? '+' : ''}${(metrics.total_pnl ?? 0).toFixed(2)}`}
            color={(metrics.total_pnl ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'}
          />
          <StatCard label="Win Rate" value={`${((metrics.win_rate ?? 0) * 100).toFixed(1)}%`} />
          <StatCard label="Games" value={metrics.total_games ?? 0} />
          <StatCard label="Trades" value={metrics.total_trades ?? 0} />
          <StatCard label="Avg P&L" value={(metrics.avg_pnl ?? 0).toFixed(3)} delta={metrics.avg_pnl} />
          <StatCard label="Sharpe" value={(metrics.sharpe ?? 0).toFixed(3)} />
          <StatCard label="Std Dev" value={(metrics.std_dev ?? 0).toFixed(3)} />
          <StatCard label="Avg ROI" value={`${((metrics.avg_roi ?? 0)).toFixed(2)}%`} />
        </div>
      )}

      {/* Cumulative P&L Chart */}
      {pnlSeries.length > 0 && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '16px 20px',
          marginBottom: 20,
        }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 16 }}>
            Cumulative P&L
          </div>
          <CumulativePnLChart data={pnlSeries} height={240} />
        </div>
      )}

      {/* Distribution */}
      {pnls.length > 0 && (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '16px 20px',
          marginBottom: 20,
        }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 16 }}>
            P&L Distribution ({pnls.length} games)
          </div>
          <DistributionChart pnls={pnls} />
        </div>
      )}

      {/* Games Table */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 12 }}>
          Games ({games.length})
        </div>
        {gLoading ? (
          <div style={{ color: 'var(--text-muted)', padding: 20 }}>Loading...</div>
        ) : (
          <DataTable
            columns={gameColumns}
            rows={games}
            rowKey={row => row.game_id}
            onRowClick={row => {
              setSelectedGameId(prev => prev === row.game_id ? null : row.game_id)
              setTradesCollapsed(false)
            }}
          />
        )}
      </div>

      {/* Game Detail Panel */}
      {selectedGameId && (
        <div style={{
          marginTop: 24,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '16px 20px',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>
              {selectedGameId}
            </div>
            <button
              onClick={() => setSelectedGameId(null)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: 18,
                lineHeight: 1,
                padding: '0 4px',
              }}
            >
              ×
            </button>
          </div>
          {detailLoading ? (
            <div style={{ color: 'var(--text-muted)', padding: 20, textAlign: 'center' }}>Loading...</div>
          ) : ticks.length > 0 ? (
            <>
              <PriceChart ticks={ticks} trades={backtestTrades} />
              <div style={{
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 8,
                overflow: 'hidden',
                marginTop: 16,
              }}>
                <div
                  onClick={() => setTradesCollapsed(c => !c)}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '12px 16px',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)' }}>
                    Trade History{' '}
                    <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({backtestTrades.length})</span>
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {tradesCollapsed ? '▼ expand' : '▲ collapse'}
                  </span>
                </div>
                {!tradesCollapsed && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-elevated)' }}>
                        <th style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>Time</th>
                        <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text-muted)', fontWeight: 500 }}>Action</th>
                        <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-muted)', fontWeight: 500 }}>Price</th>
                        <th style={{ textAlign: 'right', padding: '6px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>Position</th>
                      </tr>
                    </thead>
                    <tbody>
                      {backtestTrades.map((t: any, i: number) => (
                        <tr key={i} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                          <td style={{ padding: '6px 12px', color: 'var(--text-muted)' }}>
                            {new Date(t.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </td>
                          <td style={{ padding: '6px 8px' }}>
                            <span style={{
                              fontWeight: 600,
                              color: t.action === 'buy' ? 'var(--green)' : 'var(--red)',
                              textTransform: 'uppercase',
                              fontSize: 11,
                            }}>
                              {t.action}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text-primary)' }}>
                            {t.price.toFixed(1)}¢
                          </td>
                          <td style={{ textAlign: 'right', padding: '6px 12px', color: 'var(--text-secondary)' }}>
                            {t.positions}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </>
          ) : (
            <div style={{ color: 'var(--text-muted)', padding: 20, textAlign: 'center' }}>No prediction data for this game.</div>
          )}
        </div>
      )}
    </div>
  )
}
