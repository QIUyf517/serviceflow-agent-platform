import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { chromium } from '@playwright/test'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const outputDir = path.resolve(scriptDir, '../../docs/images')
const baseUrl = process.env.PORTFOLIO_BASE_URL ?? 'http://127.0.0.1:5173'

await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 1,
})

try {
  await page.goto(`${baseUrl}/store`, { waitUntil: 'networkidle' })
  await page.screenshot({
    path: path.join(outputDir, 'storefront.png'),
  })

  await page.getByRole('button', { name: '查看商品' }).first().click()
  await page.getByRole('dialog').waitFor()
  await page.screenshot({
    path: path.join(outputDir, 'product-detail.png'),
  })
} finally {
  await browser.close()
}

console.log(`Portfolio screenshots written to ${outputDir}`)
