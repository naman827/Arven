import { CheckCircle2, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { useState } from 'react'

import { ProviderBadge } from '@/components/ProviderBadge'
import { Button } from '@/components/ui/button'
import { useApp } from '@/hooks/useApp'
import { api } from '@/lib/api'
import { cn, PROVIDER_LABEL } from '@/lib/utils'

const ENV_KEY: Record<string, string> = {
  gemini: 'GEMINI_API_KEY',
  nvidia: 'NVIDIA_API_KEY',
  tavily: 'TAVILY_API_KEY',
  duckduckgo: 'ENABLE_DUCKDUCKGO_FALLBACK',
}
const ROLE: Record<string, string> = {
  gemini: 'Primary model',
  nvidia: 'Automatic fallback model',
  tavily: 'Primary web search',
  duckduckgo: 'Best-effort search fallback (unofficial, rate-limited)',
}
const STATE_LABEL: Record<string, string> = {
  ready: 'Ready',
  unavailable: 'Temporarily unavailable',
  key_missing_or_invalid: 'Key missing or invalid',
  not_configured: 'Not configured',
}

interface Row {
  name: string
  configured: boolean
  state: string
  model?: string
  detail?: string | null
}

export function SettingsView() {
  const { status, statusError, refreshStatus } = useApp()
  const [testing, setTesting] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({})

  const rows: Row[] = status
    ? [
        ...status.providers.map((p) => ({
          name: p.name,
          configured: p.configured,
          state: p.state,
          model: p.model,
          detail: p.last_error ? `${p.last_error.message}${p.retry_in_seconds ? ` Retrying in about ${p.retry_in_seconds}s.` : ''}` : null,
        })),
        ...status.search.providers.map((p) => ({ name: p.name, configured: p.configured, state: p.state, detail: p.last_error })),
      ]
    : []

  const test = async (name: string) => {
    setTesting(name)
    try {
      const res = await api.testConnection(name)
      setResults((r) => ({ ...r, [name]: res }))
    } catch (e) {
      setResults((r) => ({ ...r, [name]: { ok: false, message: (e as Error).message } }))
    } finally {
      setTesting(null)
      void refreshStatus()
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="mb-1 text-xl font-semibold">Settings</h1>
            <p className="text-sm text-muted">Provider status. Keys are read from <code className="rounded bg-surface-2 px-1 text-xs">.env</code> on the backend and are never sent to this page.</p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => void refreshStatus()}>
            <RefreshCw /> Refresh
          </Button>
        </div>

        {statusError ? (
          <p role="alert" className="mb-4 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger">
            {statusError}
          </p>
        ) : null}

        <div className="mb-6 rounded-lg border border-border bg-surface p-4">
          <ProviderBadge status={status} error={statusError} />
        </div>

        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {rows.map((row) => {
            const result = results[row.name]
            return (
              <li key={row.name} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{PROVIDER_LABEL[row.name] ?? row.name}</span>
                    <span
                      className={cn(
                        'rounded px-1.5 py-0.5 text-[11px] font-medium',
                        row.state === 'ready' ? 'bg-success-soft text-success' : row.configured ? 'bg-warning-soft text-warning' : 'bg-surface-2 text-muted',
                      )}
                    >
                      {STATE_LABEL[row.state] ?? row.state}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{ROLE[row.name]}</p>
                  <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    <dt className="text-faint">{ENV_KEY[row.name]}</dt>
                    <dd className="text-muted">{row.name === 'duckduckgo' ? (row.configured ? 'enabled' : 'disabled') : row.configured ? 'configured (hidden)' : 'not set'}</dd>
                    {row.model ? (
                      <>
                        <dt className="text-faint">Model</dt>
                        <dd className="break-all text-muted">{row.model}</dd>
                      </>
                    ) : null}
                  </dl>
                  {row.detail ? <p className="mt-2 text-xs text-warning">{row.detail}</p> : null}
                  {result ? (
                    <p role="status" className={cn('mt-2 flex items-start gap-1.5 text-xs', result.ok ? 'text-success' : 'text-danger')}>
                      {result.ok ? <CheckCircle2 className="mt-px size-3.5 shrink-0" /> : <XCircle className="mt-px size-3.5 shrink-0" />}
                      {result.message}
                    </p>
                  ) : null}
                </div>
                <Button variant="secondary" size="sm" onClick={() => void test(row.name)} disabled={testing !== null || !row.configured} aria-label={`Test ${PROVIDER_LABEL[row.name] ?? row.name} connection`}>
                  {testing === row.name ? <Loader2 className="animate-spin" /> : null}
                  {testing === row.name ? 'Testing' : 'Test connection'}
                </Button>
              </li>
            )
          })}
        </ul>

        <section className="mt-8 rounded-lg border border-border bg-surface p-4 text-sm">
          <h2 className="mb-2 font-semibold">Changing keys or models</h2>
          <ol className="list-decimal space-y-1.5 pl-5 text-muted">
            <li>
              Open the <code className="rounded bg-surface-2 px-1 text-xs">.env</code> file in the project root (copy <code className="rounded bg-surface-2 px-1 text-xs">.env.example</code> if it does not exist).
            </li>
            <li>
              Set <code className="rounded bg-surface-2 px-1 text-xs">GEMINI_API_KEY</code>, <code className="rounded bg-surface-2 px-1 text-xs">NVIDIA_API_KEY</code>, and <code className="rounded bg-surface-2 px-1 text-xs">TAVILY_API_KEY</code>. Optional: <code className="rounded bg-surface-2 px-1 text-xs">GEMINI_MODEL</code>, <code className="rounded bg-surface-2 px-1 text-xs">NVIDIA_MODEL</code>.
            </li>
            <li>Restart the backend (stop it with Ctrl+C, then start it again).</li>
            <li>Come back here and press Test connection for each provider.</li>
          </ol>
          <p className="mt-3 text-xs text-faint">
            When Gemini hits a rate limit or quota, ARVEN AI switches to NVIDIA automatically and returns to Gemini after a cooldown. Research budgets: up to {status?.budgets.max_search_rounds ?? '-'} search rounds, {status?.budgets.max_unique_sources ?? '-'} sources, {status?.budgets.max_report_words ?? '-'} report words.
          </p>
        </section>
      </div>
    </div>
  )
}
