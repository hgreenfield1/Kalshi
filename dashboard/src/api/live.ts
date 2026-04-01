import { useEffect, useState } from 'react'

export interface GameEntry {
  game_id: number
  market_ticker: string
  home_team: string
  away_team: string
  scheduled_start: string
  status: string
  pnl: number
  position: number
  trade_count: number
  pregame_win_probability: number | null
}

export interface Schedule {
  date: string
  auto_execute: boolean
  daily_pnl: number
  daily_loss_limit: number
  games: GameEntry[]
}

export interface Summary {
  total_pnl: number
  active_count: number
  pending_count: number
  done_count: number
  total_trades: number
  mode: 'live' | 'paper'
  daily_loss_limit: number
}

export interface GameState {
  ticker: string
  game_id: number
  pregame_prob_fetched: boolean
  pregame_win_probability: number
  portfolio: {
    cash: number
    positions: number
    trade_history: Array<{
      action: string
      price: number
      quantity: number
      positions: number
      cash: number
      ts?: string
    }>
  }
  strategy_state: {
    active_signal: string | null
    entry_price: number | null
    tick_history?: Array<{
      ts: string
      bid: number
      ask: number
      model_prob: number
    }>
  }
  saved_at: string
}

function useFetch<T>(url: string, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    const load = () =>
      fetch(url)
        .then(r => r.json())
        .then(d => { if (mounted) { setData(d); setLoading(false) } })
        .catch(e => { if (mounted) setError(String(e)) })

    load()
    if (refreshMs > 0) {
      const id = setInterval(load, refreshMs)
      return () => { mounted = false; clearInterval(id) }
    }
    return () => { mounted = false }
  }, [url])

  return { data, loading, error, refetch: () => fetch(url).then(r => r.json()).then(setData) }
}

export function useSchedule(dateStr?: string) {
  const url = dateStr ? `/api/live/schedule?date=${dateStr}` : '/api/live/schedule'
  return useFetch<Schedule>(url, 10000)
}

export function useSummary() {
  return useFetch<Summary>('/api/live/summary', 10000)
}

export function useGameState(ticker: string) {
  return useFetch<GameState>(`/api/live/games/${ticker}`, 15000)
}

export interface HistoricalDate {
  date: string
  games_count: number
  total_pnl: number
  auto_execute: boolean
}

export function useHistorical() {
  return useFetch<{ dates: HistoricalDate[] }>('/api/live/historical', 60000)
}

export type GameStatus = 'running' | 'pending' | 'armed' | 'done' | 'no_market' | 'skipped' | 'live' | 'paper'

export interface ResultGame {
  date: string
  ticker: string
  home_team: string
  away_team: string
  status: GameStatus
  pregame_win_probability: number | null
  pnl: number
  trade_count: number
}

export interface ResultsFilter {
  from?: string
  to?: string
  team?: string
  pnl_min?: number
  pnl_max?: number
  trades_min?: number
  trades_max?: number
  outcome?: 'win' | 'loss' | 'all'
}

export async function fetchResults(filters: ResultsFilter): Promise<ResultGame[]> {
  const params = new URLSearchParams()
  if (filters.from)              params.set('from', filters.from)
  if (filters.to)                params.set('to', filters.to)
  if (filters.team)              params.set('team', filters.team)
  if (filters.pnl_min != null)   params.set('pnl_min', String(filters.pnl_min))
  if (filters.pnl_max != null)   params.set('pnl_max', String(filters.pnl_max))
  if (filters.trades_min != null) params.set('trades_min', String(filters.trades_min))
  if (filters.trades_max != null) params.set('trades_max', String(filters.trades_max))
  if (filters.outcome && filters.outcome !== 'all') params.set('outcome', filters.outcome)
  const res = await fetch(`/api/live/results?${params}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
