import { expect, test as base, type Page } from '@playwright/test'

const storageKey = 'rackline:gpu:preview:v1'

type DemoState = {
  walletBalance: number
  supplied: number
  debt: number
  interest: number
  connected: boolean
  vaultAssets: number
  vaultCash: number
  queue: { id: string; amount: number; status: 'pending' | 'claimable' }[]
}

const test = base.extend<{ demoGuard: void }>({
  demoGuard: [async ({ context, page }, use) => {
    const externalRequests: string[] = []
    const walletRequests: string[] = []
    const errors: string[] = []

    await context.route('**/*', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (['http:', 'https:'].includes(url.protocol)
        && (url.origin !== 'http://127.0.0.1:4173'
          || request.method() === 'POST'
          || /^\/api(?:\/|$)/.test(url.pathname))) {
        externalRequests.push(`${request.method()} ${url.origin}${url.pathname}`)
        await route.abort('blockedbyclient')
        return
      }
      await route.continue()
    })
    await page.exposeFunction('recordDemoWalletRequest', (method: string) => {
      walletRequests.push(method)
    })
    await page.addInitScript(() => {
      if (!sessionStorage.getItem('rackline:qa:initialized')) {
        localStorage.clear()
        sessionStorage.setItem('rackline:qa:initialized', 'true')
      }
      Reflect.set(window, 'ethereum', {
        isMetaMask: true,
        request: async ({ method }: { method: string }) => {
          const record = Reflect.get(window, 'recordDemoWalletRequest') as (value: string) => Promise<void>
          await record(method)
          throw new Error(`Demo must not request a real wallet: ${method}`)
        },
        on: () => undefined,
        removeListener: () => undefined,
      })
    })
    page.on('pageerror', (error) => errors.push(error.message))

    await use()

    expect(walletRequests, 'Demo interactions must never invoke an injected wallet').toEqual([])
    expect(externalRequests, 'The demo must not request an external API or RPC').toEqual([])
    expect(errors, 'The demo must not throw uncaught browser errors').toEqual([])
  }, { auto: true }],
})

async function navigate(page: Page, name: string) {
  const navigation = page.getByRole('navigation', { name: 'Main navigation' })
  if (!await navigation.isVisible()) {
    await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  }
  await navigation.getByRole('button', { name, exact: true }).click()
}

async function readState(page: Page): Promise<DemoState> {
  return page.evaluate((key) => {
    const persisted = localStorage.getItem(key)
    if (!persisted) throw new Error('Expected demo state to be persisted after an interaction')
    return JSON.parse(persisted).state
  }, storageKey)
}

