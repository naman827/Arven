import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SHOTS = path.resolve(import.meta.dirname, '../../../docs/screenshots')

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false })
}

async function send(page: Page, text: string) {
  const box = page.getByLabel('Message', { exact: true })
  await box.fill(text)
  await box.press('Enter')
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
}

test('chat: stream, persist across refresh, rename, delete', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What would you like to work on?' })).toBeVisible()
  await expect(page.getByText('Gemini active')).toBeVisible()
  await shot(page, 'desktop-home-dark')

  await send(page, 'Explain photosynthesis briefly')
  await expect(page.getByText('Chat · Gemini (mock-gemini)')).toBeVisible()
  await expect(page.getByRole('table')).toBeVisible()
  await expect(page).toHaveURL(/#\/c\//)
  await shot(page, 'desktop-chat-dark')

  await page.reload()
  await expect(page.getByText('Here is a mocked answer to:')).toBeVisible()
  await expect(page.getByText('Chat · Gemini (mock-gemini)')).toBeVisible()

  const item = page.getByRole('navigation', { name: 'Sidebar' }).getByRole('button', { name: 'Explain photosynthesis briefly', exact: true })
  await item.hover()
  await page.getByRole('button', { name: 'Options for Explain photosynthesis briefly' }).click()
  await page.getByRole('menuitem', { name: 'Rename' }).click()
  await page.getByLabel('Title').fill('Photosynthesis notes')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('navigation', { name: 'Sidebar' }).getByRole('button', { name: 'Photosynthesis notes', exact: true })).toBeVisible()

  await page.getByRole('navigation', { name: 'Sidebar' }).getByRole('button', { name: 'Photosynthesis notes', exact: true }).hover()
  await page.getByRole('button', { name: 'Options for Photosynthesis notes' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'What would you like to work on?' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Sidebar' }).getByText('Photosynthesis notes')).toHaveCount(0)
})

test('research mode: sources and citations', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Research', exact: true }).click()
  await send(page, 'How fast is solar adoption growing?')
  await expect(page.getByText('Solar is growing quickly')).toBeVisible()
  await expect(page.getByText(/Sources \(\d+ read of \d+\)/)).toBeVisible()
  await expect(page.getByText('[42]')).toHaveCount(0)
  const citation = page.getByRole('button', { name: /^Citation 1:/ }).first()
  await expect(citation).toBeVisible()
  await citation.click()
  await expect(page.getByText('Research · Gemini (mock-gemini)')).toBeVisible()
  await shot(page, 'desktop-research-dark')
})

test('deep research: plan review, progress, report, PDF download', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Deep Research' }).click()
  await page.getByRole('switch', { name: 'Review plan' }).click()
  await send(page, 'State of residential solar adoption')
  await expect(page.getByText('Review the research plan')).toBeVisible()
  await shot(page, 'desktop-deep-research-plan-review')
  await page.getByRole('button', { name: 'Remove subquestion 3' }).click()
  await page.getByRole('button', { name: 'Start research' }).click()
  await expect(page.getByRole('button', { name: 'Open report' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/Citation check: \d+ of \d+ cited claims/)).toBeVisible()

  await page.getByRole('button', { name: 'Open report' }).click()
  await expect(page.getByRole('heading', { name: 'Solar Energy Adoption', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'References' })).toBeVisible()
  await expect(page.getByText(/UNSUPPORTED claim/)).toHaveCount(0)
  await expect(page.getByText(/fabricated claim/)).toHaveCount(0)
  await shot(page, 'desktop-report-dark')

  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'PDF', exact: true }).click()])
  const file = await download.path()
  expect(fs.readFileSync(file).subarray(0, 5).toString()).toBe('%PDF-')
  expect(download.suggestedFilename()).toMatch(/\.pdf$/)

  await page.getByRole('button', { name: 'Continue discussion' }).click()
  await expect(page).toHaveURL(/#\/c\//)
  await page.getByRole('navigation', { name: 'Sidebar' }).getByRole('button', { name: 'Reports', exact: true }).click()
  await expect(page.getByRole('button', { name: /Solar Energy Adoption/ }).first()).toBeVisible()
})

test('deep research: cancel', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Deep Research' }).click()
  await page.getByRole('switch', { name: 'Review plan' }).click()
  await send(page, 'Something to cancel')
  await expect(page.getByText('Review the research plan')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByText('Deep research was cancelled. Collected sources were kept.')).toBeVisible({ timeout: 15_000 })
})

