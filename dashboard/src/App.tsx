import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import LiveGamesPage from './pages/LiveGamesPage'
import GameDetailPage from './pages/GameDetailPage'
import ResultsPage from './pages/ResultsPage'
import BacktestPage from './pages/BacktestPage'
import { useSummary } from './api/live'
import { useLiveStream } from './hooks/useLiveStream'

function Sidebar() {
  const { data: summary } = useSummary()
  const pnl = summary?.total_pnl ?? 0
  const mode = summary?.mode ?? 'paper'

  const links = [
    { to: '/live', label: 'Live' },
    { to: '/results', label: 'Results' },
    { to: '/backtest', label: 'Backtest' },
  ]

  return (
    <aside style={{
      width: 196,
      minHeight: '100vh',
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border-subtle)',
      display: 'flex',
      flexDirection: 'column',
      padding: '24px 16px',
      flexShrink: 0,
    }}>
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
          Kalshi
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>MLB Trading</div>
      </div>

      <nav style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
        {links.map(link => (
          <NavLink
            key={link.to}
            to={link.to}
            style={({ isActive }) => ({
              display: 'block',
              padding: '7px 10px',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 500,
              textDecoration: 'none',
              color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
              background: isActive ? 'var(--bg-elevated)' : 'transparent',
            })}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>

      <div style={{
        padding: '10px 12px',
        background: 'var(--bg-elevated)',
        borderRadius: 8,
        border: '1px solid var(--border-subtle)',
      }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Daily P&L</div>
        <div style={{
          fontSize: 18,
          fontWeight: 600,
          color: pnl >= 0 ? 'var(--green)' : 'var(--red)',
        }}>
          {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
        </div>
        <span style={{
          marginTop: 6,
          display: 'inline-block',
          fontSize: 10,
          fontWeight: 600,
          padding: '2px 6px',
          borderRadius: 4,
          background: mode === 'live' ? 'rgba(34,197,94,0.15)' : 'rgba(124,58,237,0.15)',
          color: mode === 'live' ? 'var(--green)' : 'var(--accent-light)',
        }}>
          {mode.toUpperCase()}
        </span>
      </div>
    </aside>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  useLiveStream()
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar />
      <main style={{ flex: 1, overflow: 'auto', padding: 28 }}>
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<LiveGamesPage />} />
          <Route path="/live" element={<LiveGamesPage />} />
          <Route path="/live/:ticker" element={<GameDetailPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/backtest" element={<BacktestPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