async function transact(page: Page, action: 'Supply' | 'Withdraw' | 'Borrow' | 'Repay', amount: string, result: 'complete' | 'queued' = 'complete') {
  await page.getByRole('main').getByRole('button', { name: action, exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAccessibleName(`${action} demo USDC`)
  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  await dialog.getByLabel('Amount in demo USDC').fill(amount)
  const operation = action === 'Repay' ? 'repayment' : action === 'Withdraw' ? 'withdrawal' : action.toLowerCase()
  await dialog.getByRole('button', { name: `Review ${operation}`, exact: true }).click()
  await dialog.getByRole('button', { name: `Confirm demo ${operation}`, exact: true }).click()
  const completed = action === 'Repay' ? 'Repayment' : action === 'Withdraw' ? 'Withdrawal' : action
  await expect(dialog.getByRole('heading', { name: `${completed} ${result}`, exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Done', exact: true }).click()
  await expect(dialog).not.toBeVisible()
}

test('renders the demo and navigates every screen without horizontal page overflow', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Rackline overview', exact: true })).toBeVisible()
  await expect(page.getByText('INTERACTIVE DEMO', { exact: true })).toBeVisible()
  const main = page.getByRole('main')
  await expect(main).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('overview.png'), fullPage: true })

  let previousContent = ''
  for (const screen of ['Overview', 'Earn', 'Borrow', 'Providers', 'Activity', 'Operations']) {
    await navigate(page, screen)
    await expect(main).toBeVisible()
    await expect(main.getByRole('heading', { level: 1 })).toBeVisible()
    if (previousContent) await expect(main).not.toHaveText(previousContent)
    previousContent = await main.innerText()
    const pageWidth = await page.evaluate(() => Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth,
    ))
    const overflow = pageWidth - page.viewportSize()!.width
    expect(overflow, `${screen} must fit within the ${testInfo.project.name} viewport`).toBeLessThanOrEqual(1)
  }
})

test('supply, withdraw, borrow and repay update demo balances and survive a reload', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect demo wallet', exact: true }).click()
  await expect(page.getByRole('button', { name: /Demo wallet/ })).toBeVisible()
  const initial = await readState(page)
  expect(initial.connected).toBe(true)

  await navigate(page, 'Earn')
  await transact(page, 'Supply', '250')
  const supplied = await readState(page)
  expect(supplied.supplied).toBeCloseTo(initial.supplied + 250, 2)
  expect(supplied.walletBalance).toBeCloseTo(initial.walletBalance - 250, 2)

  await transact(page, 'Withdraw', '100')
  const withdrawn = await readState(page)
  expect(withdrawn.supplied).toBeCloseTo(supplied.supplied - 100, 2)
  expect(withdrawn.walletBalance).toBeCloseTo(supplied.walletBalance + 100, 2)

  await navigate(page, 'Borrow')
  await transact(page, 'Borrow', '100')
  const borrowed = await readState(page)
  expect(borrowed.debt).toBeCloseTo(withdrawn.debt + 100, 2)
  expect(borrowed.walletBalance).toBeCloseTo(withdrawn.walletBalance + 100, 2)

  await transact(page, 'Repay', '50')
  const repaid = await readState(page)
  expect(repaid.debt + repaid.interest).toBeCloseTo(borrowed.debt + borrowed.interest - 50, 2)
  expect(repaid.walletBalance).toBeCloseTo(borrowed.walletBalance - 50, 2)

  await page.reload()
  await expect(page.getByRole('main')).toBeVisible()
  expect(await readState(page)).toMatchObject(repaid)
})

test('invalid amounts cannot reach confirmation or change balances', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect demo wallet', exact: true }).click()
  const initial = await readState(page)
  await navigate(page, 'Earn')
  await page.getByRole('button', { name: 'Supply', exact: true }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Supply demo USDC' })
  for (const amount of ['-1', '900000000']) {
    await dialog.getByLabel('Amount in demo USDC').fill(amount)
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Review supply', exact: true })).toBeDisabled()
    expect(await readState(page)).toMatchObject(initial)
  }
  await dialog.getByRole('button', { name: 'Close transaction', exact: true }).click()
  await expect(dialog).not.toBeVisible()
})

