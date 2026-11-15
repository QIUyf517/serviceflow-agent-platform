import { expect, test } from '@playwright/test'

test('phase 4.5A storefront keeps products public and customer data identity-bound', async ({ page }) => {
  await page.goto('/store')

  await expect(page.getByRole('heading', { name: '模拟商品 #e2e-product' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '订单信息只对本人开放' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '选择要处理的订单' })).toHaveCount(0)

  await page.getByRole('button', { name: '查看商品' }).click()
  await expect(page.getByRole('dialog', { name: '模拟商品 #e2e-product' })).toBeVisible()
  await expect(page.getByRole('article', { name: '商品 模拟商品 #e2e-product 详情' })).toContainText('e2e-item')
  await page.getByRole('button', { name: '加入购物车' }).click()
  await expect(page.getByRole('link', { name: '核验身份后结算' })).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).click()

  await page.getByLabel('模拟账户邮箱').fill('cancel.phase4@example.invalid')
  await page.getByRole('button', { name: '核验并查看订单' }).click()
  await expect(page.getByText('e2e-cancel', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '提交模拟订单' }).click()
  await expect(page.getByText(/下单成功/)).toBeVisible()
  await page.getByRole('button', { name: '联系商家客服' }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).click()

  const previousSession = await page.evaluate(() => localStorage.getItem('serviceflow.session_id'))
  await page.getByRole('button', { name: '切换模拟顾客' }).click()
  await expect(page.getByText('已建立新的模拟顾客会话，请重新核验身份。')).toBeVisible()
  await expect(page.getByText('e2e-cancel', { exact: true })).toHaveCount(0)
  const nextSession = await page.evaluate(() => localStorage.getItem('serviceflow.session_id'))
  expect(nextSession).not.toBe(previousSession)
})
