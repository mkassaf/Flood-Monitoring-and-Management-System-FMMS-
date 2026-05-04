
const colors: Record<string, string> = {
  high: 'bg-red-100 text-red-800 border-red-300',
  medium: 'bg-orange-100 text-orange-800 border-orange-300',
  low: 'bg-yellow-100 text-yellow-800 border-yellow-300',
}

export function AlertBadge({ severity }: { severity: string }) {
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${colors[severity] ?? 'bg-gray-100 text-gray-700'}`}>
      {severity}
    </span>
  )
}
