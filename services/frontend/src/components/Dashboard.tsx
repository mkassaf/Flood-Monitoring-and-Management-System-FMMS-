import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getAreas, getAlerts, connectAlertWebSocket } from '../api'
import { useStore } from '../store'
import { MapView } from './MapView'
import { AreaDetail } from './AreaDetail'
import { AlertBadge } from './AlertBadge'

export function Dashboard() {
  const token = useStore(s => s.token)!
  const user = useStore(s => s.user)!
  const selectedAreaId = useStore(s => s.selectedAreaId)
  const setSelectedArea = useStore(s => s.setSelectedArea)
  const liveAlerts = useStore(s => s.liveAlerts)
  const addLiveAlert = useStore(s => s.addLiveAlert)
  const logout = useStore(s => s.logout)

  const { data: areas = [] } = useQuery({
    queryKey: ['areas'],
    queryFn: () => getAreas(token),
    refetchInterval: 30000,
  })

  const { data: alerts = [] } = useQuery({
    queryKey: ['alerts'],
    queryFn: () => getAlerts(token, { acknowledged: false, limit: 20 }),
    refetchInterval: 15000,
  })

  // WebSocket for real-time alerts
  useEffect(() => {
    const ws = connectAlertWebSocket(token, addLiveAlert)
    return () => ws.close()
  }, [token, addLiveAlert])

  const selectedArea = areas.find(a => a.area_id === selectedAreaId)

  const alertCountBySeverity = (severity: string) =>
    [...liveAlerts, ...alerts].filter(a => a.severity === severity && !a.acknowledged_at).length

  return (
    <div className="min-h-screen bg-gray-100 flex flex-col">
      {/* Header */}
      <header className="bg-blue-900 text-white px-6 py-3 flex justify-between items-center shadow">
        <div>
          <span className="font-bold text-lg">FMMS</span>
          <span className="ml-3 text-sm text-blue-200">{user.email} · {user.role.replace(/_/g, ' ')}</span>
        </div>
        <div className="flex items-center gap-4">
          {alertCountBySeverity('high') > 0 && (
            <span className="bg-red-500 text-white text-xs rounded-full px-2 py-0.5">
              {alertCountBySeverity('high')} critical
            </span>
          )}
          <button onClick={logout} className="text-sm text-blue-200 hover:text-white">Sign out</button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar: area list */}
        <aside className="w-64 bg-white border-r overflow-y-auto">
          <div className="p-4 border-b">
            <h2 className="font-semibold text-gray-700">Areas</h2>
          </div>
          {areas.map(area => {
            const areaAlerts = [...liveAlerts, ...alerts].filter(
              a => a.area_id === area.area_id && !a.acknowledged_at
            )
            const highCount = areaAlerts.filter(a => a.severity === 'high').length
            const medCount = areaAlerts.filter(a => a.severity === 'medium').length
            return (
              <button
                key={area.area_id}
                onClick={() => setSelectedArea(area.area_id)}
                className={`w-full text-left px-4 py-3 border-b hover:bg-gray-50 ${
                  selectedAreaId === area.area_id ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''
                }`}
              >
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-800 truncate">{area.name}</span>
                  <div className="flex gap-1">
                    {highCount > 0 && <AlertBadge severity="high" />}
                    {medCount > 0 && <AlertBadge severity="medium" />}
                  </div>
                </div>
              </button>
            )
          })}
        </aside>

        {/* Main content */}
        <main className="flex-1 flex overflow-hidden">
          {/* Map */}
          <div className={`${selectedAreaId ? 'w-1/2' : 'flex-1'} p-4`}>
            <div className="h-full rounded-xl overflow-hidden shadow">
              <MapView areas={areas} />
            </div>
          </div>

          {/* Area detail panel */}
          {selectedArea && (
            <div className="w-1/2 p-4 overflow-y-auto bg-white border-l">
              <button
                onClick={() => setSelectedArea(null)}
                className="text-xs text-gray-400 hover:text-gray-600 mb-3"
              >
                ← Back to map
              </button>
              <AreaDetail area={selectedArea} />
            </div>
          )}
        </main>

        {/* Right sidebar: live alert feed */}
        <aside className="w-72 bg-white border-l overflow-y-auto">
          <div className="p-4 border-b">
            <h2 className="font-semibold text-gray-700">Live Alerts</h2>
          </div>
          {liveAlerts.length === 0 ? (
            <p className="text-sm text-gray-400 p-4">No live alerts</p>
          ) : (
            liveAlerts.map(alert => (
              <div key={alert.alert_id} className="px-4 py-3 border-b">
                <div className="flex items-center gap-2 mb-1">
                  <AlertBadge severity={alert.severity} />
                  <span className="text-xs text-gray-600">{alert.kind}</span>
                </div>
                <div className="text-xs text-gray-500">{alert.area_id.slice(0, 8)}…</div>
                <div className="text-xs text-gray-400 mt-1">
                  {new Date(alert.ts_emitted).toLocaleTimeString()}
                </div>
              </div>
            ))
          )}
        </aside>
      </div>
    </div>
  )
}
