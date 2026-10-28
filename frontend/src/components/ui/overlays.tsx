import { Dialog as D, DropdownMenu as M, Tooltip as T } from 'radix-ui'
import { X } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

// ---- Dialog -------------------------------------------------------------------

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({
  title,
  description,
  children,
  className,
}: {
  title: string
  description?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <D.Content
        className={cn(
          'fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-5 shadow-md focus:outline-none',
          className,
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <D.Title className="text-base font-semibold">{title}</D.Title>
            {description ? <D.Description className="mt-1 text-sm text-muted">{description}</D.Description> : null}
          </div>
          <D.Close className="rounded-md p-1 text-muted hover:bg-surface-hover hover:text-fg" aria-label="Close">
            <X className="size-4" />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  )
}

// ---- Dropdown menu -------------------------------------------------------------

export const Menu = M.Root
export const MenuTrigger = M.Trigger

export function MenuContent({ children, align = 'end' }: { children: React.ReactNode; align?: 'start' | 'end' }) {
  return (
    <M.Portal>
      <M.Content
        align={align}
        sideOffset={4}
        className="z-50 min-w-40 rounded-md border border-border bg-surface p-1 text-sm shadow-md"
      >
        {children}
      </M.Content>
    </M.Portal>
  )
}

export function MenuItem({
  children,
  onSelect,
  danger,
}: {
  children: React.ReactNode
  onSelect: () => void
  danger?: boolean
}) {
  return (
    <M.Item
      onSelect={onSelect}
      className={cn(
        'flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 outline-none select-none data-highlighted:bg-surface-hover [&_svg]:size-4',
        danger ? 'text-danger' : 'text-fg',
      )}
    >
      {children}
    </M.Item>
  )
}

// ---- Tooltip -------------------------------------------------------------------

export const TooltipProvider = T.Provider

export function Tip({ label, children, side = 'top' }: { label: string; children: React.ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-fg px-2 py-1 text-xs text-bg shadow-md"
        >
          {label}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}
