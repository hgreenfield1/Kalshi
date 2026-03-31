import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchResults, type ResultGame, type ResultsFilter } from '../api/live'
import StatusPill from '../components/StatusPill'

export default function ResultsPage() {
  const navigate = useNavigate()

  // Filter inputs
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [team, setTeam] = useState('')
  const [pnlMin, setPnlMin] = useState('')
  const [pnlMax, setPnlMax] = useState('')
  const [tradesMin, setTradesMin] = useState('')
  const [tradesMax, setTradesMax] = useState('')
  const [outcome, setOutcome] = useState<'win' | 'loss' | 'all'>('all')

  // Fetch state
  const [games, setGames] = useState<ResultGame[]>([])
  const [loading, setLoading] = useState(false)
  const [fetched, setFetched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Sort state
  const [sortKey, setSortKey] = useState<keyof ResultGame>('date')
  const [sortAsc, setSortAsc] = useState(false)

  function handleSort(key: keyof ResultGame) {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  async function handleApply() {
    setLoading(true)
    setError(null)
    const filters: ResultsFilter = {}
    if (from)              filters.from = from
    if (to)                filters.to = to
    if (team)              filters.team = team
    if (pnlMin !== '')     filters.pnl_min = parseFloat(pnlMin)
    if (pnlMax !== '')     filters.pnl_max = parseFloat(pnlMax)
    if (tradesMin !== '')  filters.trades_min = parseInt(tradesMin, 10)
    if (tradesMax !== '')  filters.trades_max = parseInt(tradesMax, 10)
    if (outcome !== 'all') filters.outcome = outcome
    try {
      setGames(await fetchResults(filters))
      setFetched(true)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setFrom(''); setTo(''); setTeam('')
    setPnlMin(''); setPnlMax('')
    setTradesMin(''); setTradesMax('')
    setOutcome('all')
    setGames([])
    setFetched(false)
    setError(null)
  }

  const sorted = [...games].sort((a, b) => {
    const av = a[sortKey] ?? 0
    const bv = b[sortKey] ?? 0
    const cmp = av < bv ? -1 : av > bv ? 1 : 0
    return sortAsc ? cmp : -cmp
  })

  // Summary stats — done games only for win rate / avg P&L
  const doneGames = games.filter(g => g.status === 'done')
  const totalPnl = doneGames.reduce((s, g) => s + g.pnl, 0)
  const winRate = doneGames.length ? doneGames.filter(g => g.pnl > 0).length / doneGames.length : 0
  const avgPnl = doneGames.length ? totalPnl / doneGames.length : 0

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-default)',
    borderRadius: 4,
    padding: '4px 7px',
    color: 'var(--text-primary)',
    fontSize: 12,
    outline: 'none',
  }

  function thStyle(key: keyof ResultGame, align: 'left' | 'right' = 'left'): React.CSSProperties {
    return {
      textAlign: align,
      padding: '8px 12px',
      color: sortKey === key ? 'var(--accent-light)' : 'var(--text-muted)',
      fontWeight: 500,
      fontSize: 11,
      cursor: 'pointer',
      userSelect: 'none',
      whiteSpace: 'nowrap',
    }
  }

  function sortIndicator(key: keyof ResultGame) {
    if (sortKey !== key) return ' ↕'
    return sortAsc ? ' ↑' : ' ↓'
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>Results</h1>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Live trading history</div>
      </div>

      {/* Summary stats — shown after first fetch */}
      {fetched && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          {((): { label: string; value: string | number; color?: string }[] => [
            { label: 'Games',     value: games.length },
            { label: 'Done',      value: doneGames.length },
            { label: 'Total P&L', value: `${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)}`, color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)' },
            { label: 'Win Rate',  value: `${(winRate * 100).toFixed(0)}%` },
            { label: 'Avg P&L',   value: `${avgPnl >= 0 ? '+' : ''}$${avgPnl.toFixed(2)}`, color: avgPnl >= 0 ? 'var(--green)' : 'var(--red)' },
          ])().map(m => (
            <div key={m.label} style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 8,
              padding: '10px 14px',
              minWidth: 90,
            }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{m.label}</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: m.color ?? 'var(--text-primary)' }}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Single-row filter bar */}
      <div style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 8,
        padding: '10px 14px',
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        flexWrap: 'wrap',
        marginBottom: 16,
      }}>
        {/* Date range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>From</span>
          <input type="date" value={from} onChange={e => setFrom(e.target.value)} style={inputStyle} />
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>To</span>
          <input type="date" value={to} onChange={e => setTo(e.target.value)} style={inputStyle} />
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* Team */}
        <input
          type="text"
          placeholder="Team..."
          value={team}
          onChange={e => setTeam(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleApply()}
          style={{ ...inputStyle, width: 80 }}
        />

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* P&L range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>P&amp;L</span>
          <input type="number" step="0.01" placeholder="min" value={pnlMin} onChange={e => setPnlMin(e.target.value)} style={{ ...inputStyle, width: 60 }} />
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>→</span>
          <input type="number" step="0.01" placeholder="max" value={pnlMax} onChange={e => setPnlMax(e.target.value)} style={{ ...inputStyle, width: 60 }} />
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* Trades range */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Trades</span>
          <input type="number" min="0" placeholder="min" value={tradesMin} onChange={e => setTradesMin(e.target.value)} style={{ ...inputStyle, width: 48 }} />
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>→</span>
          <input type="number" min="0" placeholder="max" value={tradesMax} onChange={e => setTradesMax(e.target.value)} style={{ ...inputStyle, width: 48 }} />
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-subtle)' }} />

        {/* Outcome toggle */}
        <div style={{ display: 'flex', gap: 4 }}>
          {(['win', 'loss', 'all'] as const).map(o => (
            <button
              key={o}
              onClick={() => setOutcome(o)}
              style={{
                padding: '4px 10px',
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 500,
                cursor: 'pointer',
                border: '1px solid',
                borderColor: outcome === o ? 'var(--accent)' : 'var(--border-default)',
                background: outcome === o ? 'rgba(124,58,237,0.15)' : 'transparent',
                color: outcome === o ? 'var(--accent-light)' : 'var(--text-muted)',
              }}
            >
              {o.charAt(0).toUpperCase() + o.slice(1)}
            </button>
          ))}
        </div>

        {/* Apply + Reset */}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            onClick={handleApply}
            disabled={loading}
            style={{
              padding: '5px 14px',
              borderRadius: 4,
              fontSize: 12,
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              border: '1px solid var(--accent)',
              background: 'var(--accent)',
              color: '#fff',
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Loading…' : 'Apply'}
          </button>
          <button
            onClick={handleReset}
            style={{
              padding: '5px 10px',
              borderRadius: 4,
              fontSize: 12,
              cursor: 'pointer',
              border: '1px solid var(--border-default)',
              background: 'transparent',
              color: 'var(--text-muted)',
            }}
          >
            Reset
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>Error: {error}</div>
      )}

      {/* Results table */}
      {fetched && !loading && (
        sorted.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', textAlign: 'center', paddingTop: 60, fontSize: 14 }}>
            No games match the current filters
          </div>
        ) : (
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-elevated)' }}>
                  <th onClick={() => handleSort('date')} style={thStyle('date')}>
                    Date{sortIndicator('date')}
                  </th>
                  <th onClick={() => handleSort('home_team')} style={thStyle('home_team')}>
                    Matchup{sortIndicator('home_team')}
                  </th>
                  <th onClick={() => handleSort('status')} style={thStyle('status')}>
                    Status{sortIndicator('status')}
                  </th>
                  <th onClick={() => handleSort('pregame_win_probability')} style={thStyle('pregame_win_probability', 'right')}>
                    Pre-game{sortIndicator('pregame_win_probability')}
                  </th>
                  <th onClick={() => handleSort('trade_count')} style={thStyle('trade_count', 'right')}>
                    Trades{sortIndicator('trade_count')}
                  </th>
                  <th onClick={() => handleSort('pnl')} style={thStyle('pnl', 'right')}>
                    P&amp;L{sortIndicator('pnl')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((g, i) => (
                  <tr
                    key={g.ticker || i}
                    onClick={() => g.ticker && navigate(`/live/${g.ticker}`)}
                    style={{ borderTop: '1px solid var(--border-subtle)', cursor: g.ticker ? 'pointer' : 'default' }}
                    onMouseEnter={e => { if (g.ticker) (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}
                  >
                    <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>
                      {new Date(g.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </td>
                    <td style={{ padding: '8px 12px', color: 'var(--text-primary)' }}>
                      {g.away_team} <span style={{ color: 'var(--text-muted)' }}>@</span> <strong>{g.home_team}</strong>
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <StatusPill status={g.status} />
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--text-muted)' }}>
                      {g.pregame_win_probability != null ? `${g.pregame_win_probability.toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--text-secondary)' }}>
                      {g.trade_count}
                    </td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', fontWeight: 600 }}>
                      {g.status === 'done' ? (
                        <span style={{ color: g.pnl > 0 ? 'var(--green)' : g.pnl < 0 ? 'var(--red)' : 'var(--text-muted)' }}>
                          {g.pnl >= 0 ? '+' : ''}${g.pnl.toFixed(2)}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11, borderTop: '1px solid var(--border-subtle)' }}>
              {sorted.length} game{sorted.length !== 1 ? 's' : ''}
            </div>
          </div>
        )
      )}

      {/* First-load prompt */}
      {!fetched && !loading && (
        <div style={{ color: 'var(--text-muted)', textAlign: 'center', paddingTop: 60, fontSize: 14 }}>
          Set filters above and click Apply to load results
        </div>
      )}
    </div>
  )
}
