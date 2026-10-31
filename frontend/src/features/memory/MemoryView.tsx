import { Brain, Check, Loader2, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent } from '@/components/ui/overlays'
import { api, type MemoryItem } from '@/lib/api'

const MAX_LENGTH = 500

export function MemoryView() {
  const [memories, setMemories] = useState<MemoryItem[] | null>(null)
  const [autoLearn, setAutoLearn] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const [clearing, setClearing] = useState(false)

  const refresh = useCallback(
    () =>
      api.listMemories().then(
        (r) => {
          setMemories(r.memories)
          setAutoLearn(r.auto_learn)
        },
        (e: Error) => setError(e.message),
      ),
    [],
  )
  useEffect(() => void refresh(), [refresh])

  const run = async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
    } catch (e) {
      setError((e as Error).message)
    }
    await refresh()
  }

  const add = async () => {
    if (!draft.trim()) return
    setAdding(true)
    await run(async () => {
      await api.addMemory(draft.trim())
      setDraft('')
    })
    setAdding(false)
  }

  const saveEdit = async () => {
    if (!editing || !editing.text.trim()) return
    const { id, text } = editing
    setEditing(null)
    await run(() => api.updateMemory(id, text.trim()))
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="mb-1 text-xl font-semibold">Memory</h1>
        <p className="mb-6 text-sm text-muted">
          Facts and preferences ARVEN remembers about you across conversations. They are added to Chat, Research and Deep Research so answers fit your background and style. Memories are shared by everyone who signs in to this workspace.
        </p>

        <label className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-surface p-4">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-[var(--accent)]"
            checked={autoLearn}
            onChange={(e) => {
              const next = e.target.checked
              setAutoLearn(next)
              void run(() => api.setMemoryAutoLearn(next))
            }}
          />
          <span>
            <span className="block text-sm font-medium">Learn automatically</span>
            <span className="block text-xs text-muted">
              When you mention something about yourself (for example "I'm a nurse" or "keep answers short"), the model saves it here in the background. Only your own messages are used, never web pages or documents.
            </span>
          </span>
        </label>

        <form
          className="mb-6 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void add()
          }}
        >
          <label className="min-w-0 flex-1">
            <span className="sr-only">New memory</span>
            <input
              value={draft}
              maxLength={MAX_LENGTH}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Add a memory, e.g. I prefer answers with tables"
              className="h-9 w-full rounded-md border border-border bg-surface px-3 text-sm placeholder:text-faint focus:border-accent focus:outline-none"
            />
          </label>
          <Button type="submit" variant="primary" disabled={adding || !draft.trim()}>
            {adding ? <Loader2 className="animate-spin" /> : <Plus />} Add
          </Button>
        </form>

        {error ? (
          <p role="alert" className="mb-4 text-sm text-danger">
            {error}
          </p>
        ) : null}
        {memories === null && !error ? <Loader2 className="size-5 animate-spin text-muted" /> : null}
        {memories?.length === 0 ? <p className="text-sm text-faint">No memories yet.</p> : null}
        {memories?.length ? (
          <>
            <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
              {memories.map((m) => (
                <li key={m.id} className="flex items-start gap-3 px-4 py-3">
                  <Brain className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                  {editing?.id === m.id ? (
                    <form
                      className="flex min-w-0 flex-1 items-center gap-1"
                      onSubmit={(e) => {
                        e.preventDefault()
                        void saveEdit()
                      }}
                    >
                      <label className="min-w-0 flex-1">
                        <span className="sr-only">Edit memory</span>
                        <input
                          autoFocus
                          value={editing.text}
                          maxLength={MAX_LENGTH}
                          onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                          onKeyDown={(e) => e.key === 'Escape' && setEditing(null)}
                          className="h-8 w-full rounded-md border border-border bg-bg px-2 text-sm focus:border-accent focus:outline-none"
                        />
                      </label>
                      <Button type="submit" variant="ghost" size="icon-sm" aria-label="Save memory" disabled={!editing.text.trim()}>
                        <Check />
                      </Button>
                      <Button type="button" variant="ghost" size="icon-sm" aria-label="Cancel editing" onClick={() => setEditing(null)}>
                        <X />
                      </Button>
                    </form>
                  ) : (
                    <>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm break-words">{m.content}</p>
                        <p className="text-xs text-muted">
                          {m.source === 'auto' ? 'Learned from a conversation' : 'Added by you'} · {new Date(m.updated_at).toLocaleDateString()}
                        </p>
                      </div>
                      <Button variant="ghost" size="icon-sm" aria-label={`Edit memory: ${m.content}`} onClick={() => setEditing({ id: m.id, text: m.content })}>
                        <Pencil />
                      </Button>
                      <Button variant="ghost" size="icon-sm" aria-label={`Delete memory: ${m.content}`} onClick={() => void run(() => api.deleteMemory(m.id))}>
                        <Trash2 />
                      </Button>
                    </>
                  )}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex justify-end">
              <Button variant="ghost" onClick={() => setClearing(true)}>
                <Trash2 /> Clear all memories
              </Button>
            </div>
          </>
        ) : null}
      </div>

      <Dialog open={clearing} onOpenChange={setClearing}>
        <DialogContent title="Clear all memories?" description="This permanently removes every saved memory. Conversations are not affected.">
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="secondary">Cancel</Button>
            </DialogClose>
            <Button
              variant="danger"
              onClick={() => {
                setClearing(false)
                void run(() => api.clearMemories())
              }}
            >
              Clear all
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
