import { useEffect } from 'react'
import { useStore } from '../store/liveStore'

export function useLiveStream() {
  const { setConnected, applyGameUpdate, applyScheduleUpdate } = useStore()

  useEffect(() => {
    let es: EventSource
    let retryTimeout: ReturnType<typeof setTimeout>

    function connect() {
      es = new EventSource('/api/live/stream')

      es.onopen = () => setConnected(true)

      es.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'game_update') {
            applyGameUpdate(msg)
          } else if (msg.type === 'schedule_update') {
            applyScheduleUpdate(msg.data)
          }
        } catch {
          // ignore parse errors
        }
      }

      es.onerror = () => {
        setConnected(false)
        es.close()
        retryTimeout = setTimeout(connect, 5000)
      }
    }

    connect()

    return () => {
      clearTimeout(retryTimeout)
      es?.close()
    }
  }, [])
}
