import { Download, Loader2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { api, ApiError } from '@/lib/api'

/** Downloads a report PDF with the auth header (a plain link cannot send it). */
export function PdfDownloadButton({ reportId, label, variant }: { reportId: string; label: string; variant: 'primary' | 'secondary' }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const download = async () => {
    setBusy(true)
    setError(null)
    try {
      const { blob, filename } = await api.reportPdf(reportId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Download failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button size="sm" variant={variant} onClick={() => void download()} disabled={busy}>
        {busy ? <Loader2 className="animate-spin" /> : <Download />} {label}
      </Button>
      {error ? (
        <span role="alert" className="self-center text-xs text-danger">
          {error}
        </span>
      ) : null}
    </>
  )
}
