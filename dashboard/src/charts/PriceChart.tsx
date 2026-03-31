import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceDot
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
  ts?: string
}

interface Props {
  ticks: Tick[]
  trades?: Trade[]
  height?: number
}

function findNearestLabel(ts: string, ticks: Tick[]): string | null {
  if (!ticks.length) return null
  const t = new Date(ts).getTime()
  let nearest = ticks[0]
  let minDiff = Math.abs(new Date(ticks[0].ts).getTime() - t)
  for (const tick of ticks.slice(1)) {
    const diff = Math.abs(new Date(tick.ts).getTime() - t)
    if (diff < minDiff) { minDiff = diff; nearest = tick }
  }
  return new Date(nearest.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function BuyArrow({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx == null || cy == null) return null
  return (
    <g>
      <polygon points={`${cx},${cy - 10} ${cx - 6},${cy} ${cx + 6},${cy}`} fill="#22c55e" />
      <line x1={cx} y1={cy} x2={cx} y2={cy + 8} stroke="#22c55e" strokeWidth={1.5} />
    </g>
  )
}

function SellArrow({ cx, cy }: { cx?: number; cy?: number }) {
  if (cx == null || cy == null) return null
  return (
    <g>
      <polygon points={`${cx},${cy + 10} ${cx - 6},${cy} ${cx + 6},${cy}`} fill="#ef4444" />
      <line x1={cx} y1={cy - 8} x2={cx} y2={cy} stroke="#ef4444" strokeWidth={1.5} />
    </g>
  )
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

  // Map each timestamped trade to its nearest tick's x-axis label and the trade price
  const tradeMarkers = trades
    .filter(tr => tr.ts)
    .map(tr => ({
      label: findNearestLabel(tr.ts!, ticks),
      price: tr.price,
      action: tr.action,
    }))
    .filter(m => m.label !== null)

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
        {/* Trade arrows: buy = green up, sell = red down, placed at trade price */}
        {tradeMarkers.map((m, i) => (
          <ReferenceDot
            key={i}
            x={m.label!}
            y={m.price}
            r={0}
            shape={m.action === 'buy'
              ? (props: any) => <BuyArrow cx={props.cx} cy={props.cy} />
              : (props: any) => <SellArrow cx={props.cx} cy={props.cy} />
            }
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  )
}
