import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine
} from 'recharts'

interface Tick {
  ts: string
  bid: number
  ask: number
  model_prob: number
}

interface Trade {
  action: string
  price: number
  quantity: number
}

interface Props {
  ticks: Tick[]
  trades?: Trade[]
  height?: number
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div style={{
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-default)',
      borderRadius: 6,
      padding: '8px 12px',
      fontSize: 12,
    }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11 }}>
        {d?.ts ? new Date(d.ts).toLocaleTimeString() : label}
      </div>
      {d?.model_prob != null && (
        <div style={{ color: 'var(--accent-light)', marginBottom: 2 }}>
          Model: {d.model_prob.toFixed(1)}¢
        </div>
      )}
      {d?.bid != null && (
        <div style={{ color: 'var(--green)' }}>Bid: {d.bid.toFixed(1)}¢</div>
      )}
      {d?.ask != null && (
        <div style={{ color: 'var(--red)' }}>Ask: {d.ask.toFixed(1)}¢</div>
      )}
    </div>
  )
}

export default function PriceChart({ ticks, trades = [], height = 280 }: Props) {
  const data = ticks.map(t => ({
    ...t,
    label: t.ts ? new Date(t.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
  }))

  // Find timestamps of trades to draw reference lines
  const tradeTs = trades.map((tr, i) => ({
    ts: ticks[Math.max(0, ticks.length - 1 - i)]?.ts,
    action: tr.action,
  })).filter(t => t.ts)

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="modelGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="label" minTickGap={40} />
        <YAxis domain={[0, 100]} tickFormatter={v => `${v}¢`} width={40} />
        <Tooltip content={<CustomTooltip />} />
        {/* Model probability area */}
        <Area
          type="monotone"
          dataKey="model_prob"
          stroke="var(--accent-light)"
          strokeWidth={2}
          fill="url(#modelGrad)"
          dot={false}
          name="Model"
        />
        {/* Bid price line */}
        <Line
          type="monotone"
          dataKey="bid"
          stroke="var(--green)"
          strokeWidth={1.5}
          dot={false}
          name="Bid"
        />
        {/* Ask price line */}
        <Line
          type="monotone"
          dataKey="ask"
          stroke="var(--red)"
          strokeWidth={1.5}
          dot={false}
          name="Ask"
        />
        {/* Trade markers */}
        {tradeTs.map((t, i) => (
          <ReferenceLine
            key={i}
            x={t.ts ? new Date(t.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
            stroke="var(--yellow)"
            strokeDasharray="4 4"
            strokeWidth={1}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  )
}
