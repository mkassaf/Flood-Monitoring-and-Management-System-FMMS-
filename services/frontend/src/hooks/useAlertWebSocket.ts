import { useEffect } from 'react'
import type { Alert } from '../types'

export function useAlertWebSocket(
  token: string | null,
  onAlert: (alert: Alert) => void
): void {
  useEffect(() => {
    if (!token) return
    const BFF_URL = import.meta.env.VITE_BFF_URL ?? 'http://localhost:8080'
    const wsUrl = `${BFF_URL.replace(/^http/, 'ws')}/ws/alerts?token=${encodeURIComponent(token)}`

    let ws: WebSocket
    let reconnectTimer: ReturnType<typeof setTimeout>

    const connect = () => {
      ws = new WebSocket(wsUrl)
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          if (data.type !== 'heartbeat') onAlert(data as Alert)
        } catch {}
      }
      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000)
      }
    }

    connect()
    return () => {
      clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [token, onAlert])
}
