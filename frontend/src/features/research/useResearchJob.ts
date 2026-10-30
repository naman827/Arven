import { useEffect, useReducer } from 'react'

import { ApiError, openEventStream, type Plan, type SourceInfo, type Verification } from '@/lib/api'

export interface JobState {
  status: string
  stage: string | null
  plan: Plan | null
  queries: { query: string; subquestion?: string; round?: number }[]
  sources: Record<number, SourceInfo>
  gaps: { subquestion: string; coverage: number; gaps: string[]; conflicts: string[] }[]
  searchErrors: string[]
  provider: string | null
  draft: string
  verification: Verification | null
  reportId: string | null
  error: string | null
  connected: boolean
}

export const initialJobState: JobState = {
  status: 'queued',
  stage: null,
  plan: null,
  queries: [],
  sources: {},
  gaps: [],
  searchErrors: [],
  provider: null,
  draft: '',
  verification: null,
  reportId: null,
  error: null,
  connected: false,
}

type Action = { type: string; data: Record<string, unknown> } | { type: '__reset' } | { type: '__connected'; value: boolean }

export function jobReducer(state: JobState, action: Action): JobState {
  if (action.type === '__reset') return initialJobState
  if (action.type === '__connected') return { ...state, connected: (action as { value: boolean }).value }
  const d = (action as { data: Record<string, unknown> }).data
  switch (action.type) {
    case 'status':
      return { ...state, status: String(d.status), stage: (d.stage as string) ?? null, error: (d.error as string) ?? state.error }
    case 'plan':
      return { ...state, plan: d as unknown as Plan }
    case 'query':
      return { ...state, queries: [...state.queries, d as JobState['queries'][number]] }
    case 'source_found': {
      const s = d as unknown as SourceInfo
      return { ...state, sources: { ...state.sources, [s.number]: s } }
    }
    case 'source_read': {
      const n = Number(d.number)
      const prev = state.sources[n]
      if (!prev) return state
      return { ...state, sources: { ...state.sources, [n]: { ...prev, readable: Boolean(d.readable), error: (d.error as string) ?? null } } }
    }
    case 'gap_found':
      return { ...state, gaps: [...state.gaps, d as unknown as JobState['gaps'][number]] }
    case 'search_error':
      return { ...state, searchErrors: [...state.searchErrors, String(d.message)] }
    case 'provider':
      return { ...state, provider: String(d.provider) }
    case 'token':
      return { ...state, draft: state.draft + String(d.text ?? '') }
    case 'reset':
      return { ...state, draft: '' }
    case 'verification':
      return { ...state, verification: d as unknown as Verification }
    case 'done':
      return { ...state, status: 'completed', reportId: String(d.report_id) }
    case 'error':
      return { ...state, status: 'failed', error: String(d.message) }
    default:
      return state
  }
}

const EVENT_TYPES = [
  'status', 'plan', 'query', 'source_found', 'source_read', 'gap_found', 'search_error',
  'provider', 'token', 'reset', 'verification', 'done', 'error',
]

const RECONNECT_MS = 2000

/**
 * Subscribes to a job's SSE stream. Replays from the start so a refresh rebuilds the timeline, and
 * reconnects with Last-Event-ID if the connection drops. Uses fetch so the auth header can be sent.
 */
export function useResearchJob(jobId: string | null, onFinished?: () => void) {
  const [state, dispatch] = useReducer(jobReducer, initialJobState)

  useEffect(() => {
    dispatch({ type: '__reset' })
    if (!jobId) return
    const controller = new AbortController()
    let lastId: number | undefined
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      controller.abort()
      dispatch({ type: '__connected', value: false })
      onFinished?.()
    }
    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        const t = window.setTimeout(resolve, ms)
        controller.signal.addEventListener('abort', () => (window.clearTimeout(t), resolve()), { once: true })
      })

    void (async () => {
      while (!controller.signal.aborted) {
        try {
          const stream = await openEventStream(`/api/research/${jobId}/events`, lastId, controller.signal)
          dispatch({ type: '__connected', value: true })
          for await (const ev of stream) {
            if (ev.id !== undefined) lastId = ev.id
            if (!EVENT_TYPES.includes(ev.type)) continue
            dispatch({ type: ev.type, data: ev.data })
            if (ev.type === 'done' || ev.type === 'error' || (ev.type === 'status' && ev.data.status === 'cancelled')) {
              finish()
              return
            }
          }
        } catch (err) {
          if (controller.signal.aborted) return
          // Missing job or signed out: retrying will not help.
          if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
            dispatch({ type: '__connected', value: false })
            return
          }
        }
        dispatch({ type: '__connected', value: false })
        await wait(RECONNECT_MS)
      }
    })()
    return () => controller.abort()
    // onFinished intentionally excluded: subscription lifetime is tied to the job id only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  return state
}
