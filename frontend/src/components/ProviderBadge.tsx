import type { SystemStatus } from '@/lib/api'
import { cn } from '@/lib/utils'

const OVERALL: Record<SystemStatus['overall'], { label: string; tone: string }> = {
  gemini_active: { label: 'Gemini active', tone: 'bg-success' },
  nvidia_fallback_active: { label: 'NVIDIA fallback active', tone: 'bg-warning' },
  unavailable: { label: 'Models unavailable', tone: 'bg-danger' },
  key_missing_or_invalid: { label: 'API key missing or invalid', tone: 'bg-danger' },
}

export function ProviderBadge({ status, error, compact }: { status: SystemStatus | null; error: string | null; compact?: boolean }) {
  const info = error
    ? { label: 'Backend offline', tone: 'bg-danger' }
    : status
      ? OVERALL[status.overall]
      : { label: 'Checking providers', tone: 'bg-faint' }
  const search = status && !error ? (status.search.available ? 'Web search ready' : 'Web search unavailable') : null
  return (
    <div className="flex min-w-0 flex-col gap-0.5" aria-live="polite">
      <span className="flex items-center gap-2 text-xs text-fg">
        <span className={cn('size-2 shrink-0 rounded-full', info.tone)} aria-hidden />
        <span className="truncate">{info.label}</span>
      </span>
      {!compact && search ? (
        <span className="flex items-center gap-2 text-xs text-muted">
          <span className={cn('size-2 shrink-0 rounded-full', status?.search.available ? 'bg-success' : 'bg-warning')} aria-hidden />
          <span className="truncate">{search}</span>
        </span>
      ) : null}
    </div>
  )
}
