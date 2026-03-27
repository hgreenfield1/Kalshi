import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts'

interface DataPoint {
  date: string
  cumulative_pnl: number
  pnl?: number
  game_id?: string
}

interface Props {
  data: DataPoint[]
  height?: number
}

function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-default)',
      borderRadius: 6,
      padding: '8px 12px',
      fontSize: 12,
    }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>{d.date?.slice(0, 10)}</div>
      <div style={{ color: d.cumulative_pnl >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
        Cumulative: {d.cumulative_pnl >= 0 ? '+' : ''}{d.cumulative_pnl?.toFixed(2)}
      </div>
      {d.pnl !== undefined && (
        <div style={{ color: d.pnl >= 0 ? 'var(--green)' : 'var(--red)', marginTop: 2 }}>
          Game: {d.pnl >= 0 ? '+' : ''}{d.pnl?.toFixed(2)}
        </div>
      )}
    </div>
  )
}

export default function CumulativePnLChart({ data, height = 260 }: Props) {
  const isPositive = (data[data.length - 1]?.cumulative_pnl ?? 0) >= 0

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={isPositive ? 'var(--green)' : 'var(--red)'} stopOpacity={0.25} />
            <stop offset="100%" stopColor={isPositive ? 'var(--green)' : 'var(--red)'} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="date"
          tickFormatter={v => v?.slice(0, 10) ?? ''}
          minTickGap={60}
        />
        <YAxis tickFormatter={v => `${v > 0 ? '+' : ''}${v.toFixed(0)}`} width={48} />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine y={0} stroke="var(--border-default)" strokeDasharray="4 4" />
        <Area
          type="monotone"
          dataKey="cumulative_pnl"
          stroke={isPositive ? 'var(--green)' : 'var(--red)'}
          strokeWidth={2}
          fill="url(#pnlGrad)"
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
