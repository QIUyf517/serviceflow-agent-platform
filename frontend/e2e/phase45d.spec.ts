import { expect, test, type Page } from '@playwright/test'

async function send(page: Page, message: string) {
  await page.getByLabel('输入售后问题').fill(message)
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('status', { name: '正在处理并核对服务端状态…' })).toBeHidden()
}

test('phase 4.5D keeps two orders of one customer in separate threads', async ({ page }) => {
  await page.goto('/store')
  await page.getByLabel('模拟账户邮箱').fill('thread.phase4@example.invalid')
  await page.getByRole('button', { name: '核验并查看订单' }).click()
  await expect(page.getByText('e2e-thread-a', { exact: true }).first()).toBeVisible()

  const supportButtons = page.getByRole('button', { name: '联系商家客服' })
  await supportButtons.nth(0).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  const firstHeading = (await dialog.getByRole('heading').first().textContent()) ?? ''
  await send(page, '这是第一笔订单的消息')

  await page.getByRole('button', { name: '关闭' }).click()
  await supportButtons.nth(1).click()
  await expect(dialog).toBeVisible()
  const secondHeading = (await dialog.getByRole('heading').first().textContent()) ?? ''
  expect(secondHeading).not.toBe(firstHeading)
  await expect(page.getByText('这是第一笔订单的消息')).toHaveCount(0)
  await send(page, '这是第二笔订单的消息')

  await page.reload()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText('这是第二笔订单的消息')).toBeVisible()
  await expect(page.getByText('这是第一笔订单的消息')).toHaveCount(0)

  await page.getByRole('button', { name: '关闭' }).click()
  await supportButtons.nth(0).click()
  await expect(page.getByText('这是第一笔订单的消息')).toBeVisible()
  await expect(page.getByText('这是第二笔订单的消息')).toHaveCount(0)
})
