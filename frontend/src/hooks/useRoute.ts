import { useCallback, useEffect, useState } from 'react'

// Hash routing so views survive a browser refresh without server config.
export type Route =
  | { view: 'home' }
  | { view: 'chat'; id: string }
  | { view: 'reports' }
  | { view: 'report'; id: string }
  | { view: 'documents' }
  | { view: 'memory' }
  | { view: 'settings' }

export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'c' && parts[1]) return { view: 'chat', id: parts[1] }
  if (parts[0] === 'reports' && parts[1]) return { view: 'report', id: parts[1] }
  if (parts[0] === 'reports') return { view: 'reports' }
  if (parts[0] === 'documents') return { view: 'documents' }
  if (parts[0] === 'memory') return { view: 'memory' }
  if (parts[0] === 'settings') return { view: 'settings' }
  return { view: 'home' }
}

export function routeToHash(route: Route): string {
  switch (route.view) {
    case 'chat':
      return `#/c/${route.id}`
    case 'report':
      return `#/reports/${route.id}`
    case 'reports':
      return '#/reports'
    case 'documents':
      return '#/documents'
    case 'memory':
      return '#/memory'
    case 'settings':
      return '#/settings'
    default:
      return '#/'
  }
}

export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const navigate = useCallback((next: Route) => {
    const hash = routeToHash(next)
    if (window.location.hash !== hash) window.location.hash = hash
    else setRoute(next)
  }, [])

  return { route, navigate }
}
