// Typed client for the ARVEN AI backend. Locally, requests go through the Vite /api proxy (same origin).
// A deployed frontend sets VITE_API_BASE to the backend's URL and authenticates with an access token.

export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')
const TOKEN_KEY = 'arven-token'
export const UNAUTHORIZED_EVENT = 'arven:unauthorized'

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable: the user will be asked to log in again */
  }
}

function withAuth(init?: RequestInit): RequestInit {
  const token = getToken()
  if (!token) return init ?? {}
  const headers = new Headers(init?.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return { ...init, headers }
}

/** URL for GET endpoints that cannot send headers (EventSource, download links). */
export function authUrl(path: string): string {
  const token = getToken()
  const sep = path.includes('?') ? '&' : '?'
  return `${API_BASE}${path}${token ? `${sep}access_token=${encodeURIComponent(token)}` : ''}`
}

const UNREACHABLE = API_BASE
  ? 'Cannot reach the ARVEN AI backend. It may be waking up; try again in a minute.'
  : 'Cannot reach the ARVEN AI backend. Is it running on 127.0.0.1:8000?'

function onUnauthorized(status: number) {
  if (status === 401) {
    setToken('')
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
}

export type Mode = 'chat' | 'research' | 'deep_research'

export interface Conversation {
  id: string
  title: string
  mode: Mode
  created_at: string
  updated_at: string
}

export interface SourceInfo {
  number: number
  url: string
  title: string
  domain: string
  published_date?: string | null
  retrieved_at?: string | null
  snippet?: string
  readable?: boolean | null
  error?: string | null
  source_type?: string | null
  subquestion?: string | null
  provider?: string | null
  search_provider?: string | null
}

export interface Verification {
  ran: boolean
  claims_total: number
  claims_checked: number
  supported: number
  partial: number
  removed: number
  not_checked: number
  invalid_citations_removed: number
  failed_batches?: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  mode: Mode
  provider: string | null
  model: string | null
  status: 'complete' | 'stopped' | 'error' | 'cancelled' | string
  research_job_id: string | null
  meta: {
    sources?: SourceInfo[]
    report_id?: string
    verification?: Verification
    title?: string
    error?: string
    document_ids?: string[]
    invalid_citations_removed?: number
    queries?: string[]
  }
  created_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
  active_job_id: string | null
}

export interface Plan {
  main_question: string
  deliverable_type: string
  subquestions: { question: string; evidence_needed: string }[]
  time_sensitive_claims: string[]
  stop_conditions: string[]
}

export interface Job {
  id: string
  conversation_id: string
  question: string
  status: string
  error: string | null
  plan: Plan | null
  options: { review_plan?: boolean; focus?: string }
  report_id: string | null
  created_at: string
}

export interface ReportSummary {
  id: string
  title: string
  job_id: string | null
  conversation_id: string | null
  created_at: string
}

export interface Report extends ReportSummary {
  markdown: string
  verification: Verification | null
  provider: string | null
  sources: SourceInfo[]
}

export interface DocumentInfo {
  id: string
  filename: string
  size_bytes: number
  page_count: number
  has_text: boolean
  status: string
  created_at: string
}

export interface ProviderStatus {
  name: string
  configured: boolean
  model: string
  state: 'ready' | 'unavailable' | 'key_missing_or_invalid'
  circuit: string
  retry_in_seconds: number
  last_error: { kind: string; message: string } | null
}

export interface SystemStatus {
  overall: 'gemini_active' | 'nvidia_fallback_active' | 'unavailable' | 'key_missing_or_invalid'
  providers: ProviderStatus[]
  search: {
    available: boolean
    providers: { name: string; configured: boolean; state: string; last_error: string | null }[]
  }
  budgets: Record<string, number>
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, withAuth(init))
  } catch {
    throw new ApiError(0, UNREACHABLE)
  }
  if (!res.ok) {
    onUnauthorized(res.status)
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail || `Request failed (${res.status})`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  listConversations: (q?: string) =>
    request<Conversation[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  getConversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    request<Conversation>(`/api/conversations/${id}`, { ...json({ title }), method: 'PATCH' }),
  setConversationMode: (id: string, mode: Mode) =>
    request<Conversation>(`/api/conversations/${id}`, { ...json({ mode }), method: 'PATCH' }),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: 'DELETE' }),
  messageSources: (conversationId: string, messageId: string) =>
    request<SourceInfo[]>(`/api/conversations/${conversationId}/messages/${messageId}/sources`),

  startResearch: (body: { conversation_id?: string | null; question: string; review_plan: boolean; focus: 'general' | 'academic' }) =>
    request<{ job_id: string; conversation_id: string }>('/api/research', json(body)),
  getJob: (id: string) => request<Job>(`/api/research/${id}`),
  cancelJob: (id: string) => request<{ cancelled: boolean }>(`/api/research/${id}/cancel`, { method: 'POST' }),
  approvePlan: (id: string, subquestions: string[]) =>
    request<{ approved: boolean }>(`/api/research/${id}/approve`, json({ subquestions })),

  listReports: () => request<ReportSummary[]>('/api/reports'),
  getReport: (id: string) => request<Report>(`/api/reports/${id}`),
  reportPdfUrl: (id: string) => authUrl(`/api/reports/${id}/pdf`),

  listDocuments: () => request<DocumentInfo[]>('/api/documents'),
  uploadDocument: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentInfo>('/api/documents', { method: 'POST', body: form })
  },
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: 'DELETE' }),

  authStatus: () => request<{ required: boolean; authenticated: boolean }>('/api/auth/status'),
  login: (password: string) => request<{ token: string; expires_in: number }>('/api/auth/login', json({ password })),

  status: () => request<SystemStatus>('/api/settings/status'),
  testConnection: (name: string) =>
    request<{ ok: boolean; message: string; kind?: string }>(`/api/settings/test/${name}`, { method: 'POST' }),
}

// ---- Streaming -------------------------------------------------------------

export interface StreamEvent {
  type: string
  data: Record<string, unknown>
  id?: number
}

/** Parse an SSE byte stream from a fetch() response body. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let index: number
      while ((index = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)
        const event = parseBlock(block)
        if (event) yield event
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export function parseBlock(block: string): StreamEvent | null {
  let type = 'message'
  let data = ''
  let id: number | undefined
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue
    if (line.startsWith('event: ')) type = line.slice(7)
    else if (line.startsWith('data: ')) data += line.slice(6)
    else if (line.startsWith('id: ')) id = Number(line.slice(4))
  }
  if (!data) return null
  try {
    return { type, data: JSON.parse(data), id }
  } catch {
    return null
  }
}

export async function streamChat(
  body: { conversation_id?: string | null; message: string; mode: 'chat' | 'research'; document_ids: string[]; regenerate?: boolean },
  signal: AbortSignal,
): Promise<AsyncGenerator<StreamEvent>> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/chat`, withAuth({ ...json(body), signal }))
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(0, UNREACHABLE)
  }
  if (!res.ok || !res.body) {
    onUnauthorized(res.status)
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail))
  }
  return readSse(res.body)
}
