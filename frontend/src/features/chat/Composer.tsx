import { ArrowUp, FileText, Loader2, Paperclip, Square, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Tip } from '@/components/ui/overlays'
import { api, type DocumentInfo, type Mode } from '@/lib/api'
import { cn, MODE_LABEL } from '@/lib/utils'

const MODES: Mode[] = ['chat', 'research', 'deep_research']
const MODE_HINT: Record<Mode, string> = {
  chat: 'Conversation with the model. No web search.',
  research: 'One web search round, reads top sources, answers with citations.',
  deep_research: 'Multi-step plan, several search rounds, cross-checking, verified report.',
}

export interface SubmitPayload {
  text: string
  documents: DocumentInfo[]
  reviewPlan: boolean
  focus: 'general' | 'academic'
}

export function ModeSwitch({ mode, onChange, disabled }: { mode: Mode; onChange: (m: Mode) => void; disabled?: boolean }) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = MODES.indexOf(mode)
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const next = MODES[(i + (e.key === 'ArrowRight' ? 1 : MODES.length - 1)) % MODES.length]
      onChange(next)
      document.getElementById(`mode-${next}`)?.focus()
    }
  }
  return (
    <div role="radiogroup" aria-label="Mode" onKeyDown={onKey} className="inline-flex rounded-md border border-border bg-bg-subtle p-0.5">
      {MODES.map((m) => (
        <Tip key={m} label={MODE_HINT[m]}>
          <button
            id={`mode-${m}`}
            type="button"
            role="radio"
            aria-checked={mode === m}
            tabIndex={mode === m ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(m)}
            className={cn(
              'h-7 rounded px-2.5 text-xs font-medium whitespace-nowrap transition-colors disabled:opacity-50 sm:px-3',
              mode === m ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
            )}
          >
            {MODE_LABEL[m]}
          </button>
        </Tip>
      ))}
    </div>
  )
}

export function Composer({
  mode,
  onModeChange,
  onSubmit,
  busy,
  onStop,
  autoFocus,
  placeholder,
}: {
  mode: Mode
  onModeChange: (m: Mode) => void
  onSubmit: (p: SubmitPayload) => void
  busy: boolean
  onStop?: () => void
  autoFocus?: boolean
  placeholder?: string
}) {
  const [text, setText] = useState('')
  const [docs, setDocs] = useState<DocumentInfo[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [reviewPlan, setReviewPlan] = useState(false)
  const [academic, setAcademic] = useState(false)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const el = textRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`
  }, [text])

  const canSend = text.trim().length > 0 && !busy && !uploading && (mode !== 'deep_research' || text.trim().length >= 3)

  const submit = () => {
    if (!canSend) return
    onSubmit({ text: text.trim(), documents: docs, reviewPlan, focus: academic ? 'academic' : 'general' })
    setText('')
  }

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setUploadError(null)
    setUploading(true)
    try {
      for (const file of Array.from(files).slice(0, 5 - docs.length)) {
        const doc = await api.uploadDocument(file)
        setDocs((d) => [...d, doc])
        if (!doc.has_text) setUploadError(`"${doc.filename}" looks like a scanned PDF with no text layer. OCR is not supported yet.`)
      }
    } catch (e) {
      setUploadError((e as Error).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div
      className="rounded-lg border border-border bg-surface shadow-sm focus-within:border-border-strong"
      onDragOver={(e) => {
        if (mode !== 'deep_research') e.preventDefault()
      }}
      onDrop={(e) => {
        if (mode === 'deep_research') return
        e.preventDefault()
        void upload(e.dataTransfer.files)
      }}
    >
      {docs.length > 0 && mode !== 'deep_research' ? (
        <ul className="flex flex-wrap gap-1.5 px-3 pt-3" aria-label="Attached documents">
          {docs.map((d) => (
            <li key={d.id} className="flex max-w-full items-center gap-1.5 rounded-md border border-border bg-bg-subtle py-1 pr-1 pl-2 text-xs">
              <FileText className="size-3.5 shrink-0 text-muted" aria-hidden />
              <span className="truncate">{d.filename}</span>
              <span className="text-faint">{d.page_count}p</span>
              <button
                type="button"
                onClick={() => setDocs((all) => all.filter((x) => x.id !== d.id))}
                className="rounded p-0.5 text-faint hover:bg-surface-hover hover:text-fg"
                aria-label={`Remove ${d.filename}`}
              >
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <label htmlFor="composer-input" className="sr-only">
        Message
      </label>
      <textarea
        id="composer-input"
        ref={textRef}
        autoFocus={autoFocus}
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={
          placeholder ??
          (mode === 'deep_research'
            ? 'Describe what you want researched in depth...'
            : mode === 'research'
              ? 'Ask a question to research on the web...'
              : 'Message ARVEN AI...')
        }
        className="block max-h-60 min-h-[3.25rem] w-full resize-none bg-transparent px-4 pt-3 pb-1 text-[15px] placeholder:text-faint focus:outline-none"
      />
      {uploadError ? <p className="px-4 pb-1 text-xs text-warning">{uploadError}</p> : null}
      <div className="flex flex-wrap items-center gap-2 px-2.5 pt-1 pb-2.5">
        <ModeSwitch mode={mode} onChange={onModeChange} disabled={busy} />
        {mode === 'deep_research' ? (
          <div className="flex flex-wrap items-center gap-3 pl-1 text-xs text-muted">
            <Toggle checked={reviewPlan} onChange={setReviewPlan} label="Review plan" hint="Pause after planning so you can edit the subquestions" />
            <Toggle checked={academic} onChange={setAcademic} label="Academic focus" hint="Prefer papers, institutions and DOIs; label preprints" />
          </div>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">
          {mode !== 'deep_research' ? (
            <>
              <input ref={fileRef} type="file" accept="application/pdf,.pdf" multiple hidden onChange={(e) => void upload(e.target.files)} />
              <Tip label="Attach PDF (or drag and drop)">
                <Button variant="ghost" size="icon-sm" type="button" onClick={() => fileRef.current?.click()} disabled={uploading || docs.length >= 5} aria-label="Attach PDF">
                  {uploading ? <Loader2 className="animate-spin" /> : <Paperclip />}
                </Button>
              </Tip>
            </>
          ) : null}
          {busy && onStop ? (
            <Button variant="secondary" size="icon-sm" type="button" onClick={onStop} aria-label="Stop generating">
              <Square className="fill-current" />
            </Button>
          ) : (
            <Button variant="primary" size="icon-sm" type="button" onClick={submit} disabled={!canSend} aria-label={mode === 'deep_research' ? 'Start deep research' : 'Send message'}>
              <ArrowUp />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint: string }) {
  return (
    <Tip label={hint}>
      <div className="inline-flex cursor-pointer items-center gap-1.5 select-none">
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          aria-label={label}
          onClick={() => onChange(!checked)}
          className={cn('relative h-4 w-7 rounded-full transition-colors', checked ? 'bg-accent' : 'bg-border-strong')}
        >
          <span className={cn('absolute top-0.5 left-0.5 size-3 rounded-full bg-white transition-transform', checked && 'translate-x-3')} />
        </button>
        <span onClick={() => onChange(!checked)} aria-hidden>
          {label}
        </span>
      </div>
    </Tip>
  )
}
