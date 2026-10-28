import { FileText, FolderOpen, MessageSquarePlus, Moon, MoreHorizontal, PanelLeftClose, Pencil, Search, Settings, Sun, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { ProviderBadge } from '@/components/ProviderBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/overlays'
import { useApp } from '@/hooks/useApp'
import type { Theme } from '@/hooks/useTheme'
import { api, type Conversation } from '@/lib/api'
import { cn, dateGroup } from '@/lib/utils'

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
        <rect width="32" height="32" rx="7" fill="var(--accent)" />
        <path d="M9 23 16 8l7 15h-3.4L16 15.2 12.4 23z" fill="#fff" />
        <rect x="13" y="19" width="6" height="2" rx="1" fill="#fff" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">ARVEN AI</span>
    </div>
  )
}

export function Sidebar({ onClose, theme, onToggleTheme }: { onClose: () => void; theme: Theme; onToggleTheme: () => void }) {
  const { conversations, conversationsError, refreshConversations, route, navigate, status, statusError } = useApp()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Conversation[] | null>(null)
  const [renaming, setRenaming] = useState<Conversation | null>(null)
  const [deleting, setDeleting] = useState<Conversation | null>(null)

  useEffect(() => {
    if (!query.trim()) {
      setResults(null)
      return
    }
    const timer = window.setTimeout(() => {
      api.listConversations(query.trim()).then(setResults, () => setResults([]))
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query, conversations])

  const list = results ?? conversations
  const groups = useMemo(() => {
    const out: [string, Conversation[]][] = []
    for (const c of list) {
      const g = dateGroup(c.updated_at)
      const last = out[out.length - 1]
      if (last && last[0] === g) last[1].push(c)
      else out.push([g, [c]])
    }
    return out
  }, [list])

  const go = (r: Parameters<typeof navigate>[0]) => {
    navigate(r)
    if (window.innerWidth < 1024) onClose()
  }

  const activeId = route.view === 'chat' ? route.id : null

  return (
    <nav aria-label="Sidebar" className="flex h-full w-72 flex-col border-r border-border bg-bg-subtle">
      <div className="flex h-14 items-center justify-between px-4">
        <button onClick={() => go({ view: 'home' })} className="rounded-md" aria-label="ARVEN AI home">
          <Logo />
        </button>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Collapse sidebar">
          <PanelLeftClose />
        </Button>
      </div>

      <div className="space-y-2 px-3">
        <Button variant="secondary" className="w-full justify-start" onClick={() => go({ view: 'home' })}>
          <MessageSquarePlus /> New chat
        </Button>
        <label className="relative block">
          <span className="sr-only">Search conversations</span>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-faint" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search history"
            className="h-9 w-full rounded-md border border-border bg-surface pr-3 pl-8 text-sm placeholder:text-faint focus:border-accent focus:outline-none"
          />
        </label>
      </div>

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {conversationsError ? <p className="px-2 py-2 text-xs text-danger">{conversationsError}</p> : null}
        {list.length === 0 && !conversationsError ? (
          <p className="px-2 py-2 text-xs text-faint">{query ? 'No matching conversations.' : 'No conversations yet.'}</p>
        ) : null}
        {groups.map(([group, items]) => (
          <section key={group} className="mb-3">
            <h3 className="px-2 pb-1 text-[11px] font-medium tracking-wide text-faint uppercase">{group}</h3>
            <ul>
              {items.map((c) => (
                <li key={c.id} className="group relative">
                  <button
                    onClick={() => go({ view: 'chat', id: c.id })}
                    aria-current={activeId === c.id ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-center rounded-md py-1.5 pr-8 pl-2 text-left text-sm',
                      activeId === c.id ? 'bg-surface-hover text-fg' : 'text-muted hover:bg-surface-hover hover:text-fg',
                    )}
                  >
                    <span className="truncate">{c.title}</span>
                  </button>
                  <Menu>
                    <MenuTrigger
                      aria-label={`Options for ${c.title}`}
                      className="absolute top-1/2 right-1 -translate-y-1/2 rounded p-1 text-faint opacity-0 group-hover:opacity-100 hover:text-fg focus-visible:opacity-100 data-[state=open]:opacity-100"
                    >
                      <MoreHorizontal className="size-4" />
                    </MenuTrigger>
                    <MenuContent>
                      <MenuItem onSelect={() => setRenaming(c)}>
                        <Pencil /> Rename
                      </MenuItem>
                      <MenuItem danger onSelect={() => setDeleting(c)}>
                        <Trash2 /> Delete
                      </MenuItem>
                    </MenuContent>
                  </Menu>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="space-y-1 border-t border-border p-2">
        <NavItem icon={<FileText />} label="Reports" active={route.view === 'reports' || route.view === 'report'} onClick={() => go({ view: 'reports' })} />
        <NavItem icon={<FolderOpen />} label="Documents" active={route.view === 'documents'} onClick={() => go({ view: 'documents' })} />
        <NavItem icon={<Settings />} label="Settings" active={route.view === 'settings'} onClick={() => go({ view: 'settings' })} />
        <div className="flex items-center justify-between gap-2 rounded-md px-2 pt-2 pb-1">
          <button onClick={() => go({ view: 'settings' })} className="min-w-0 rounded text-left" aria-label="Provider status, open settings">
            <ProviderBadge status={status} error={statusError} />
          </button>
          <Button variant="ghost" size="icon-sm" onClick={onToggleTheme} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
        </div>
      </div>

      <RenameDialog
        conversation={renaming}
        onClose={() => setRenaming(null)}
        onDone={async () => {
          setRenaming(null)
          await refreshConversations()
        }}
      />
      <Dialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent title="Delete conversation?" description="This permanently removes the conversation, its messages, sources, and any reports created in it.">
          <p className="mb-4 truncate text-sm font-medium">{deleting?.title}</p>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="secondary">Cancel</Button>
            </DialogClose>
            <Button
              variant="danger"
              onClick={async () => {
                if (!deleting) return
                const id = deleting.id
                setDeleting(null)
                try {
                  await api.deleteConversation(id)
                } finally {
                  await refreshConversations()
                  if (activeId === id) navigate({ view: 'home' })
                }
              }}
            >
              Delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </nav>
  )
}

function NavItem({ icon, label, active, onClick }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-sm [&_svg]:size-4',
        active ? 'bg-surface-hover text-fg' : 'text-muted hover:bg-surface-hover hover:text-fg',
      )}
    >
      {icon}
      {label}
    </button>
  )
}

function RenameDialog({ conversation, onClose, onDone }: { conversation: Conversation | null; onClose: () => void; onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setTitle(conversation?.title ?? '')
    setError(null)
  }, [conversation])
  return (
    <Dialog open={!!conversation} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Rename conversation">
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            if (!conversation || !title.trim()) return
            try {
              await api.renameConversation(conversation.id, title.trim())
              onDone()
            } catch (err) {
              setError((err as Error).message)
            }
          }}
        >
          <label className="mb-1 block text-sm text-muted" htmlFor="rename-input">
            Title
          </label>
          <input
            id="rename-input"
            autoFocus
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
            className="mb-2 h-9 w-full rounded-md border border-border bg-bg px-3 text-sm focus:border-accent focus:outline-none"
          />
          {error ? <p className="mb-2 text-xs text-danger">{error}</p> : null}
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="secondary" type="button">
                Cancel
              </Button>
            </DialogClose>
            <Button variant="primary" type="submit" disabled={!title.trim()}>
              Save
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
