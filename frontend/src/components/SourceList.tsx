import { AlertTriangle, ExternalLink } from 'lucide-react'

import type { SourceInfo } from '@/lib/api'
import { cn, PROVIDER_LABEL } from '@/lib/utils'

const TYPE_LABEL: Record<string, string> = {
  academic: 'Academic',
  preprint: 'Preprint',
  government: 'Government',
  institution: 'Institution',
  encyclopedia: 'Encyclopedia',
}

export function sourceAnchor(scope: string, n: number) {
  return `src-${scope}-${n}`
}

export function focusSource(scope: string, n: number) {
  const el = document.getElementById(sourceAnchor(scope, n))
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  el.classList.add('ring-2', 'ring-accent')
  window.setTimeout(() => el.classList.remove('ring-2', 'ring-accent'), 1600)
}

export function SourceCard({ source, scope, compact }: { source: SourceInfo; scope: string; compact?: boolean }) {
  const unreadable = source.readable === false
  const provider = source.provider ?? source.search_provider
  return (
    <li
      id={sourceAnchor(scope, source.number)}
      className={cn('rounded-md border border-border bg-surface p-3 transition-shadow', unreadable && 'opacity-75')}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded bg-accent-soft px-1 text-[11px] font-semibold text-accent">
          {source.number}
        </span>
        <div className="min-w-0 flex-1">
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex max-w-full items-center gap-1 text-sm font-medium text-fg hover:text-accent"
          >
            <span className="truncate">{source.title || source.url}</span>
            <ExternalLink className="size-3 shrink-0 text-faint group-hover:text-accent" aria-hidden />
            <span className="sr-only">(opens in new tab)</span>
          </a>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
            <span className="truncate">{source.domain}</span>
            {source.published_date ? <span>{source.published_date.slice(0, 10)}</span> : null}
            {source.source_type && TYPE_LABEL[source.source_type] ? (
              <span className="rounded border border-border px-1 text-[11px]">{TYPE_LABEL[source.source_type]}</span>
            ) : null}
            {provider ? <span className="text-faint">via {PROVIDER_LABEL[provider] ?? provider}</span> : null}
          </div>
          {unreadable ? (
            <p className="mt-1 flex items-center gap-1 text-xs text-warning">
              <AlertTriangle className="size-3" aria-hidden /> Not read: {source.error || 'unreadable'}
            </p>
          ) : !compact && source.snippet ? (
            <p className="mt-1 line-clamp-2 text-xs text-muted">{source.snippet}</p>
          ) : null}
        </div>
      </div>
    </li>
  )
}

export function SourceList({ sources, scope, compact }: { sources: SourceInfo[]; scope: string; compact?: boolean }) {
  if (!sources.length) return null
  return (
    <ul className={cn('grid gap-2', compact ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2')}>
      {sources.map((s) => (
        <SourceCard key={s.number} source={s} scope={scope} compact={compact} />
      ))}
    </ul>
  )
}
