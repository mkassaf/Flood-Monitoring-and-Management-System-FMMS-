export interface User {
  user_id: string
  email: string
  role: 'area_manager' | 'city_manager' | 'regional_manager'
  jurisdiction: string[]
  area_ids: string[]
}

export interface Area {
  area_id: string
  city_id: string
  name: string
  risk_profile: string
  sensor_count?: number
  live_summary?: {
    max_water_level_m?: number
    latest_ts?: string
    sensor_count: number
  }
}

export interface Alert {
  alert_id: string
  kind: 'threshold' | 'malfunction' | 'priority'
  severity: 'low' | 'medium' | 'high'
  area_id: string
  sensor_id: string | null
  parameter: string | null
  value: number | null
  threshold: number | null
  ts_event: string
  ts_emitted: string
  ts_persisted: string
  acknowledged_at: string | null
  context: Record<string, unknown>
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}