test('documents: upload PDF and ask about it', async ({ page }) => {
  await page.goto('/#/documents')
  await page.locator('input[type=file]').setInputFiles(path.resolve(import.meta.dirname, 'fixtures/sample.pdf'))
  await expect(page.getByText('sample.pdf')).toBeVisible()
  await expect(page.getByText(/2 pages/)).toBeVisible()
  await shot(page, 'desktop-documents-dark')

  await page.goto('/')
  await page.locator('input[type=file]').setInputFiles(path.resolve(import.meta.dirname, 'fixtures/sample.pdf'))
  await expect(page.getByRole('list', { name: 'Attached documents' })).toContainText('sample.pdf')
  await send(page, 'What does chlorophyll absorb?')
  await expect(page.getByText('Here is a mocked answer to:')).toBeVisible()
})

test('memory: learned from chat, used in later chats, editable', async ({ page }) => {
  await page.goto('/#/memory')
  await expect(page.getByRole('heading', { name: 'Memory' })).toBeVisible()
  const clearAll = page.getByRole('button', { name: 'Clear all memories' })
  await expect(page.getByText('No memories yet.').or(clearAll)).toBeVisible()
  if (await clearAll.isVisible()) {
    await clearAll.click()
    await page.getByRole('button', { name: 'Clear all', exact: true }).click()
  }
  await expect(page.getByText('No memories yet.')).toBeVisible()

  await page.goto('/')
  await send(page, 'I am a marine biologist. What is krill?')
  await expect(page.getByText('Here is a mocked answer to:')).toBeVisible()

  // Learning runs in the background after the answer, so reload until it shows up.
  await page.goto('/#/memory')
  await expect(async () => {
    await page.reload()
    await expect(page.getByText('The user is a marine biologist.')).toBeVisible({ timeout: 1_000 })
  }).toPass({ timeout: 10_000 })
  await expect(page.getByText('Learned from a conversation')).toBeVisible()

  await page.getByLabel('New memory', { exact: true }).fill('I prefer answers with tables')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByText('I prefer answers with tables')).toBeVisible()
  await expect(page.getByText('Added by you')).toBeVisible()
  await shot(page, 'desktop-memory-dark')

  await page.getByRole('button', { name: 'Edit memory: The user is a marine biologist.' }).click()
  await page.getByLabel('Edit memory', { exact: true }).fill('The user is an ocean scientist.')
  await page.getByRole('button', { name: 'Save memory' }).click()
  await expect(page.getByText('The user is an ocean scientist.')).toBeVisible()

  // A new conversation is personalized with both memories, and they survive a reload.
  await page.goto('/')
  await send(page, 'Tell me about whales')
  await expect(page.getByText('Personalized with 2 saved memories.')).toBeVisible()
  await page.goto('/#/memory')
  await page.reload()
  await expect(page.getByText('The user is an ocean scientist.')).toBeVisible()

  await page.getByRole('button', { name: 'Delete memory: I prefer answers with tables' }).click()
  await expect(page.getByText('I prefer answers with tables')).toHaveCount(0)
  await page.getByRole('checkbox', { name: /Learn automatically/ }).uncheck()
  await page.reload()
  await expect(page.getByRole('checkbox', { name: /Learn automatically/ })).not.toBeChecked()
  await page.getByRole('checkbox', { name: /Learn automatically/ }).check()
})

test('settings: status and connection test', async ({ page }) => {
  await page.goto('/#/settings')
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page.getByRole('term').filter({ hasText: 'GEMINI_API_KEY' })).toBeVisible()
  await expect(page.getByText('mock-gemini')).toBeVisible()
  await page.getByRole('button', { name: 'Test Gemini connection' }).click()
  await expect(page.getByText(/Connected\. Model mock-gemini responded\./)).toBeVisible()
  await shot(page, 'desktop-settings-dark')
})

test('light theme toggle', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Switch to light theme' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.waitForTimeout(400) // let color transitions finish
  await shot(page, 'desktop-home-light')
  await page.reload()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
})

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test('layout fits and sidebar opens as drawer', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Open sidebar' })).toBeVisible()
    await noHorizontalOverflow(page)
    await shot(page, 'mobile-home-dark')
    await send(page, 'Hello from a phone')
    await expect(page.getByText('Chat · Gemini (mock-gemini)')).toBeVisible()
    await noHorizontalOverflow(page)
    await shot(page, 'mobile-chat-dark')
    await page.getByRole('button', { name: 'Open sidebar' }).click()
    await expect(page.getByRole('navigation', { name: 'Sidebar' })).toBeVisible()
    await shot(page, 'mobile-sidebar-dark')
    await page.getByRole('navigation', { name: 'Sidebar' }).getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await noHorizontalOverflow(page)
  })
})
