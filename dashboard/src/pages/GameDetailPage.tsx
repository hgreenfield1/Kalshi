import { useParams, useNavigate } from 'react-router-dom'
import { useGameState } from '../api/live'
import { useStore } from '../store/liveStore'
import PriceChart from '../charts/PriceChart'
import DataTable, { type Column } from '../components/DataTable'

export default function GameDetailPage() {
  const { ticker } = useParams<{ ticker: string }>()
  const navigate = useNavigate()
  const { data: remote, loading, error } = useGameState(ticker ?? '')
  const liveUpdate = useStore(s => ticker ? s.gameUpdates[ticker] : undefined)

  if (loading) return <div style={{ color: 'var(--text-muted)', padding: 40 }}>Loading...</div>
  if (error || !remote) return (
    <div style={{ color: 'var(--red)', padding: 40 }}>
      Game state not found for {ticker}
    </div>
  )

  // Merge live updates
  const portfolio = liveUpdate?.portfolio ?? remote.portfolio
  const tickHistory = liveUpdate?.tick_history ??
    remote.strategy_state?.tick_history ?? []

  const pnl = portfolio.cash - 100
  const trades = portfolio.trade_history ?? []

  const tradeColumns: Column<typeof trades[0]>[] = [
    {
      key: 'action',
      label: 'Action',
      render: row => (
        <span style={{
          fontWeight: 600,
          color: row.action === 'buy' ? 'var(--green)' : 'var(--red)',
          textTransform: 'uppercase',
          fontSize: 11,
        }}>
          {row.action}
        </span>
      ),
    },
    { key: 'price', label: 'Price', align: 'right', render: row => `${row.price}¢` },
    { key: 'quantity', label: 'Qty', align: 'right' },
    { key: 'positions', label: 'Pos', align: 'right' },
    {
      key: 'cash',
      label: 'Cash',
      align: 'right',
      render: row => {
        const delta = row.cash - 100
        return (
          <span style={{ color: delta >= 0 ? 'var(--green)' : 'var(--red)' }}>
            ${row.cash.toFixed(2)}
          </span>
        )
      },
    },
  ]

  return (
    <div>
      {/* Back */}
      <button
        onClick={() => navigate('/live')}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text-muted)',
          cursor: 'pointer',
          fontSize: 13,
          marginBottom: 20,
          padding: 0,
        }}
      >
        ← Back to Live
      </button>

      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>
          {ticker?.split('-').slice(0, -1).join(' ')}
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          {remote.pregame_win_probability > 0 && (
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              Pre-game: {remote.pregame_win_probability.toFixed(1)}¢
            </span>
          )}
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Saved: {new Date(remote.saved_at).toLocaleTimeString()}
          </span>
        </div>
      </div>

      {/* Metrics row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        {[
          { label: 'Cash', value: `$${portfolio.cash.toFixed(2)}` },
          { label: 'P&L', value: `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`, color: pnl >= 0 ? 'var(--green)' : 'var(--red)' },
          { label: 'Position', value: portfolio.positions > 0 ? `+${portfolio.positions}` : String(portfolio.positions),
            color: portfolio.positions > 0 ? 'var(--green)' : portfolio.positions < 0 ? 'var(--red)' : undefined },
          { label: 'Trades', value: trades.length },
        ].map(m => (
          <div key={m.label} style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 8,
            padding: '12px 16px',
            minWidth: 100,
          }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{m.label}</div>
            <div style={{ fontSize: 20, fontWeight: 600, color: (m as any).color ?? 'var(--text-primary)' }}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* Price chart */}
      {tickHistory.length > 0 ? (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '16px 20px',
          marginBottom: 24,
        }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 16 }}>
            Price & Model Probability
          </div>
          <PriceChart ticks={tickHistory} trades={trades} />
          <div style={{ display: 'flex', gap: 16, marginTop: 12, fontSize: 11 }}>
            {[
              { color: 'var(--accent-light)', label: 'Model prob' },
              { color: 'var(--green)', label: 'Bid' },
              { color: 'var(--red)', label: 'Ask' },
              { color: 'var(--yellow)', label: 'Trades' },
            ].map(l => (
              <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--text-muted)' }}>
                <div style={{ width: 12, height: 2, background: l.color }} />
                {l.label}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '32px 20px',
          marginBottom: 24,
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: 13,
        }}>
          No tick history yet — chart will populate once the game starts trading
        </div>
      )}

      {/* Trade table */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 12 }}>
          Trade History ({trades.length})
        </div>
        <DataTable
          columns={tradeColumns}
          rows={trades}
          rowKey={(_, i) => i!}
        />
      </div>
    </div>
  )
}
