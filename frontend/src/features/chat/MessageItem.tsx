import { AlertTriangle, Check, Copy, FileText, RotateCcw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { Markdown } from '@/components/Markdown'
import { PdfDownloadButton } from '@/components/PdfDownloadButton'
import { focusSource, SourceList } from '@/components/SourceList'
import { Button } from '@/components/ui/button'
import { Tip } from '@/components/ui/overlays'
import { useApp } from '@/hooks/useApp'
import type { Message, SourceInfo, Verification } from '@/lib/api'
import { copyText, MODE_LABEL, PROVIDER_LABEL } from '@/lib/utils'

export function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-lg bg-surface-2 px-4 py-2.5 text-[15px] whitespace-pre-wrap break-words">{content}</div>
    </div>
  )
}

export function VerificationSummary({ v }: { v: Verification }) {
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted">
      <ShieldCheck className="size-3.5 text-success" aria-hidden />
      Citation check: {v.claims_checked} of {v.claims_total} cited claims checked against stored evidence; {v.removed} unsupported removed
      {v.invalid_citations_removed ? `, ${v.invalid_citations_removed} invalid citation(s) dropped` : ''}
      {v.not_checked ? `, ${v.not_checked} not checked (budget)` : ''}.
    </p>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Tip label={copied ? 'Copied' : 'Copy'}>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={copied ? 'Copied' : 'Copy message'}
        onClick={async () => {
          if (await copyText(text)) {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1500)
          }
        }}
      >
        {copied ? <Check /> : <Copy />}
      </Button>
    </Tip>
  )
}

export function AssistantBody({
  content,
  sources,
  scope,
  streaming,
}: {
  content: string
  sources: SourceInfo[]
  scope: string
  streaming?: boolean
}) {
  return (
    <div className="space-y-3">
      {content ? (
        <Markdown content={content} sources={sources} onCitation={(n) => focusSource(scope, n)} streaming={streaming} />
      ) : null}
      {sources.length ? (
        <details className="group" open={!streaming}>
          <summary className="cursor-pointer text-xs font-medium tracking-wide text-faint uppercase select-none hover:text-fg">
            Sources ({sources.filter((s) => s.readable).length} read of {sources.length})
          </summary>
          <div className="mt-2">
            <SourceList sources={sources} scope={scope} />
          </div>
        </details>
      ) : null}
    </div>
  )
}

export function MessageItem({ message, isLast, onRegenerate, busy }: { message: Message; isLast: boolean; onRegenerate: () => void; busy: boolean }) {
  const { navigate } = useApp()
  if (message.role === 'user') return <UserMessage content={message.content} />

  const reportId = message.meta.report_id
  const sources = message.meta.sources ?? []
  const failed = message.status === 'error'
  const canRegenerate = isLast && !busy && message.mode !== 'deep_research'

  return (
    <article className="space-y-2" aria-label="Assistant message">
      {reportId ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
              <FileText className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-faint">Deep Research report</p>
              <h3 className="truncate font-medium">{message.meta.title ?? 'Research report'}</h3>
              {message.meta.verification?.ran ? (
                <div className="mt-1">
                  <VerificationSummary v={message.meta.verification} />
                </div>
              ) : null}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="primary" onClick={() => navigate({ view: 'report', id: reportId })}>
              Open report
            </Button>
            <PdfDownloadButton reportId={reportId} label="Download PDF" variant="secondary" />
          </div>
        </div>
      ) : failed ? (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-sm text-danger">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{message.meta.error ?? message.content}</span>
        </div>
      ) : (
        <AssistantBody content={message.content} sources={sources} scope={message.id} />
      )}
      <div className="flex flex-wrap items-center gap-1 text-xs text-faint">
        {!failed ? <CopyButton text={message.content} /> : null}
        {canRegenerate ? (
          <Tip label={failed ? 'Retry' : 'Regenerate'}>
            <Button variant="ghost" size="icon-sm" onClick={onRegenerate} aria-label={failed ? 'Retry' : 'Regenerate response'}>
              <RotateCcw />
            </Button>
          </Tip>
        ) : null}
        <span className="ml-1">
          {MODE_LABEL[message.mode as keyof typeof MODE_LABEL] ?? message.mode}
          {message.provider ? ` · ${PROVIDER_LABEL[message.provider] ?? message.provider}` : ''}
          {message.model ? ` (${message.model})` : ''}
        </span>
        {message.status === 'stopped' ? <span className="ml-1 rounded border border-border px-1">stopped</span> : null}
        {message.status === 'cancelled' ? <span className="ml-1 rounded border border-border px-1">cancelled</span> : null}
      </div>
    </article>
  )
}
