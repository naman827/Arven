import { Loader2, Lock } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'

import { Logo } from '@/components/Sidebar'
import { Button } from '@/components/ui/button'
import { api, ApiError, setToken, UNAUTHORIZED_EVENT } from '@/lib/api'

type State = 'checking' | 'ok' | 'login' | 'unreachable'

/** Shows a password screen when the backend has ACCESS_PASSWORD set; renders the app otherwise. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>('checking')

  const check = useCallback(async () => {
    setState('checking')
    try {
      const s = await api.authStatus()
      setState(!s.required || s.authenticated ? 'ok' : 'login')
    } catch {
      setState('unreachable')
    }
  }, [])

  useEffect(() => {
    void check()
    const onUnauthorized = () => setState('login')
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [check])

  if (state === 'ok') return <>{children}</>
  return (
    <div className="flex h-full items-center justify-center bg-bg p-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-6 shadow-sm">
        <div className="mb-5 flex justify-center">
          <Logo />
        </div>
        {state === 'checking' ? (
          <p className="flex items-center justify-center gap-2 text-sm text-muted" role="status">
            <Loader2 className="size-4 animate-spin" /> Connecting to the backend...
          </p>
        ) : null}
        {state === 'unreachable' ? (
          <div className="space-y-3 text-center">
            <p className="text-sm text-muted">Cannot reach the ARVEN AI backend. A free server may take up to a minute to wake up.</p>
            <Button variant="primary" onClick={() => void check()}>
              Try again
            </Button>
          </div>
        ) : null}
        {state === 'login' ? <LoginForm onSuccess={() => setState('ok')} /> : null}
      </div>
    </div>
  )
}

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError(null)
    try {
      const { token } = await api.login(password)
      setToken(token)
      onSuccess()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <label htmlFor="access-password" className="flex items-center gap-1.5 text-sm font-medium">
        <Lock className="size-3.5" /> Access password
      </label>
      <input
        id="access-password"
        type="password"
        autoComplete="current-password"
        autoFocus
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none focus-visible:border-accent"
      />
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" variant="primary" className="w-full" disabled={!password || busy}>
        {busy ? <Loader2 className="animate-spin" /> : null} Unlock
      </Button>
    </form>
  )
}
