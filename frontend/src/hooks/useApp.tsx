import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api, type Conversation, type SystemStatus } from '@/lib/api'
import type { Route } from '@/hooks/useRoute'

interface AppState {
  route: Route
  navigate: (r: Route) => void
  conversations: Conversation[]
  conversationsError: string | null
  refreshConversations: () => Promise<void>
  status: SystemStatus | null
  statusError: string | null
  refreshStatus: () => Promise<void>
}

const Ctx = createContext<AppState | null>(null)

export function AppProvider({ route, navigate, children }: { route: Route; navigate: (r: Route) => void; children: ReactNode }) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationsError, setConversationsError] = useState<string | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations())
      setConversationsError(null)
    } catch (e) {
      setConversationsError((e as Error).message)
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.status())
      setStatusError(null)
    } catch (e) {
      setStatusError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    void refreshConversations()
    void refreshStatus()
    const timer = window.setInterval(() => void refreshStatus(), 30_000)
    return () => window.clearInterval(timer)
  }, [refreshConversations, refreshStatus])

  const value = useMemo(
    () => ({ route, navigate, conversations, conversationsError, refreshConversations, status, statusError, refreshStatus }),
    [route, navigate, conversations, conversationsError, refreshConversations, status, statusError, refreshStatus],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useApp outside provider')
  return ctx
}
