import type { Order } from '../api/types'
import { StateNotice } from './StateNotice'

interface OrdersPanelProps {
  orders: Order[] | undefined
  selectedOrder: Order | null
  isLoading: boolean
  isDetailLoading: boolean
  errorMessage?: string
  detailErrorMessage?: string
  onSelect: (orderId: string) => void
}

function total(order: Order): number {
  return order.items.reduce((sum, item) => sum + item.price, 0)
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '待处理',
    delivered: '已送达',
    cancelled: '已取消',
    'return requested': '退货申请中',
  }
  return labels[status] ?? status
}

export function OrdersPanel({
  orders,
  selectedOrder,
  isLoading,
  isDetailLoading,
  errorMessage,
  detailErrorMessage,
  onSelect,
}: OrdersPanelProps) {
  return (
    <section className="orders-panel" aria-labelledby="orders-title">
      <div className="section-heading">
        <div>
          <p className="section-label">本人订单</p>
          <h2 id="orders-title">选择要处理的订单</h2>
        </div>
        {orders ? <span>{orders.length} 笔</span> : null}
      </div>
      {isLoading ? <StateNotice kind="loading" title="正在读取订单" /> : null}
      {errorMessage ? <StateNotice kind="error" title="订单加载失败">{errorMessage}</StateNotice> : null}
      {!isLoading && !errorMessage && orders?.length === 0 ? (
        <StateNotice title="暂无订单">这个模拟账户下没有可显示的订单。</StateNotice>
      ) : null}
      {orders && orders.length > 0 ? (
        <div className="order-list">
          {orders.map((order) => (
            <button
              className={`order-card ${selectedOrder?.order_id === order.order_id ? 'is-selected' : ''}`}
              key={order.order_id}
              type="button"
              onClick={() => onSelect(order.order_id)}
            >
              <span>
                <strong>{order.order_id}</strong>
                <small>{order.items.length} 件商品 · ¥{total(order).toFixed(2)}</small>
              </span>
              <span className={`status-chip status-${order.status.replaceAll(' ', '-')}`}>
                {statusLabel(order.status)}
              </span>
            </button>
          ))}
        </div>
      ) : null}
      {isDetailLoading ? <StateNotice kind="loading" title="正在读取订单详情" /> : null}
      {detailErrorMessage ? (
        <StateNotice kind="error" title="无法打开订单">{detailErrorMessage}</StateNotice>
      ) : null}
      {selectedOrder && !isDetailLoading ? (
        <article className="order-detail" aria-label={`订单 ${selectedOrder.order_id} 详情`}>
          <div>
            <strong>{selectedOrder.order_id}</strong>
            <span>{statusLabel(selectedOrder.status)}</span>
          </div>
          <ul>
            {selectedOrder.items.map((item) => (
              <li key={item.item_id}>
                <span>{item.name || item.product_id}</span>
                <span>¥{item.price.toFixed(2)}</span>
              </li>
            ))}
          </ul>
          {selectedOrder.fulfillments?.length ? (
            <p className="tracking">
              物流：{selectedOrder.fulfillments.flatMap((item) => item.tracking_id).join('、')}
            </p>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}
