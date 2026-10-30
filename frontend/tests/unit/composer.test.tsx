import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/overlays'
import { Composer, type SubmitPayload } from '@/features/chat/Composer'
import type { Mode } from '@/lib/api'

function Harness({ onSubmit, busy = false, onStop }: { onSubmit: (p: SubmitPayload) => void; busy?: boolean; onStop?: () => void }) {
  const [mode, setMode] = useState<Mode>('chat')
  return (
    <TooltipProvider>
      <Composer mode={mode} onModeChange={setMode} onSubmit={onSubmit} busy={busy} onStop={onStop} />
      <output data-testid="mode">{mode}</output>
    </TooltipProvider>
  )
}

describe('Composer', () => {
  it('sends on Enter, not on Shift+Enter, and clears', async () => {
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} />)
    const box = screen.getByLabelText('Message')
    await userEvent.type(box, 'hello{Shift>}{Enter}{/Shift}')
    expect(onSubmit).not.toHaveBeenCalled()
    await userEvent.type(box, '{Enter}')
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ text: 'hello', documents: [], reviewPlan: false, focus: 'general' }))
    expect(box).toHaveValue('')
  })

  it('disables send for empty input', () => {
    render(<Harness onSubmit={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('switches mode by click and arrow keys; deep research shows its options', async () => {
    render(<Harness onSubmit={vi.fn()} />)
    await userEvent.click(screen.getByRole('radio', { name: 'Research' }))
    expect(screen.getByTestId('mode')).toHaveTextContent('research')
    fireEvent.keyDown(screen.getByRole('radiogroup', { name: 'Mode' }), { key: 'ArrowRight' })
    expect(screen.getByTestId('mode')).toHaveTextContent('deep_research')
    expect(screen.getByRole('switch', { name: 'Review plan' })).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(screen.getByRole('switch', { name: 'Academic focus' }))
    expect(screen.getByRole('switch', { name: 'Academic focus' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByRole('button', { name: 'Attach PDF' })).toBeNull()
  })

  it('shows stop while busy', async () => {
    const onStop = vi.fn()
    render(<Harness onSubmit={vi.fn()} busy onStop={onStop} />)
    await userEvent.click(screen.getByRole('button', { name: 'Stop generating' }))
    expect(onStop).toHaveBeenCalled()
  })
})
