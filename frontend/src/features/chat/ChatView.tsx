import { AlertTriangle, BookOpenCheck, Globe, Loader2, MessageSquare } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useApp } from '@/hooks/useApp'
import { ResearchProgress } from '@/features/research/ResearchProgress'
import { api, ApiError, streamChat, type ConversationDetail, type Mode, type SourceInfo } from '@/lib/api'
import { cn, MODE_LABEL, PROVIDER_LABEL } from '@/lib/utils'

import { Composer, type SubmitPayload } from './Composer'
import { AssistantBody, MessageItem, UserMessage } from './MessageItem'

interface LiveTurn {
  userText: string | null
  content: string
  sources: Record<number, SourceInfo>
  phase: string
  queries: string[]
  provider: string | null
  error: string | null
  resets: number
}

const PHASE_LABEL: Record<string, string> = {
  starting: 'Starting',
  searching: 'Searching the web',
  reading: 'Reading sources',
  synthesizing: 'Writing answer',
  generating: 'Generating',
}

export function ChatView({ conversationId }: { conversationId: string | null }) {
  const { navigate, refreshConversations, refreshStatus, status } = useApp()
  const [conv, setConv] = useState<ConversationDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>('chat')
  const [live, setLive] = useState<LiveTurn | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const ownIdRef = useRef<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  const load = useCallback(async (id: string) => {
    setLoadError(null)
    try {
      const detail = await api.getConversation(id)
      setConv(detail)
      setMode(detail.mode)
    } catch (e) {
      setLoadError(e instanceof ApiError && e.status === 404 ? 'This conversation no longer exists.' : (e as Error).message)
      setConv(null)
    }
  }, [])

  useEffect(() => {
    if (conversationId && conversationId === ownIdRef.current) return // we created it mid-stream
    abortRef.current?.abort()
    ownIdRef.current = null
    setLive(null)
    setSendError(null)
    if (!conversationId) {
      setConv(null)
      setLoadError(null)
      return
    }
    setLoading(true)
    void load(conversationId).finally(() => setLoading(false))
  }, [conversationId, load])

  useEffect(() => {
    if (stickRef.current) bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [conv?.messages.length, live?.content, live?.phase, conv?.active_job_id])

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
  }

  const changeMode = (m: Mode) => {
    setMode(m)
    if (conv) void api.setConversationMode(conv.id, m).catch(() => undefined)
  }

  const finishTurn = async (id: string | null) => {
    if (id) await load(id)
    setLive(null)
    abortRef.current = null
    ownIdRef.current = null
    void refreshConversations()
    void refreshStatus()
  }

  const runStream = async (body: Parameters<typeof streamChat>[0], userText: string | null) => {
    const controller = new AbortController()
    abortRef.current = controller
    stickRef.current = true
    setSendError(null)
    setLive({ userText, content: '', sources: {}, phase: body.mode === 'research' ? 'searching' : 'starting', queries: [], provider: null, error: null, resets: 0 })
    let id = body.conversation_id ?? null
    try {
      const events = await streamChat(body, controller.signal)
      for await (const ev of events) {
        const d = ev.data
        setLive((prev) => {
          if (!prev) return prev
          switch (ev.type) {
            case 'provider':
              return { ...prev, provider: String(d.provider), phase: prev.phase === 'starting' ? 'generating' : prev.phase }
            case 'status':
              return { ...prev, phase: String(d.status) }
            case 'query':
              return { ...prev, queries: [...prev.queries, String(d.query)] }
            case 'source_found':
              return { ...prev, sources: { ...prev.sources, [Number(d.number)]: d as unknown as SourceInfo } }
            case 'source_read': {
              const n = Number(d.number)
              const s = prev.sources[n]
              return s ? { ...prev, sources: { ...prev.sources, [n]: { ...s, readable: Boolean(d.readable), error: (d.error as string) ?? null } } } : prev
            }
            case 'token':
              return { ...prev, content: prev.content + String(d.text ?? '') }
            case 'reset':
              return { ...prev, content: '', resets: prev.resets + 1 }
            case 'error':
              return { ...prev, error: String(d.message) }
            case 'done':
              return { ...prev, content: typeof d.content === 'string' ? d.content : prev.content }
            default:
              return prev
          }
        })
        if (ev.type === 'meta' && !id) {
          id = String(ev.data.conversation_id)
          ownIdRef.current = id
          navigate({ view: 'chat', id })
          void refreshConversations()
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setSendError((e as Error).message)
      else await new Promise((r) => window.setTimeout(r, 300)) // let the server persist the partial answer
    } finally {
      await finishTurn(id)
    }
  }

  const submit = async (p: SubmitPayload) => {
    if (mode === 'deep_research') {
      setSendError(null)
      try {
        const res = await api.startResearch({ conversation_id: conv?.id ?? null, question: p.text, review_plan: p.reviewPlan, focus: p.focus })
        await refreshConversations()
        if (conv?.id === res.conversation_id) await load(res.conversation_id)
        else navigate({ view: 'chat', id: res.conversation_id })
      } catch (e) {
        setSendError((e as Error).message)
      }
      return
    }
    await runStream(
      { conversation_id: conv?.id ?? null, message: p.text, mode, document_ids: p.documents.map((d) => d.id) },
      p.text,
    )
  }

  const regenerate = async () => {
    if (!conv) return
    const lastUser = [...conv.messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    const m: 'chat' | 'research' = lastUser.mode === 'research' ? 'research' : 'chat'
    setConv({ ...conv, messages: conv.messages.slice(0, conv.messages.lastIndexOf(lastUser) + 1) })
    await runStream({ conversation_id: conv.id, message: '', mode: m, document_ids: [], regenerate: true }, null)
  }

  const busy = live !== null
  const jobRunning = !!conv?.active_job_id
  const messages = conv?.messages ?? []
  const liveSources = live ? Object.values(live.sources).sort((a, b) => a.number - b.number) : []
  const noModels = status && (status.overall === 'key_missing_or_invalid' || status.overall === 'unavailable')
  const noSearch = status && !status.search.available && mode !== 'chat'

  const composer = (
    <Composer
      mode={mode}
      onModeChange={changeMode}
      onSubmit={submit}
      busy={busy || jobRunning}
      onStop={busy ? () => abortRef.current?.abort() : undefined}
      autoFocus
    />
  )
  const warnings = (
    <>
      {noModels ? (
        <Notice>
          No model provider is available ({status?.overall.replace(/_/g, ' ')}). Add or fix <code>GEMINI_API_KEY</code> / <code>NVIDIA_API_KEY</code> in <code>.env</code>, restart the backend, and check{' '}
          <button className="underline" onClick={() => navigate({ view: 'settings' })}>
            Settings
          </button>
          .
        </Notice>
      ) : null}
      {noSearch ? <Notice>Web search is unavailable, so {MODE_LABEL[mode]} cannot run. Add <code>TAVILY_API_KEY</code> to <code>.env</code> and restart the backend. Chat mode still works.</Notice> : null}
      {sendError ? <Notice danger>{sendError}</Notice> : null}
    </>
  )

  if (!conversationId && !live) {
    return (
      <div className="flex h-full flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-10">
          <h1 className="mb-1.5 text-center text-2xl font-semibold tracking-tight">What would you like to work on?</h1>
          <p className="mb-7 text-center text-sm text-muted">Chat with the model, research the web with citations, or run a verified deep research report.</p>
          <div className="space-y-3">
            {warnings}
            {composer}
          </div>
          <div className="mt-6 grid gap-2 sm:grid-cols-3">
            <ModeCard icon={<MessageSquare />} title="Chat" text="Fast answers and drafting. Attach PDFs for context." active={mode === 'chat'} onClick={() => changeMode('chat')} />
            <ModeCard icon={<Globe />} title="Research" text="One search round with inline citations to the sources read." active={mode === 'research'} onClick={() => changeMode('research')} />
            <ModeCard icon={<BookOpenCheck />} title="Deep Research" text="Planned multi-round research, cross-checked, with a citation-verified PDF report." active={mode === 'deep_research'} onClick={() => changeMode('deep_research')} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto" onScroll={onScroll}>
        <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
          {loading && !conv ? (
            <p className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="size-4 animate-spin" /> Loading conversation...
            </p>
          ) : null}
          {loadError ? (
            <div className="space-y-3">
              <Notice danger>{loadError}</Notice>
              <Button onClick={() => navigate({ view: 'home' })}>Start a new chat</Button>
            </div>
          ) : null}
          {messages.map((m, i) => (
            <MessageItem key={m.id} message={m} isLast={i === messages.length - 1 && !live} onRegenerate={regenerate} busy={busy || jobRunning} />
          ))}
          {conv?.active_job_id ? <ResearchProgress jobId={conv.active_job_id} onFinished={() => void finishTurn(conv.id)} /> : null}
          {live ? (
            <>
              {live.userText ? <UserMessage content={live.userText} /> : null}
              <article className="space-y-2" aria-live="polite" aria-busy="true">
                {!live.content && !live.error ? (
                  <p className="flex items-center gap-2 text-sm text-muted">
                    <Loader2 className="size-4 animate-spin" />
                    {PHASE_LABEL[live.phase] ?? 'Working'}
                    {live.phase === 'searching' && live.queries.length ? `: ${live.queries.join(' · ')}` : ''}
                    {live.phase === 'reading' && liveSources.length ? ` (${liveSources.length} sources)` : ''}
                  </p>
                ) : null}
                {live.resets ? (
                  <p className="text-xs text-warning">The first provider failed mid-answer; restarted on {live.provider ? (PROVIDER_LABEL[live.provider] ?? live.provider) : 'the backup'}.</p>
                ) : null}
                {live.error ? <Notice danger>{live.error}</Notice> : null}
                <AssistantBody content={live.content} sources={liveSources} scope="live" streaming={!!live.content} />
              </article>
            </>
          ) : null}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="border-t border-border bg-bg px-4 pt-3 pb-4">
        <div className="mx-auto w-full max-w-3xl space-y-2">
          {warnings}
          {composer}
          <p className="text-center text-[11px] text-faint">AI output can be wrong. Check cited sources before relying on them.</p>
        </div>
      </div>
    </div>
  )
}

function Notice({ children, danger }: { children: React.ReactNode; danger?: boolean }) {
  return (
    <div
      role={danger ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2 rounded-md border px-3 py-2 text-sm [&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:text-xs',
        danger ? 'border-danger/40 bg-danger-soft text-danger' : 'border-warning/40 bg-warning-soft text-warning',
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  )
}

function ModeCard({ icon, title, text, active, onClick }: { icon: React.ReactNode; title: string; text: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded-lg border p-3.5 text-left transition-colors [&_svg]:size-4',
        active ? 'border-accent bg-accent-soft/50' : 'border-border bg-surface hover:bg-surface-hover',
      )}
    >
      <span className={cn('mb-1.5 flex items-center gap-2 text-sm font-medium', active ? 'text-accent' : 'text-fg')}>
        {icon}
        {title}
      </span>
      <span className="block text-xs text-muted">{text}</span>
    </button>
  )
}
