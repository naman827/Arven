import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function dateGroup(iso: string, now = new Date()): string {
  const d = new Date(iso)
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000
  const t = d.getTime()
  if (t >= startOfToday) return 'Today'
  if (t >= startOfToday - day) return 'Yesterday'
  if (t >= startOfToday - 7 * day) return 'Previous 7 days'
  if (t >= startOfToday - 30 * day) return 'Previous 30 days'
  return d.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .slice(0, 60)
}

export const PROVIDER_LABEL: Record<string, string> = {
  gemini: 'Gemini',
  nvidia: 'NVIDIA',
  tavily: 'Tavily',
  duckduckgo: 'DuckDuckGo',
}

export const MODE_LABEL = { chat: 'Chat', research: 'Research', deep_research: 'Deep Research' } as const

/** Turn [n] / [n, m] citation markers into markdown links, outside code fences/spans. */
export function linkCitations(markdown: string): string {
  return markdown
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(/\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/g, (_m, nums: string) =>
            nums
              .split(',')
              .map((n) => `[${n.trim()}](#source-${n.trim()})`)
              .join(''),
          ),
    )
    .join('')
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
