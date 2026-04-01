import { test, expect, ConsoleMessage } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

const CONSOLE_LOG_FILE = path.join(__dirname, 'logs', 'browser-console.log')

test.describe('Full research flow', () => {
  let consoleLogs: string[] = []

  test.beforeEach(async ({ page }) => {
    consoleLogs = []
    page.on('console', (msg: ConsoleMessage) =>
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`)
    )
    page.on('pageerror', (err: Error) =>
      consoleLogs.push(`[pageerror] ${err.message}`)
    )
    page.on('request', (req) => {
      if (req.url().includes('localhost:8000')) {
        consoleLogs.push(`[net:request] ${req.method()} ${req.url()}`)
      }
    })
    page.on('response', (res) => {
      if (res.url().includes('localhost:8000')) {
        consoleLogs.push(`[net:response] ${res.status()} ${res.url()}`)
      }
    })
    page.on('requestfailed', (req) => {
      if (req.url().includes('localhost:8000')) {
        consoleLogs.push(`[net:failed] ${req.failure()?.errorText} ${req.url()}`)
      }
    })
  })

  test.afterEach(async ({}, testInfo) => {
    const logDir = path.join(__dirname, 'logs')
    if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true })
    const header = `\n=== ${testInfo.title} | ${testInfo.status} | ${new Date().toISOString()} ===\n`
    fs.appendFileSync(CONSOLE_LOG_FILE, header + consoleLogs.join('\n') + '\n')
  })

  test('Phase 1→2→3→4: initial → chatting → generating → completed', async ({ page }) => {
    // Phase 1: initial
    await page.goto('/chat')
    // Wait for React to hydrate — click focuses the element and confirms event handlers are attached
    const textarea = page.getByTestId('initial-prompt-textarea')
    await expect(textarea).toBeVisible()
    await textarea.click()
    await textarea.fill('When US GDP contracts, what happens to unemployment? Analyze the historical relationship between US real GDP growth and the unemployment rate over the last 20 years and explain what the data shows.')
    // Confirm React state updated (button becomes enabled) before clicking
    const submitBtn = page.getByTestId('initial-prompt-submit')
    await expect(submitBtn).toBeEnabled({ timeout: 5_000 })
    await submitBtn.click()

    // Phase 2: chatting — chat panel appears while backend starts
    await expect(page.getByTestId('chat-messages')).toBeVisible({ timeout: 60_000 })

    // Phase 2→3 transition: either the orchestrator asks a clarifying question
    // (begin-research-btn becomes enabled) or it starts the pipeline immediately
    // (auto-transition via subagent updates → generation-loading appears).
    const generationLoading = page.getByTestId('generation-loading')
    const beginBtn = page.getByTestId('begin-research-btn')

    // Poll every second for up to 120s for either condition
    let transitioned: 'generating' | 'chatting' | null = null
    for (let i = 0; i < 120 && transitioned === null; i++) {
      await page.waitForTimeout(1_000)
      const isGenerating = await generationLoading.isVisible().catch(() => false)
      if (isGenerating) { transitioned = 'generating'; break }
      const btnDisabled = await beginBtn.getAttribute('disabled').catch(() => 'true')
      if (btnDisabled === null) { transitioned = 'chatting'; break }
    }
    expect(transitioned, 'Expected either generation-loading or begin-research-btn to become active within 120s').not.toBeNull()

    if (transitioned === 'chatting') {
      // Orchestrator asked a clarifying question — click Begin research
      await beginBtn.click()
      // Phase 3: generating
      await expect(generationLoading).toBeVisible({ timeout: 30_000 })
    }
    // else: already in Phase 3 via auto-transition

    // Phase 4: completed — results panel appears after pipeline finishes
    await expect(page.getByTestId('results-panel')).toBeVisible({ timeout: 600_000 })
    await expect(page.getByTestId('results-panel')).not.toBeEmpty()
  })
})
