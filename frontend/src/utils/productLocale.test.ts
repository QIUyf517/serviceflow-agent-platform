import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { optionLabel, optionValue, productName } from './productLocale'

interface RetailProduct {
  product_id: string
  name: string
  variants: Record<string, { options: Record<string, string> }>
}

interface RetailSnapshot {
  products: Record<string, RetailProduct>
}

const SNAPSHOT = resolve(
  process.cwd(),
  '..',
  'data',
  'raw',
  'tau2',
  'da0835f6c67baef58bdda18f2a3b037dfb3a1754',
  'db.json',
)

describe('商品中文展示', () => {
  it('对未知英文商品和规格安全降级，不直接暴露英文', () => {
    expect(productName('Unknown Product', 'p-1')).toBe('模拟商品 #p-1')
    expect(productName('中文商品', 'p-2')).toBe('中文商品')
    expect(optionLabel('unknown option')).toBe('规格')
    expect(optionValue('unknown value')).toBe('规格值')
  })

  it.runIf(existsSync(SNAPSHOT))('覆盖固定 Retail 快照的全部商品、规格字段和规格值', () => {
    const snapshot = JSON.parse(readFileSync(SNAPSHOT, 'utf8')) as RetailSnapshot
    expect(Object.keys(snapshot.products)).toHaveLength(50)

    for (const product of Object.values(snapshot.products)) {
      expect(productName(product.name, product.product_id), product.name).toMatch(/[\u3400-\u9fff]/u)
      for (const variant of Object.values(product.variants)) {
        for (const [key, value] of Object.entries(variant.options)) {
          expect(optionLabel(key), key).not.toBe('规格')
          expect(optionValue(value), value).not.toBe('规格值')
        }
      }
    }
  })
})
