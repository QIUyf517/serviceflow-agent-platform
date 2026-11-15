import { expect, test, type APIResponse, type Page } from '@playwright/test'

const configuredOperatorToken = process.env.E2E_OPERATOR_TOKEN
if (!configuredOperatorToken) throw new Error('E2E_OPERATOR_TOKEN is required')
const operatorToken: string = configuredOperatorToken

interface CurrentTaskBody {
  pending_confirmation: { request_id: string } | null
}

interface OrderBody {
  status: string
}

interface AuditBody {
  events: Array<{ event_type: string }>
}

async function responseBody<T>(response: APIResponse): Promise<T> {
  return JSON.parse(await response.text()) as T
}

async function verify(page: Page, email: string, expectedOrder: string) {
  await page.goto('/support')
  await expect(page.getByRole('heading', { name: '订单信息只对本人开放' })).toBeVisible()
  await page.getByLabel('模拟账户邮箱').fill(email)
  await page.getByRole('button', { name: '核验并查看订单' }).click()
  await expect(page.getByText(expectedOrder, { exact: true }).first()).toBeVisible()
}

async function send(page: Page, message: string) {
  if (!(await page.getByLabel('输入售后问题').isVisible())) {
    await page.getByRole('button', { name: '联系商家客服' }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
  }
  await page.getByLabel('输入售后问题').fill(message)
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('status', { name: '正在处理并核对服务端状态…' })).toBeHidden()
}

async function sessionId(page: Page): Promise<string> {
  const value = await page.evaluate(() => localStorage.getItem('serviceflow.session_id'))
  if (!value) throw new Error('ServiceFlow session was not created')
  return value
}

async function currentTask(page: Page, orderId?: string) {
  const sid = await sessionId(page)
  const query = orderId ? `?order_id=${encodeURIComponent(orderId)}` : ''
  const response = await page.request.get(`/api/v1/multi-agent/tasks/current${query}`, {
    headers: { 'X-Session-Id': sid },
  })
  expect(response.ok()).toBeTruthy()
  return { sid, body: await responseBody<CurrentTaskBody>(response) }
}

async function openAdmin(page: Page) {
  await page.goto('/admin')
  if (await page.getByLabel('X-Operator-Token').isVisible()) {
    await page.getByLabel('X-Operator-Token').fill(operatorToken)
    await page.getByRole('button', { name: '验证并打开工单' }).click()
  }
  await expect(page.getByRole('heading', { name: '工单列表' })).toBeVisible()
}

async function navigateInApp(page: Page, path: string) {
  await page.evaluate(
    "history.pushState({}, '', " + JSON.stringify(path) + "); dispatchEvent(new PopStateEvent('popstate'))",
  )
}

