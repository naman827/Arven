import { Check, Copy } from 'lucide-react'
import { memo, useState, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

import type { SourceInfo } from '@/lib/api'
import { cn, copyText, linkCitations, slugify } from '@/lib/utils'

function textOf(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (node && typeof node === 'object' && 'props' in node) return textOf((node as { props: { children?: ReactNode } }).props.children)
  return ''
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="group relative">
      <pre>{children}</pre>
      <button
        type="button"
        onClick={async () => {
          if (await copyText(textOf(children))) {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1500)
          }
        }}
        className="absolute top-2 right-2 rounded-md border border-border bg-surface p-1 text-muted opacity-0 group-hover:opacity-100 hover:text-fg focus-visible:opacity-100"
        aria-label={copied ? 'Copied' : 'Copy code'}
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  )
}

interface Props {
  content: string
  sources?: SourceInfo[]
  onCitation?: (n: number) => void
  anchors?: boolean
  streaming?: boolean
  className?: string
}

export const Markdown = memo(function Markdown({ content, sources, onCitation, anchors, streaming, className }: Props) {
  const byNumber = new Map((sources ?? []).map((s) => [s.number, s]))
  const heading =
    (Tag: 'h2' | 'h3') =>
    ({ children }: { children?: ReactNode }) => {
      const id = anchors ? `sec-${slugify(textOf(children))}` : undefined
      return (
        <Tag id={id} className={anchors ? 'scroll-mt-20' : undefined}>
          {children}
        </Tag>
      )
    }

  const components: Components = {
    a: ({ href, children }) => {
      const m = href?.match(/^#source-(\d+)$/)
      if (m) {
        const n = Number(m[1])
        const src = byNumber.get(n)
        const label = src ? `${src.title} (${src.domain})` : `Source ${n}`
        return (
          <button
            type="button"
            onClick={() => onCitation?.(n)}
            title={label}
            aria-label={`Citation ${n}: ${label}`}
            className="mx-0.5 inline-flex h-[1.15rem] min-w-[1.15rem] -translate-y-px items-center justify-center rounded bg-accent-soft px-1 align-middle text-[11px] font-semibold text-accent no-underline hover:bg-accent hover:text-accent-fg"
          >
            {n}
          </button>
        )
      }
      const external = href?.startsWith('http')
      return (
        <a href={href} target={external ? '_blank' : undefined} rel={external ? 'noopener noreferrer' : undefined}>
          {children}
        </a>
      )
    },
    pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
    table: ({ children }) => (
      <div className="table-wrap">
        <table>{children}</table>
      </div>
    ),
    h2: heading('h2'),
    h3: heading('h3'),
  }

  return (
    <div className={cn('prose-arven', streaming && 'streaming-caret', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={components}>
        {linkCitations(content)}
      </ReactMarkdown>
    </div>
  )
})
