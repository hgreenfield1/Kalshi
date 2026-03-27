import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHistorical, useSchedule } from '../api/live'
import StatCard from '../components/StatCard'
import DataTable, { type Column } from '../components/DataTable'
import StatusPill from '../components/StatusPill'

function DateGames({ dateStr }: { dateStr: string }) {
  const { data, loading } = useSchedule(dateStr)
  const navigate = useNavigate()

  if (loading) return <div style={{ color: 'var(--text-muted)', padding: 20 }}>Loading...</div>

  const games = data?.games ?? []

  const cols: Column<typeof games[0]>[] = [
    {
      key: 'matchup',
      label: 'Matchup',
      render: row => `${row.away_team} @ ${row.home_team}`,
    },
    { key: 'status', label: 'Status', render: row => <StatusPill status={row.status as any} /> },
    {
      key: 'pnl',
      label: 'P&L',
      align: 'right',
      render: row => (
        <span style={{ color: (row.pnl ?? 0) > 0 ? 'var(--green)' : (row.pnl ?? 0) < 0 ? 'var(--red)' : 'var(--text-muted)', fontWeight: 600 }}>
          {(row.pnl ?? 0) >= 0 ? '+' : ''}{(row.pnl ?? 0).toFixed(2)}
        </span>
      ),
    },
    { key: 'trade_count', label: 'Trades', align: 'right' },
    {
      key: 'pregame_win_probability',
      label: 'Pre-game',
      align: 'right',
      render: row => row.pregame_win_probability != null ? `${row.pregame_win_probability.toFixed(1)}¢` : '—',
    },
  ]

  return (
    <DataTable
      columns={cols}
      rows={games}
      rowKey={row => row.market_ticker || row.game_id}
      onRowClick={row => row.market_ticker && navigate(`/live/${row.market_ticker}`)}
    />
  )
}

function formatDate(dateStr: string) {
  // "20260326" → "Mar 26, 2026"
  const y = dateStr.slice(0, 4), m = dateStr.slice(4, 6), d = dateStr.slice(6, 8)
  return new Date(`${y}-${m}-${d}`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function ResultsPage() {
  const { data: histData, loading } = useHistorical()
  const [selected, setSelected] = useState<string | null>(null)

  if (loading) return <div style={{ color: 'var(--text-muted)', padding: 40 }}>Loading...</div>

  const dates = histData?.dates ?? []
  const activeDate = selected ?? dates[0]?.date ?? null

  const totalPnl = dates.reduce((s, d) => s + d.total_pnl, 0)
  const totalGames = dates.reduce((s, d) => s + d.games_count, 0)
  const activeDateData = dates.find(d => d.date === activeDate)

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
          Results
        </h1>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Historical live trading sessions</div>
      </div>

      {/* Overall stats */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
        <StatCard
          label="All-time P&L"
          value={`${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}`}
          color={totalPnl >= 0 ? 'var(--green)' : 'var(--red)'}
        />
        <StatCard label="Sessions" value={dates.length} />
        <StatCard label="Games" value={totalGames} />
      </div>

      {dates.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', textAlign: 'center', paddingTop: 60, fontSize: 14 }}>
          No historical sessions yet
        </div>
      ) : (
        <>
          {/* Date selector */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
            {dates.map(d => {
              const isActive = d.date === activeDate
              return (
                <button
                  key={d.date}
                  onClick={() => setSelected(d.date)}
                  style={{
                    padding: '7px 14px',
                    borderRadius: 20,
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: 'pointer',
                    border: '1px solid',
                    borderColor: isActive ? 'var(--accent)' : 'var(--border-default)',
                    background: isActive ? 'rgba(124,58,237,0.15)' : 'transparent',
                    color: isActive ? 'var(--accent-light)' : 'var(--text-secondary)',
                    transition: 'all 0.1s',
                  }}
                >
                  {formatDate(d.date)}
                  <span style={{
                    marginLeft: 8,
                    fontWeight: 600,
                    color: d.total_pnl >= 0 ? 'var(--green)' : 'var(--red)',
                  }}>
                    {d.total_pnl >= 0 ? '+' : ''}{d.total_pnl.toFixed(2)}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Selected day detail */}
          {activeDate && activeDateData && (
            <div style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 8,
              padding: '16px 20px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--text-primary)' }}>
                    {formatDate(activeDate)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                    {activeDateData.games_count} games
                  </div>
                </div>
                <div style={{
                  fontWeight: 700,
                  fontSize: 20,
                  color: activeDateData.total_pnl >= 0 ? 'var(--green)' : 'var(--red)',
                }}>
                  {activeDateData.total_pnl >= 0 ? '+' : ''}{activeDateData.total_pnl.toFixed(2)}
                </div>
              </div>
              <DateGames dateStr={activeDate} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
