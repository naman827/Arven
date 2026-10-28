import { Menu as MenuIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Logo, Sidebar } from '@/components/Sidebar'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/overlays'
import { AppProvider } from '@/hooks/useApp'
import { useRoute } from '@/hooks/useRoute'
import { useTheme } from '@/hooks/useTheme'
import { ChatView } from '@/features/chat/ChatView'
import { DocumentsView } from '@/features/documents/DocumentsView'
import { ReportsList, ReportView } from '@/features/reports/ReportView'
import { SettingsView } from '@/features/settings/SettingsView'
import { cn } from '@/lib/utils'

const isWide = () => window.innerWidth >= 1024

export default function App() {
  const { route, navigate } = useRoute()
  const { theme, toggle } = useTheme()
  const [sidebarOpen, setSidebarOpen] = useState(isWide)

  useEffect(() => {
    const onResize = () => {
      if (!isWide()) setSidebarOpen(false)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const chatId = route.view === 'chat' ? route.id : null

  return (
    <TooltipProvider delayDuration={400}>
      <AppProvider route={route} navigate={navigate}>
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
          Skip to content
        </a>
        <div className="flex h-full overflow-hidden">
          {sidebarOpen ? (
            <>
              <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} aria-hidden />
              <div className="fixed inset-y-0 left-0 z-40 lg:static lg:z-auto">
                <Sidebar onClose={() => setSidebarOpen(false)} theme={theme} onToggleTheme={toggle} />
              </div>
            </>
          ) : null}
          <div className="flex min-w-0 flex-1 flex-col">
            <header className={cn('flex h-12 shrink-0 items-center gap-2 border-b border-border px-3', sidebarOpen && 'lg:hidden')}>
              <Button variant="ghost" size="icon-sm" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar" aria-expanded={sidebarOpen}>
                <MenuIcon />
              </Button>
              <button onClick={() => navigate({ view: 'home' })} aria-label="ARVEN AI home" className="rounded-md">
                <Logo />
              </button>
            </header>
            <main id="main" className="min-h-0 flex-1">
              {route.view === 'home' || route.view === 'chat' ? <ChatView conversationId={chatId} /> : null}
              {route.view === 'reports' ? <ReportsList /> : null}
              {route.view === 'report' ? <ReportView id={route.id} /> : null}
              {route.view === 'documents' ? <DocumentsView /> : null}
              {route.view === 'settings' ? <SettingsView /> : null}
            </main>
          </div>
        </div>
      </AppProvider>
    </TooltipProvider>
  )
}
