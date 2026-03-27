type Status = 'running' | 'pending' | 'armed' | 'done' | 'no_market' | 'skipped' | 'live' | 'paper'

const CONFIG: Record<Status, { dot: string; label: string; bg: string; color: string; pulse?: boolean }> = {
  running:   { dot: 'var(--green)',   label: 'Running',   bg: 'rgba(34,197,94,0.12)',   color: 'var(--green)',   pulse: true },
  pending:   { dot: 'var(--yellow)',  label: 'Pending',   bg: 'rgba(234,179,8,0.12)',   color: 'var(--yellow)' },
  armed:     { dot: 'var(--accent-light)', label: 'Armed', bg: 'rgba(168,85,247,0.12)', color: 'var(--accent-light)' },
  done:      { dot: 'var(--text-muted)', label: 'Done',  bg: 'rgba(78,85,96,0.2)',     color: 'var(--text-muted)' },
  no_market: { dot: 'var(--text-muted)', label: 'No Market', bg: 'rgba(78,85,96,0.2)', color: 'var(--text-muted)' },
  skipped:   { dot: 'var(--text-muted)', label: 'Skipped',  bg: 'rgba(78,85,96,0.2)',  color: 'var(--text-muted)' },
  live:      { dot: 'var(--green)',   label: 'LIVE',      bg: 'rgba(34,197,94,0.12)',   color: 'var(--green)',   pulse: true },
  paper:     { dot: 'var(--accent-light)', label: 'PAPER', bg: 'rgba(168,85,247,0.12)', color: 'var(--accent-light)' },
}

export default function StatusPill({ status }: { status: Status }) {
  const cfg = CONFIG[status] ?? CONFIG['pending']
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '3px 8px',
      borderRadius: 20,
      fontSize: 11,
      fontWeight: 600,
      background: cfg.bg,
      color: cfg.color,
    }}>
      <span style={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: cfg.dot,
        flexShrink: 0,
        animation: cfg.pulse ? 'pulse 2s infinite' : undefined,
      }} />
      {cfg.label}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </span>
  )
}
