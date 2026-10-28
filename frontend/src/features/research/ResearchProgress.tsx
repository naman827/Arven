import { AlertTriangle, Check, ChevronDown, Circle, Loader2, Plus, Search, Square, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Markdown } from '@/components/Markdown'
import { SourceList } from '@/components/SourceList'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { cn, PROVIDER_LABEL } from '@/lib/utils'

import { useResearchJob, type JobState } from './useResearchJob'

const STEPS = [
  { key: 'planning', label: 'Planning' },
  { key: 'searching', label: 'Searching' },
  { key: 'reading', label: 'Reading sources' },
  { key: 'cross_checking', label: 'Cross-checking' },
  { key: 'synthesizing', label: 'Writing report' },
  { key: 'verifying', label: 'Verifying citations' },
] as const

function stepIndex(state: JobState): number {
  if (state.status === 'completed') return STEPS.length
  if (state.status === 'synthesizing' && state.stage === 'verifying_citations') return 5
  const s = state.status === 'awaiting_plan_approval' ? 'planning' : state.status
  const i = STEPS.findIndex((x) => x.key === s)
  return i === -1 ? 0 : i
}

export function ResearchProgress({ jobId, onFinished }: { jobId: string; onFinished: () => void }) {
  const state = useResearchJob(jobId, onFinished)
  const [cancelling, setCancelling] = useState(false)
  const [showQueries, setShowQueries] = useState(false)
  const [showDraft, setShowDraft] = useState(false)
  const sources = useMemo(() => Object.values(state.sources).sort((a, b) => a.number - b.number), [state.sources])
  const read = sources.filter((s) => s.readable === true).length
  const active = !['completed', 'failed', 'cancelled'].includes(state.status)
  const current = stepIndex(state)

  return (
    <section aria-label="Deep research progress" className="rounded-lg border border-border bg-surface">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          {active ? <Loader2 className="size-4 animate-spin text-accent" aria-hidden /> : null}
          Deep Research
          <span className="text-xs font-normal text-muted" aria-live="polite">
            {state.status === 'awaiting_plan_approval' ? 'waiting for your plan review' : active ? STEPS[Math.min(current, STEPS.length - 1)].label.toLowerCase() : state.status}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {state.provider ? <span className="text-xs text-faint">Model: {PROVIDER_LABEL[state.provider] ?? state.provider}</span> : null}
          {active ? (
            <Button
              size="sm"
              variant="secondary"
              disabled={cancelling}
              onClick={async () => {
                setCancelling(true)
                try {
                  await api.cancelJob(jobId)
                } finally {
                  setCancelling(false)
                }
              }}
            >
              <Square className="size-3 fill-current" /> {cancelling ? 'Cancelling' : 'Cancel'}
            </Button>
          ) : null}
        </div>
      </header>

      <div className="grid gap-5 p-4 md:grid-cols-[200px_1fr]">
        <ol className="space-y-2.5" aria-label="Steps">
          {STEPS.map((step, i) => {
            const done = i < current || state.status === 'completed'
            const running = i === current && active
            const failed = i === current && state.status === 'failed'
            return (
              <li key={step.key} className="flex items-center gap-2.5 text-sm" aria-current={running ? 'step' : undefined}>
                <span
                  className={cn(
                    'flex size-5 shrink-0 items-center justify-center rounded-full border',
                    done && 'border-success bg-success text-white',
                    running && 'border-accent text-accent',
                    failed && 'border-danger bg-danger text-white',
                    !done && !running && !failed && 'border-border-strong text-faint',
                  )}
                >
                  {done ? <Check className="size-3" /> : running ? <Loader2 className="size-3 animate-spin" /> : failed ? <X className="size-3" /> : <Circle className="size-1.5 fill-current" />}
                </span>
                <span className={cn(done || running ? 'text-fg' : 'text-muted')}>{step.label}</span>
              </li>
            )
          })}
        </ol>

        <div className="min-w-0 space-y-4 text-sm">
          {state.status === 'awaiting_plan_approval' && state.plan ? (
            <PlanReview jobId={jobId} initial={state.plan.subquestions.map((s) => s.question)} />
          ) : state.plan ? (
            <div>
              <h4 className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">Plan</h4>
              <ol className="list-decimal space-y-1 pl-5 text-muted">
                {state.plan.subquestions.map((s) => (
                  <li key={s.question}>{s.question}</li>
                ))}
              </ol>
            </div>
          ) : active ? (
            <p className="text-muted">Breaking the question into subquestions...</p>
          ) : null}

          {state.queries.length ? (
            <div>
              <button
                onClick={() => setShowQueries((v) => !v)}
                aria-expanded={showQueries}
                className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-faint uppercase hover:text-fg"
              >
                <Search className="size-3" /> {state.queries.length} searches
                <ChevronDown className={cn('size-3 transition-transform', showQueries && 'rotate-180')} />
              </button>
              {showQueries ? (
                <ul className="mt-1.5 space-y-0.5 text-xs text-muted">
                  {state.queries.map((q, i) => (
                    <li key={i} className="truncate">
                      {q.round && q.round > 1 ? <span className="mr-1 text-warning">follow-up</span> : null}
                      {q.query}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}

          {state.gaps.length ? (
            <div className="rounded-md border border-border bg-warning-soft px-3 py-2 text-xs">
              <p className="mb-1 font-medium text-warning">Gaps found, running targeted follow-up searches</p>
              <ul className="space-y-0.5 text-muted">
                {state.gaps.map((g, i) => (
                  <li key={i}>
                    {g.subquestion} (coverage {Math.round(g.coverage * 100)}%){g.conflicts.length ? `; conflict: ${g.conflicts[0]}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {sources.length ? (
            <div>
              <h4 className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">
                Sources: {sources.length} found, {read} read
              </h4>
              <div className="max-h-72 overflow-y-auto pr-1">
                <SourceList sources={sources} scope={`job-${jobId}`} compact />
              </div>
            </div>
          ) : null}

          {state.draft && active ? (
            <div>
              <button
                onClick={() => setShowDraft((v) => !v)}
                aria-expanded={showDraft}
                className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-faint uppercase hover:text-fg"
              >
                Draft preview (before citation verification)
                <ChevronDown className={cn('size-3 transition-transform', showDraft && 'rotate-180')} />
              </button>
              {showDraft ? (
                <div className="mt-2 max-h-80 overflow-y-auto rounded-md border border-border bg-bg-subtle p-3">
                  <Markdown content={state.draft} streaming />
                </div>
              ) : null}
            </div>
          ) : null}

          {state.searchErrors.length && active ? (
            <p className="flex items-start gap-1.5 text-xs text-warning">
              <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {state.searchErrors.length} search request(s) failed; continuing with the rest.
            </p>
          ) : null}

          {state.status === 'failed' ? (
            <p role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-danger">
              {state.error ?? 'Research failed.'}
            </p>
          ) : null}
          {state.status === 'cancelled' ? <p className="text-muted">Research was cancelled.</p> : null}
        </div>
      </div>
    </section>
  )
}

function PlanReview({ jobId, initial }: { jobId: string; initial: string[] }) {
  const [items, setItems] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const valid = items.map((s) => s.trim()).filter(Boolean)
  return (
    <div className="rounded-md border border-accent/40 bg-accent-soft/40 p-3">
      <h4 className="mb-2 text-sm font-medium">Review the research plan</h4>
      <p className="mb-3 text-xs text-muted">Edit, remove, or add subquestions (up to 7), then start the research.</p>
      <ol className="space-y-2">
        {items.map((q, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="w-4 text-right text-xs text-faint">{i + 1}.</span>
            <input
              value={q}
              aria-label={`Subquestion ${i + 1}`}
              onChange={(e) => setItems((all) => all.map((x, j) => (j === i ? e.target.value : x)))}
              className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface px-2 text-sm focus:border-accent focus:outline-none"
            />
            <Button variant="ghost" size="icon-sm" onClick={() => setItems((all) => all.filter((_, j) => j !== i))} aria-label={`Remove subquestion ${i + 1}`} disabled={items.length <= 1}>
              <Trash2 />
            </Button>
          </li>
        ))}
      </ol>
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => setItems((all) => [...all, ''])} disabled={items.length >= 7}>
          <Plus /> Add subquestion
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={busy || valid.length === 0}
          onClick={async () => {
            setBusy(true)
            setError(null)
            try {
              await api.approvePlan(jobId, valid)
            } catch (e) {
              setError((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
        >
          Start research
        </Button>
      </div>
    </div>
  )
}
