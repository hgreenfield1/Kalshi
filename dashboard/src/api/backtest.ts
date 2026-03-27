import { useEffect, useState } from 'react'

function useFetch<T>(url: string) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    fetch(url)
      .then(r => r.json())
      .then(d => { if (mounted) { setData(d); setLoading(false) } })
      .catch(e => { if (mounted) setError(String(e)) })
    return () => { mounted = false }
  }, [url])

  return { data, loading, error }
}

export interface BacktestFilters {
  strategies: string[]
  models: string[]
}

export function useBacktestFilters() {
  return useFetch<BacktestFilters>('/api/backtest/filters')
}

export interface BacktestMetrics {
  total_pnl: number
  avg_pnl: number
  win_rate: number
  avg_roi: number
  sharpe: number
  std_dev: number
  total_games: number
  total_trades: number
}

export function useBacktestMetrics(strategy?: string, model?: string, start?: string, end?: string) {
  const p = new URLSearchParams()
  if (strategy) p.set('strategy', strategy)
  if (model) p.set('model', model)
  if (start) p.set('start', start)
  if (end) p.set('end', end)
  return useFetch<BacktestMetrics>(`/api/backtest/metrics?${p}`)
}

export interface BacktestGame {
  game_id: string
  final_cash: number
  pnl: number
  actual_outcome: number | null
  strategy_version: string
  model_version: string
  start_time: string
  trade_count: number
}

export function useBacktestGames(strategy?: string, model?: string, start?: string, end?: string) {
  const p = new URLSearchParams()
  if (strategy) p.set('strategy', strategy)
  if (model) p.set('model', model)
  if (start) p.set('start', start)
  if (end) p.set('end', end)
  return useFetch<{ games: BacktestGame[] }>(`/api/backtest/games?${p}`)
}

export interface PnLPoint {
  game_id: string
  date: string
  pnl: number
  cumulative_pnl: number
}

export function useBacktestCumulativePnL(strategy?: string, model?: string, start?: string, end?: string) {
  const p = new URLSearchParams()
  if (strategy) p.set('strategy', strategy)
  if (model) p.set('model', model)
  if (start) p.set('start', start)
  if (end) p.set('end', end)
  return useFetch<{ series: PnLPoint[] }>(`/api/backtest/cumulative_pnl?${p}`)
}

export function useBacktestDistribution(strategy?: string, model?: string) {
  const p = new URLSearchParams()
  if (strategy) p.set('strategy', strategy)
  if (model) p.set('model', model)
  return useFetch<{ pnls: number[] }>(`/api/backtest/distribution?${p}`)
}
