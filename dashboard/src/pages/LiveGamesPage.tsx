import { useNavigate } from 'react-router-dom'
import { useSchedule } from '../api/live'
import { useStore } from '../store/liveStore'
import StatusPill from '../components/StatusPill'
import StatCard from '../components/StatCard'

function GameCard({ game }: { game: any }) {
  const navigate = useNavigate()
  const liveUpdate = useStore(s => s.gameUpdates[game.market_ticker])

  const pnl = liveUpdate ? liveUpdate.portfolio.cash - 100 : game.pnl
  const position = liveUpdate ? liveUpdate.portfolio.positions : game.position
  const tradeCount = liveUpdate
    ? liveUpdate.portfolio.trade_history.length
    : game.trade_count

  const status = game.status as any

  return (
    <div
      onClick={() => game.market_ticker && navigate(`/live/${game.market_ticker}`)}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        padding: '16px 18px',
        cursor: 'pointer',
        transition: 'border-color 0.1s, background 0.1s',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--border-default)')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
    >
      {/* Teams */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--text-primary)' }}>
          {game.away_team} @ {game.home_team}
        </div>
        <StatusPill status={status} />
      </div>

      {/* Start time */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>
        {game.scheduled_start
          ? new Date(game.scheduled_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          : '—'}
      </div>

      {/* Metrics row */}
      <div style={{ display: 'flex', gap: 20, fontSize: 12 }}>
        <div>
          <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>P&L</div>
          <div style={{
            fontWeight: 600,
            color: pnl > 0 ? 'var(--green)' : pnl < 0 ? 'var(--red)' : 'var(--text-secondary)',
          }}>
            {pnl > 0 ? '+' : ''}{pnl.toFixed(2)}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>Pos</div>
          <div style={{
            fontWeight: 600,
            color: position > 0 ? 'var(--green)' : position < 0 ? 'var(--red)' : 'var(--text-secondary)',
          }}>
            {position > 0 ? '+' : ''}{position}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>Trades</div>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{tradeCount}</div>
        </div>
        {game.pregame_win_probability != null && (
          <div>
            <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>Pre-game</div>
            <div style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>
              {game.pregame_win_probability.toFixed(0)}¢
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function LiveGamesPage() {
  const { data, loading, error } = useSchedule()
  const connected = useStore(s => s.connected)

  if (loading) return <div style={{ color: 'var(--text-muted)', padding: 40 }}>Loading...</div>
  if (error) return <div style={{ color: 'var(--red)', padding: 40 }}>Error: {error}</div>

  const games = data?.games ?? []
  const totalPnl = data?.daily_pnl ?? 0
  const activeCount = games.filter(g => g.status === 'running').length
  const pendingCount = games.filter(g => ['pending', 'armed'].includes(g.status)).length

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
            Live Games
          </h1>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {data?.date ?? 'Today'} · {games.length} games
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: connected ? 'var(--green)' : 'var(--red)',
            animation: connected ? 'pulse 2s infinite' : undefined,
          }} />
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {connected ? 'Live' : 'Disconnected'}
          </span>
        </div>
        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
      </div>

      {/* Summary row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
        <StatCard
          label="Daily P&L"
          value={`${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}`}
          color={totalPnl >= 0 ? 'var(--green)' : 'var(--red)'}
        />
        <StatCard label="Active" value={activeCount} />
        <StatCard label="Pending" value={pendingCount} />
        <StatCard label="Done" value={games.filter(g => g.status === 'done').length} />
        <StatCard
          label="Mode"
          value={data?.auto_execute ? 'LIVE' : 'PAPER'}
          color={data?.auto_execute ? 'var(--green)' : 'var(--accent-light)'}
        />
      </div>

      {/* Games grid */}
      {games.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', textAlign: 'center', paddingTop: 60 }}>
          No games scheduled today
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 12,
        }}>
          {games.map(game => (
            <GameCard key={game.market_ticker || game.game_id} game={game} />
          ))}
        </div>
      )}
    </div>
  )
}
