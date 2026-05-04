import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAlerts, acknowledgeAlert } from '../api'
import { useStore } from '../store'
import { AlertBadge } from './AlertBadge'
import type { Area } from '../types'

export function AreaDetail({ area }: { area: Area }) {
  const token = useStore(s => s.token)!
  const qc = useQueryClient()

  const { data: alerts = [] } = useQuery({
    queryKey: ['alerts', area.area_id],
    queryFn: () => getAlerts(token, { acknowledged: false }),
    refetchInterval: 10000,
    select: (all) => all.filter(a => a.area_id === area.area_id).slice(0, 10),
  })

  const ackMutation = useMutation({
    mutationFn: ({ id }: { id: string }) => acknowledgeAlert(token, id, 'Acknowledged via dashboard'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const summary = area.live_summary

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-gray-800">{area.name}</h2>
        <span className="text-sm text-gray-500">Risk: {area.risk_profile}</span>
      </div>

      {summary && (
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-blue-50 rounded-lg p-3">
            <div className="text-xs text-gray-500">Max Water Level</div>
            <div className="text-lg font-bold text-blue-700">
              {summary.max_water_level_m != null ? `${Number(summary.max_water_level_m).toFixed(2)} m` : '—'}
            </div>
          </div>
          <div className="bg-green-50 rounded-lg p-3">
            <div className="text-xs text-gray-500">Active Sensors</div>
            <div className="text-lg font-bold text-green-700">{summary.sensor_count}</div>
          </div>
        </div>
      )}

      <div>
        <h3 className="font-semibold text-gray-700 mb-2">Recent Alerts</h3>
        {alerts.length === 0 ? (
          <p className="text-sm text-gray-400">No active alerts</p>
        ) : (
          <div className="space-y-2">
            {alerts.map(alert => (
              <div key={alert.alert_id} className="border rounded-lg p-3 bg-white flex justify-between items-center">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <AlertBadge severity={alert.severity} />
                    <span className="text-sm font-medium">{alert.kind}</span>
                  </div>
                  <div className="text-xs text-gray-500">
                    {alert.parameter ?? 'area'} {alert.value != null && `= ${Number(alert.value).toFixed(2)}`}
                  </div>
                </div>
                <button
                  onClick={() => ackMutation.mutate({ id: alert.alert_id })}
                  className="text-xs bg-gray-100 hover:bg-gray-200 px-3 py-1 rounded-full"
                >
                  Ack
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
