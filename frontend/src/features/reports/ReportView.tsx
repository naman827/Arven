import { ArrowLeft, Check, Copy, FileText, Loader2, MessageSquare, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Markdown } from '@/components/Markdown'
import { PdfDownloadButton } from '@/components/PdfDownloadButton'
import { focusSource, SourceList } from '@/components/SourceList'
import { Button } from '@/components/ui/button'
import { useApp } from '@/hooks/useApp'
import { VerificationSummary } from '@/features/chat/MessageItem'
import { api, type Report, type ReportSummary } from '@/lib/api'
import { copyText, PROVIDER_LABEL, slugify } from '@/lib/utils'

export function ReportsList() {
  const { navigate } = useApp()
  const [reports, setReports] = useState<ReportSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.listReports().then(setReports, (e: Error) => setError(e.message))
  }, [])
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="mb-1 text-xl font-semibold">Reports</h1>
        <p className="mb-6 text-sm text-muted">Deep Research reports with verified citations. Open one to read, copy, or download it as PDF.</p>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {reports === null && !error ? <Loader2 className="size-5 animate-spin text-muted" /> : null}
        {reports?.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted">
            No reports yet. Choose <strong className="text-fg">Deep Research</strong> in the composer to create one.
          </div>
        ) : null}
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {reports?.map((r) => (
            <li key={r.id}>
              <button onClick={() => navigate({ view: 'report', id: r.id })} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-hover">
                <FileText className="size-4 shrink-0 text-accent" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{r.title}</span>
                <span className="shrink-0 text-xs text-faint">{new Date(r.created_at).toLocaleDateString()}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export function ReportView({ id }: { id: string }) {
  const { navigate } = useApp()
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [panel, setPanel] = useState(() => window.innerWidth >= 1280)

  useEffect(() => {
    let current = true // a slow response for a previous report must not replace this one
    setReport(null)
    setError(null)
    api.getReport(id).then(
      (r) => current && setReport(r),
      (e: Error) => current && setError(e.message),
    )
    return () => {
      current = false
    }
  }, [id])

  const toc = useMemo(
    () =>
      (report?.markdown.match(/^##\s+.+$/gm) ?? [])
        .map((h) => h.replace(/^##\s+/, '').trim())
        .filter((h) => h.toLowerCase() !== 'references'),
    [report],
  )

  if (error) return <div className="p-8 text-sm text-danger">{error}</div>
  if (!report)
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted">
        <Loader2 className="size-4 animate-spin" /> Loading report...
      </div>
    )

  const scope = `report-${report.id}`
  const onCitation = (n: number) => {
    setPanel(true)
    window.setTimeout(() => focusSource(scope, n), 50)
  }

  return (
    <div className="flex h-full min-w-0">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-border bg-bg/95 px-4 py-2 backdrop-blur">
          <Button variant="ghost" size="sm" onClick={() => navigate({ view: 'reports' })}>
            <ArrowLeft /> Reports
          </Button>
          <div className="ml-auto flex flex-wrap gap-2">
            {report.conversation_id ? (
              <Button variant="secondary" size="sm" onClick={() => navigate({ view: 'chat', id: report.conversation_id! })}>
                <MessageSquare /> Continue discussion
              </Button>
            ) : null}
            <Button
              variant="secondary"
              size="sm"
              onClick={async () => {
                if (await copyText(report.markdown)) {
                  setCopied(true)
                  window.setTimeout(() => setCopied(false), 1500)
                }
              }}
            >
              {copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy'}
            </Button>
            <PdfDownloadButton reportId={report.id} label="PDF" variant="primary" />
            <Button variant="ghost" size="icon-sm" onClick={() => setPanel((p) => !p)} aria-label={panel ? 'Hide sources panel' : 'Show sources panel'} aria-expanded={panel}>
              {panel ? <PanelRightClose /> : <PanelRightOpen />}
            </Button>
          </div>
        </div>
        <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
          <div className="mb-6 space-y-1.5 rounded-md border border-border bg-bg-subtle px-3 py-2.5">
            {report.verification?.ran ? <VerificationSummary v={report.verification} /> : <p className="text-xs text-muted">Citation verification did not run for this report.</p>}
            <p className="text-xs text-faint">
              {report.sources.filter((s) => s.readable).length} sources read of {report.sources.length} found
              {report.provider ? ` · written with ${PROVIDER_LABEL[report.provider] ?? report.provider}` : ''} · {new Date(report.created_at).toLocaleString()}
            </p>
          </div>
          {toc.length > 2 ? (
            <nav aria-label="Table of contents" className="mb-8">
              <h2 className="mb-2 text-xs font-medium tracking-wide text-faint uppercase">Contents</h2>
              <ol className="space-y-1 text-sm">
                {toc.map((h) => (
                  <li key={h}>
                    <a href={`#sec-${slugify(h)}`} onClick={(e) => { e.preventDefault(); document.getElementById(`sec-${slugify(h)}`)?.scrollIntoView({ behavior: 'smooth' }) }} className="text-muted hover:text-accent">
                      {h}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}
          <Markdown content={report.markdown} sources={report.sources} onCitation={onCitation} anchors />
        </div>
      </div>
      {panel ? (
        <aside aria-label="Sources" className="fixed inset-y-0 right-0 z-30 w-[min(22rem,100vw)] overflow-y-auto border-l border-border bg-bg-subtle p-4 shadow-md xl:static xl:z-auto xl:shadow-none">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Sources ({report.sources.length})</h2>
            <Button variant="ghost" size="icon-sm" onClick={() => setPanel(false)} aria-label="Close sources panel">
              <PanelRightClose />
            </Button>
          </div>
          <SourceList sources={report.sources} scope={scope} compact />
        </aside>
      ) : null}
    </div>
  )
}
