import axios from 'axios'
import type { TokenResponse, User, Area, Alert } from './types'

const BFF_URL = import.meta.env.VITE_BFF_URL ?? 'http://localhost:8080'

const api = axios.create({ baseURL: BFF_URL })

function authHeader(token: string) {
  return { Authorization: `Bearer ${token}` }
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>('/auth/login', { email, password })
  return res.data
}

export async function getMe(token: string): Promise<User> {
  const res = await api.get<User>('/dashboard/me', { headers: authHeader(token) })
  return res.data
}

export async function getAreas(token: string): Promise<Area[]> {
  const res = await api.get<Area[]>('/dashboard/areas', { headers: authHeader(token) })
  return res.data
}

export async function getAlerts(token: string, params?: {
  severity?: string
  acknowledged?: boolean
  limit?: number
  offset?: number
}): Promise<Alert[]> {
  const res = await api.get<Alert[]>('/dashboard/alerts', {
    headers: authHeader(token),
    params,
  })
  return res.data
}

export async function acknowledgeAlert(token: string, alertId: string, reason: string): Promise<void> {
  await api.post(
    `/dashboard/alerts/${alertId}/acknowledge`,
    null,
    { headers: authHeader(token), params: { reason } }
  )
}

export function connectAlertWebSocket(token: string, onMessage: (alert: Alert) => void): WebSocket {
  const wsBase = BFF_URL.replace(/^http/, 'ws')
  const ws = new WebSocket(`${wsBase}/ws/alerts?token=${encodeURIComponent(token)}`)
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type !== 'heartbeat') onMessage(data as Alert)
    } catch {}
  }
  return ws
}