test.describe.serial('phase 4 real browser acceptance', () => {
  test('identity, order query, cancel confirmation, audit, and success trace', async ({ page }) => {
    await verify(page, 'cancel.phase4@example.invalid', 'e2e-cancel')
    await page.getByRole('button', { name: /e2e-cancel/ }).click()
    await expect(page.getByLabel('订单 e2e-cancel 详情')).toContainText('待处理')

    await send(page, 'Please cancel order e2e-cancel because ordered by mistake')
    await expect(page.getByRole('heading', { name: '核对即将执行的操作' })).toBeVisible()
    await expect(page.locator('.action-summary')).toContainText('取消订单')
    await expect(page.locator('.action-summary')).toContainText('e2e-cancel')
    await expect(page.locator('.action-summary')).toContainText('下错单')
    const waiting = await currentTask(page, 'e2e-cancel')
    if (!waiting.body.pending_confirmation) throw new Error('pending confirmation was not persisted')
    const requestId = waiting.body.pending_confirmation.request_id

    await page.getByRole('button', { name: '确认取消订单' }).click()
    await expect(page.getByText('服务端已执行成功', { exact: true })).toBeVisible()
    await expect(page.getByText(/待处理 → 已取消/)).toBeVisible()

    const order = await page.request.get('/api/v1/orders/e2e-cancel', {
      headers: { 'X-Session-Id': waiting.sid },
    })
    expect((await responseBody<OrderBody>(order)).status).toBe('cancelled')
    const audit = await page.request.get(`/api/v1/multi-agent/cancel-requests/${requestId}/audit`, {
      headers: { 'X-Session-Id': waiting.sid },
    })
    const eventTypes = (await responseBody<AuditBody>(audit)).events.map((event) => event.event_type)
    expect(eventTypes).toContain('user_confirmed')
    expect(eventTypes).toContain('execution_succeeded')

    await page.getByRole('button', { name: '关闭' }).click()
    await navigateInApp(page, '/developer')
    await expect(page.getByRole('heading', { name: '成功 trace' })).toBeVisible()
    await expect(page.getByText('mock_local').first()).toBeVisible()
  })

  test('return confirmation shows the real terminal state', async ({ page }) => {
    await verify(page, 'return.phase4@example.invalid', 'e2e-return')
    await send(page, 'Please return order e2e-return item_quantities=e2e-item:1 payment_method_id=e2e-card')
    await expect(page.locator('.action-summary')).toContainText('提交退货申请')
    await expect(page.locator('.action-summary')).toContainText('e2e-item')
    await expect(page.locator('.action-summary')).toContainText('e2e-card')

    await page.getByRole('button', { name: '确认提交退货申请' }).click()
    await expect(page.getByText('服务端已执行成功', { exact: true })).toBeVisible()
    await expect(page.getByText(/已送达 → 已申请退货/)).toBeVisible()
    const { sid } = await currentTask(page, 'e2e-return')
    const order = await page.request.get('/api/v1/orders/e2e-return', {
      headers: { 'X-Session-Id': sid },
    })
    expect((await responseBody<OrderBody>(order)).status).toBe('return requested')
  })

  test('unconfirmed proposal performs zero writes and refresh restores it', async ({ page }) => {
    await verify(page, 'pending.phase4@example.invalid', 'e2e-no-confirm')
    await send(page, 'Please cancel order e2e-no-confirm because ordered by mistake')
    await expect(page.getByRole('heading', { name: '核对即将执行的操作' })).toBeVisible()
    const { sid } = await currentTask(page, 'e2e-no-confirm')

    const before = await page.request.get('/api/v1/orders/e2e-no-confirm', {
      headers: { 'X-Session-Id': sid },
    })
    expect((await responseBody<OrderBody>(before)).status).toBe('pending')
    await page.reload()
    await expect(page.getByText('已从服务端恢复当前任务')).toBeVisible()
    await expect(page.getByRole('heading', { name: '核对即将执行的操作' })).toBeVisible()
    await expect(page.locator('.action-summary')).toContainText('e2e-no-confirm')
    const after = await page.request.get('/api/v1/orders/e2e-no-confirm', {
      headers: { 'X-Session-Id': sid },
    })
    expect((await responseBody<OrderBody>(after)).status).toBe('pending')
  })

  test('human ticket is assigned, moved in progress, and audited', async ({ page }) => {
    await verify(page, 'human.phase4@example.invalid', 'e2e-human')
    await page.getByRole('button', { name: '联系商家客服' }).click()
    await page.getByRole('button', { name: '创建人工工单' }).click()
    const ticketNotice = page.getByRole('status').filter({ hasText: '已创建工单' })
    await expect(ticketNotice).toBeVisible()
    const ticketNo = (await ticketNotice.locator('strong').textContent())?.replace('已创建工单 ', '') ?? ''
    await expect(page.getByText(/人工处理进度/)).toBeVisible()

    await openAdmin(page)
    await page.getByRole('button', { name: new RegExp(ticketNo) }).click()
    await expect(page.getByRole('heading', { name: ticketNo })).toBeVisible()
    await page.getByLabel('分配客服').fill('phase4-operator')
    await page.getByRole('button', { name: '保存分配' }).click()
    await expect(page.getByText('已分配', { exact: true }).last()).toBeVisible()
    await page.getByLabel('合法状态流转').selectOption('in_progress')
    await page.getByRole('button', { name: '更新状态' }).click()
    await expect(page.getByText('处理中', { exact: true }).last()).toBeVisible()
    await expect(page.getByText('ticket_assigned')).toBeVisible()
    await expect(page.getByText('ticket_status_changed')).toBeVisible()
  })

  test('operator approval cannot replace customer confirmation', async ({ page }) => {
    await verify(page, 'approval.phase4@example.invalid', 'e2e-approval')
    await send(page, 'Please cancel order e2e-approval because ordered by mistake')
    await expect(page.getByRole('heading', { name: '核对即将执行的操作' })).toBeVisible()
    await page.getByRole('button', { name: '创建人工工单' }).click()
    const ticketNotice = page.getByRole('status').filter({ hasText: '已创建工单' })
    await expect(ticketNotice).toBeVisible()
    const ticketNo = (await ticketNotice.locator('strong').textContent())?.replace('已创建工单 ', '') ?? ''

    await openAdmin(page)
    await page.getByRole('button', { name: new RegExp(ticketNo) }).click()
    await page.getByRole('button', { name: '创建审批' }).click()
    await expect(page.getByText('pending', { exact: true })).toBeVisible()
    await page.getByLabel('决定理由').fill('Phase 4 browser review')
    await page.getByRole('button', { name: '批准审批' }).click()
    await expect(page.getByText('决定：Phase 4 browser review')).toBeVisible()
    await page.getByRole('button', { name: '请求服务端代执行' }).click()
    await expect(page.getByText(/confirmation_required：审批不能替代客户确认/)).toBeVisible()
  })

  test('developer page shows a real failed trace', async ({ browser, page }) => {
    await verify(page, 'race.phase4@example.invalid', 'e2e-race')
    await send(page, 'Please cancel order e2e-race because ordered by mistake')

    const competing = await browser.newContext()
    const competitor = await competing.newPage()
    await verify(competitor, 'race.phase4@example.invalid', 'e2e-race')
    await send(competitor, 'Please cancel order e2e-race because ordered by mistake')
    await competitor.getByRole('button', { name: '确认取消订单' }).click()
    await expect(competitor.getByText('服务端已执行成功', { exact: true })).toBeVisible()
    await competing.close()

    await page.getByRole('button', { name: '确认取消订单' }).click()
    await expect(page.getByText('操作没有执行', { exact: true })).toBeVisible()
    await expect(page.getByText(/订单状态已变化/).first()).toBeVisible()
    await page.getByRole('button', { name: '关闭' }).click()
    await navigateInApp(page, '/developer')
    await expect(page.getByRole('heading', { name: '失败 trace' })).toBeVisible()
    await expect(page.getByText('order_changed', { exact: false }).first()).toBeVisible()
  })
})
