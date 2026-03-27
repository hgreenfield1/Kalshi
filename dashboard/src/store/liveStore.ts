import { create } from 'zustand'

interface GameUpdate {
  ticker: string
  portfolio: {
    cash: number
    positions: number
    trade_history: Array<{
      action: string
      price: number
      quantity: number
      positions: number
      cash: number
    }>
  }
  tick_history: Array<{
    ts: string
    bid: number
    ask: number
    model_prob: number
  }>
  saved_at: string
}

interface ScheduleUpdate {
  date: string
  auto_execute: boolean
  daily_pnl: number
  entries: Array<{
    market_ticker: string
    status: string
  }>
}

interface LiveStore {
  gameUpdates: Record<string, GameUpdate>
  scheduleUpdate: ScheduleUpdate | null
  connected: boolean
  setConnected: (v: boolean) => void
  applyGameUpdate: (update: GameUpdate) => void
  applyScheduleUpdate: (update: ScheduleUpdate) => void
}

export const useStore = create<LiveStore>((set) => ({
  gameUpdates: {},
  scheduleUpdate: null,
  connected: false,
  setConnected: (v) => set({ connected: v }),
  applyGameUpdate: (update) =>
    set((s) => ({
      gameUpdates: { ...s.gameUpdates, [update.ticker]: update },
    })),
  applyScheduleUpdate: (update) => set({ scheduleUpdate: update }),
}))
