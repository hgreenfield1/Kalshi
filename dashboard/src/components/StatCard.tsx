interface Props {
  label: string
  value: string | number
  delta?: number
  deltaLabel?: string
  color?: string
}

export default function StatCard({ label, value, delta, deltaLabel, color }: Props) {
  const deltaColor = delta === undefined
    ? 'var(--text-muted)'
    : delta >= 0 ? 'var(--green)' : 'var(--red)'

  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 8,
      padding: '16px 20px',
      minWidth: 140,
    }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color: color ?? 'var(--text-primary)', letterSpacing: '-0.5px' }}>
        {value}
      </div>
      {(delta !== undefined || deltaLabel) && (
        <div style={{ marginTop: 6, fontSize: 12, color: deltaColor }}>
          {delta !== undefined && (delta >= 0 ? '+' : '')}{delta !== undefined ? delta.toFixed(2) : ''} {deltaLabel ?? ''}
        </div>
      )}
    </div>
  )
}
