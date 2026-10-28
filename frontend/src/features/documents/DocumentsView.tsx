import { AlertTriangle, FileText, Loader2, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { api, type DocumentInfo } from '@/lib/api'
import { cn, formatBytes } from '@/lib/utils'

export function DocumentsView() {
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => api.listDocuments().then(setDocs, (e: Error) => setError(e.message)), [])
  useEffect(() => void refresh(), [refresh])

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setError(null)
    setUploading(true)
    try {
      for (const f of Array.from(files)) await api.uploadDocument(f)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
      await refresh()
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="mb-1 text-xl font-semibold">Documents</h1>
        <p className="mb-6 text-sm text-muted">
          Upload PDFs, then attach them in the composer (paperclip) to ask questions. Answers cite page numbers. Scanned PDFs without a text layer cannot be read yet (no OCR).
        </p>
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            void upload(e.dataTransfer.files)
          }}
          className={cn('mb-6 flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center', dragging ? 'border-accent bg-accent-soft/40' : 'border-border-strong')}
        >
          <Upload className="size-6 text-muted" aria-hidden />
          <p className="text-sm text-muted">Drag and drop PDF files here, or</p>
          <input ref={fileRef} type="file" accept="application/pdf,.pdf" multiple hidden onChange={(e) => void upload(e.target.files)} />
          <Button variant="primary" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <Loader2 className="animate-spin" /> : <Upload />} {uploading ? 'Uploading' : 'Choose PDF'}
          </Button>
        </div>
        {error ? (
          <p role="alert" className="mb-4 text-sm text-danger">
            {error}
          </p>
        ) : null}
        {docs === null && !error ? <Loader2 className="size-5 animate-spin text-muted" /> : null}
        {docs?.length === 0 ? <p className="text-sm text-faint">No documents uploaded yet.</p> : null}
        {docs?.length ? (
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
            {docs.map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-4 py-3">
                <FileText className="size-4 shrink-0 text-accent" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{d.filename}</p>
                  <p className="text-xs text-muted">
                    {d.page_count} pages · {formatBytes(d.size_bytes)} · {new Date(d.created_at).toLocaleDateString()}
                  </p>
                  {!d.has_text ? (
                    <p className="mt-0.5 flex items-center gap-1 text-xs text-warning">
                      <AlertTriangle className="size-3" /> No text layer (scanned). OCR is not supported yet.
                    </p>
                  ) : null}
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Delete ${d.filename}`}
                  onClick={async () => {
                    try {
                      await api.deleteDocument(d.id)
                    } catch (e) {
                      setError((e as Error).message)
                    }
                    await refresh()
                  }}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  )
}
