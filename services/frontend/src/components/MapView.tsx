import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import type { Area, Alert } from '../types'
import { useStore } from '../store'

function areaColor(area: Area, alerts: Alert[]): string {
  const areaAlerts = alerts.filter(a => a.area_id === area.area_id && !a.acknowledged_at)
  if (areaAlerts.some(a => a.severity === 'high')) return '#ef4444'
  if (areaAlerts.some(a => a.severity === 'medium')) return '#f97316'
  if (areaAlerts.some(a => a.severity === 'low')) return '#eab308'
  return '#22c55e'
}

function areaLatLng(areaId: string): [number, number] {
  // Deterministic pseudo-position based on area_id bytes
  const hex = areaId.replace(/-/g, '')
  const lat = 41.0 + (parseInt(hex.slice(0, 4), 16) % 800) / 100 - 4
  const lng = 12.5 + (parseInt(hex.slice(4, 8), 16) % 600) / 100 - 3
  return [lat, lng]
}

export function MapView({ areas }: { areas: Area[] }) {
  const liveAlerts = useStore(s => s.liveAlerts)
  const setSelectedArea = useStore(s => s.setSelectedArea)

  return (
    <MapContainer center={[42.0, 13.0]} zoom={6} className="h-full w-full rounded-lg">
      <TileLayer
        attribution='© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {areas.map(area => (
        <CircleMarker
          key={area.area_id}
          center={areaLatLng(area.area_id)}
          radius={12}
          pathOptions={{
            color: areaColor(area, liveAlerts),
            fillColor: areaColor(area, liveAlerts),
            fillOpacity: 0.7,
          }}
          eventHandlers={{ click: () => setSelectedArea(area.area_id) }}
        >
          <Popup>
            <b>{area.name}</b><br />
            Risk: {area.risk_profile}<br />
            Sensors: {area.sensor_count ?? 0}
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