test('connecting a sample provider requires consent and does not approve credit', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect demo wallet', exact: true }).click()
  const initial = await readState(page)
  await navigate(page, 'Providers')
  await page.getByRole('button', { name: 'Connect provider', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toHaveAccessibleName('Connect your compute.')
  await dialog.getByRole('button', { name: /^GPU\.net/ }).click()
  await dialog.getByLabel('Connection name').fill('QA demo cluster')
  await dialog.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled()
  await dialog.getByRole('checkbox', { name: /does not approve a loan/ }).check()
  await expect(dialog.getByRole('button', { name: 'Continue', exact: true })).toBeDisabled()
  await dialog.getByRole('checkbox', { name: /create a sample connection/ }).check()
  await dialog.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(dialog.getByText('Pending review', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Add sample connection', exact: true }).click()
  await expect(dialog).toHaveAccessibleName('Your sample account is ready.')
  await dialog.getByRole('button', { name: 'View connection', exact: true }).click()
  await expect(page.getByRole('main').getByText('QA demo cluster', { exact: true })).toBeVisible()
  expect(await readState(page)).toMatchObject(initial)
})

test('proof and control interruptions block borrowing while direct repayment remains available', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect demo wallet', exact: true }).click()
  await navigate(page, 'Borrow')
  const main = page.getByRole('main')
  for (const scenario of ['proof-pending', 'control-expired']) {
    const before = await readState(page)
    await page.getByLabel('Facility condition').selectOption(scenario)
    await expect(main.getByRole('button', { name: 'Borrow', exact: true })).toBeDisabled()
    await expect(main.getByRole('button', { name: 'Repay', exact: true })).toBeEnabled()
    const interrupted = await readState(page)
    expect(interrupted.debt + interrupted.interest).toBeCloseTo(before.debt + before.interest, 2)
    await transact(page, 'Repay', '1')
    const repaid = await readState(page)
    expect(repaid.debt + repaid.interest).toBeCloseTo(before.debt + before.interest - 1, 2)
  }
  await page.getByLabel('Facility condition').selectOption('healthy')
  await expect(main.getByRole('button', { name: 'Borrow', exact: true })).toBeEnabled()
})

test('a queued withdrawal requires liquidity before settlement and credits the wallet only once on claim', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Connect demo wallet', exact: true }).click()
  const initial = await readState(page)
  await navigate(page, 'Earn')
  const main = page.getByRole('main')
  await main.getByRole('button', { name: 'Try limited liquidity', exact: true }).click()
  const stressed = await readState(page)
  expect(stressed.vaultCash).toBe(5000)
  expect(stressed.vaultAssets).toBe(initial.vaultAssets)
  expect(stressed.walletBalance).toBe(initial.walletBalance)
  expect(stressed.debt + stressed.interest).toBe(initial.debt + initial.interest)

  await transact(page, 'Withdraw', '6000', 'queued')
  const queued = await readState(page)
  expect(queued.queue).toEqual([{ id: expect.any(String), amount: 6000, status: 'pending' }])
  expect(queued.supplied).toBeCloseTo(initial.supplied - 6000, 2)
  expect(queued.walletBalance).toBe(initial.walletBalance)
  expect(queued.vaultCash).toBe(5000)
  await main.getByRole('button', { name: 'Simulate settlement', exact: true }).click()
  expect(await readState(page)).toMatchObject(queued)
  await expect(main.getByRole('button', { name: 'Claim demo funds', exact: true })).toHaveCount(0)

  await navigate(page, 'Borrow')
  await transact(page, 'Repay', '1000')
  const repaid = await readState(page)
  expect(repaid.vaultCash).toBe(6000)
  expect(repaid.debt + repaid.interest).toBeCloseTo(initial.debt + initial.interest - 1000, 2)
  await navigate(page, 'Earn')
  await main.getByRole('button', { name: 'Simulate settlement', exact: true }).click()
  await expect(main.getByRole('button', { name: 'Claim demo funds', exact: true })).toBeVisible()
  const settled = await readState(page)
  expect(settled.queue).toEqual([{ ...queued.queue[0], status: 'claimable' }])
  expect(settled.vaultCash).toBe(0)
  expect(settled.vaultAssets).toBeCloseTo(repaid.vaultAssets - 6000, 2)
  expect(settled.walletBalance).toBe(repaid.walletBalance)

  await main.getByRole('button', { name: 'Claim demo funds', exact: true }).click()
  const claimed = await readState(page)
  expect(claimed.queue).toEqual([])
  expect(claimed.walletBalance).toBeCloseTo(repaid.walletBalance + 6000, 2)
  await expect(main.getByText('Nothing in the queue', { exact: true })).toBeVisible()
  await expect(main.getByRole('button', { name: 'Claim demo funds', exact: true })).toHaveCount(0)
  await page.reload()
  await navigate(page, 'Earn')
  expect(await readState(page)).toMatchObject(claimed)
  await expect(main.getByRole('button', { name: 'Claim demo funds', exact: true })).toHaveCount(0)
})
