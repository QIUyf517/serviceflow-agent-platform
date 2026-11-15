import { useState } from 'react'

import type { CheckoutResult, ProductVariant, UserProfile } from '../api/types'
import { optionLabel, optionValue, productName } from '../utils/productLocale'
import { StateNotice } from './StateNotice'

export interface CartLine {
  productId: string
  productName: string
  variant: ProductVariant
  quantity: number
}

interface StoreCartProps {
  lines: CartLine[]
  verified: boolean
  profile: UserProfile | undefined
  isProfileLoading: boolean
  isCheckingOut: boolean
  checkoutError?: string
  checkoutResult: CheckoutResult | null
  onQuantityChange: (itemId: string, quantity: number) => void
  onRemove: (itemId: string) => void
  onCheckout: (paymentMethodId: string) => void
}

function paymentLabel(method: UserProfile['payment_methods'][string]): string {
  if (method.source === 'credit_card') {
    return `${method.brand ?? '银行卡'}（尾号 ${method.last_four ?? '未知'}）`
  }
  if (method.source === 'paypal') return 'PayPal'
  if (method.source === 'gift_card') return `礼品卡（余额 ${method.balance?.toFixed(2) ?? '0.00'}）`
  return method.source
}

export function StoreCart({
  lines,
  verified,
  profile,
  isProfileLoading,
  isCheckingOut,
  checkoutError,
  checkoutResult,
  onQuantityChange,
  onRemove,
  onCheckout,
}: StoreCartProps) {
  const paymentMethods = profile
    ? Object.entries(profile.payment_methods).map(([id, method]) => ({ ...method, id }))
    : []
  const [paymentMethodId, setPaymentMethodId] = useState('')
  const selectedPaymentMethodId = paymentMethods.some((method) => method.id === paymentMethodId)
    ? paymentMethodId
    : (paymentMethods[0]?.id ?? '')

  const itemCount = lines.reduce((sum, line) => sum + line.quantity, 0)
  const total = lines.reduce((sum, line) => sum + line.variant.price * line.quantity, 0)

  return (
    <aside className="store-cart" id="cart" aria-labelledby="cart-title">
      <header>
        <div>
          <span>购物车</span>
          <h2 id="cart-title">已选商品</h2>
        </div>
        <strong>{itemCount} 件</strong>
      </header>

      {lines.length === 0 ? (
        <p className="cart-empty">打开商品规格，选择可用款式加入购物车。</p>
      ) : (
        <ul className="cart-lines">
          {lines.map((line) => (
            <li key={line.variant.item_id}>
              <div>
                <strong>{productName(line.productName, line.productId)}</strong>
                <small>
                  {Object.entries(line.variant.options)
                    .map(([key, value]) => `${optionLabel(key)}：${optionValue(value)}`)
                    .join('，') || '单一规格'}
                </small>
                <button type="button" className="cart-remove" onClick={() => onRemove(line.variant.item_id)}>
                  移除
                </button>
              </div>
              <label>
                <span className="sr-only">{productName(line.productName, line.productId)}数量</span>
                <select
                  value={line.quantity}
                  onChange={(event) => onQuantityChange(line.variant.item_id, Number(event.target.value))}
                >
                  {Array.from({ length: 10 }, (_, index) => index + 1).map((quantity) => (
                    <option key={quantity} value={quantity}>{quantity}</option>
                  ))}
                </select>
              </label>
              <b>金额 {(line.variant.price * line.quantity).toFixed(2)}</b>
            </li>
          ))}
        </ul>
      )}

      <div className="cart-total">
        <span>合计</span>
        <strong>金额 {total.toFixed(2)}</strong>
      </div>

      {!verified ? (
        <a className="button cart-checkout" href="#customer-service">核验身份后结算</a>
      ) : null}
      {verified && isProfileLoading ? <StateNotice kind="loading" title="正在读取结算信息" /> : null}
      {verified && profile ? (
        <div className="checkout-fields">
          <p>
            <span>配送至</span>
            {profile.address.state} {profile.address.city} {profile.address.address1}
          </p>
          <label>
            支付方式
            <select value={selectedPaymentMethodId} onChange={(event) => setPaymentMethodId(event.target.value)}>
              {paymentMethods.map((method) => (
                <option key={method.id} value={method.id}>{paymentLabel(method)}</option>
              ))}
            </select>
          </label>
          <button
            className="button cart-checkout"
            type="button"
            disabled={!lines.length || !selectedPaymentMethodId || isCheckingOut}
            onClick={() => onCheckout(selectedPaymentMethodId)}
          >
            {isCheckingOut ? '正在创建订单…' : '提交模拟订单'}
          </button>
        </div>
      ) : null}
      {checkoutError ? <StateNotice kind="error" title="下单没有完成">{checkoutError}</StateNotice> : null}
      {checkoutResult ? (
        <StateNotice kind="success" title="下单成功">
          订单 {checkoutResult.order.order_id} 已创建，可在“我的订单”中查看并联系客服。
        </StateNotice>
      ) : null}
    </aside>
  )
}
