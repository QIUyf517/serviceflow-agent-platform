import { useEffect, useRef } from 'react'

import type { Product, ProductSummary } from '../api/types'
import { optionLabel, optionValue, productName } from '../utils/productLocale'
import { StateNotice } from './StateNotice'

interface ProductCatalogProps {
  products: ProductSummary[] | undefined
  selectedProduct: Product | null
  isDetailOpen: boolean
  isLoading: boolean
  isDetailLoading: boolean
  errorMessage?: string
  detailErrorMessage?: string
  onSelect: (productId: string) => void
  onAddToCart: (product: Product, variant: Product['variants'][string]) => void
  onCloseDetail: () => void
}

interface ProductDetailDialogProps {
  open: boolean
  product: Product | null
  isLoading: boolean
  errorMessage?: string
  onAddToCart: (product: Product, variant: Product['variants'][string]) => void
  onClose: () => void
}

function priceRange(product: ProductSummary): string {
  if (product.min_price === product.max_price) return `金额 ${product.min_price.toFixed(2)}`
  return `金额 ${product.min_price.toFixed(2)} – ${product.max_price.toFixed(2)}`
}

function ProductDetailDialog({
  open,
  product,
  isLoading,
  errorMessage,
  onAddToCart,
  onClose,
}: ProductDetailDialogProps) {
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose, open])

  if (!open) return null
  const variants = product ? Object.values(product.variants) : []

  return (
    <div className="product-dialog-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        className="product-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-dialog-title"
      >
        <header>
          <div>
            <span>商品规格</span>
            <h2 id="product-dialog-title">
              {product ? productName(product.name, product.product_id) : '正在读取商品'}
            </h2>
          </div>
          <button ref={closeButton} className="dialog-close" type="button" onClick={onClose}>
            关闭
          </button>
        </header>
        <div className="product-dialog-body">
          {isLoading ? <StateNotice kind="loading" title="正在读取商品详情" /> : null}
          {errorMessage ? <StateNotice kind="error" title="无法打开商品">{errorMessage}</StateNotice> : null}
          {product && !isLoading ? (
            <article className="product-detail" aria-label={`商品 ${productName(product.name, product.product_id)} 详情`}>
              <p className="product-dialog-code">#{product.product_id}</p>
              <div className="variant-table-wrap">
                <table className="variant-table">
                  <thead>
                    <tr>
                      <th scope="col">规格编号</th>
                      <th scope="col">选项</th>
                      <th scope="col">价格</th>
                      <th scope="col">状态</th>
                      <th scope="col">购买</th>
                    </tr>
                  </thead>
                  <tbody>
                    {variants.map((variant) => (
                      <tr key={variant.item_id}>
                        <td>#{variant.item_id}</td>
                        <td>{Object.entries(variant.options).map(([key, value]) => `${optionLabel(key)}：${optionValue(value)}`).join('，')}</td>
                        <td>{variant.price.toFixed(2)}</td>
                        <td><span className={variant.available ? 'stock-available' : 'stock-unavailable'}>{variant.available ? '可用' : '暂不可用'}</span></td>
                        <td>
                          <button
                            className="variant-cart-button"
                            type="button"
                            disabled={!variant.available}
                            onClick={() => onAddToCart(product, variant)}
                          >
                            {variant.available ? '加入购物车' : '暂不可购买'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          ) : null}
        </div>
      </section>
    </div>
  )
}

export function ProductCatalog({
  products,
  selectedProduct,
  isDetailOpen,
  isLoading,
  isDetailLoading,
  errorMessage,
  detailErrorMessage,
  onSelect,
  onAddToCart,
  onCloseDetail,
}: ProductCatalogProps) {
  return (
    <section className="catalog" id="catalog" aria-labelledby="catalog-title">
      <div className="catalog-heading">
        <div>
          <p>模拟商品目录</p>
          <h1 id="catalog-title">从真实库存开始，把售后讲清楚。</h1>
        </div>
        <p>
          这里展示 τ-bench Retail 固定快照中的模拟商品。价格、规格和可用状态直接来自业务数据库。
        </p>
      </div>

      {isLoading ? <StateNotice kind="loading" title="正在整理商品货架" /> : null}
      {errorMessage ? <StateNotice kind="error" title="商品目录加载失败">{errorMessage}</StateNotice> : null}
      {!isLoading && !errorMessage && products?.length === 0 ? (
        <StateNotice title="暂无商品">当前业务数据库没有可展示的商品。</StateNotice>
      ) : null}

      {products?.length ? (
        <div className="product-shelf">
          {products.map((product, index) => (
            <article className="product-index-card" key={product.product_id}>
              <div className="product-card-visual" aria-hidden="true">
                <span>{productName(product.name, product.product_id).slice(0, 1)}</span>
                <small>{String(index + 1).padStart(2, '0')}</small>
              </div>
              <div className="product-card-copy">
                <h2>{productName(product.name, product.product_id)}</h2>
                <p className="product-code">#{product.product_id}</p>
                <p className="product-options">
                  {product.option_names.length
                    ? product.option_names.map(optionLabel).join(' / ')
                    : '单一规格'}
                </p>
              </div>
              <div className="product-stock">
                <strong>{priceRange(product)}</strong>
                <span>{product.available_variants} / {product.total_variants} 个规格可用</span>
                <button className="text-button" type="button" onClick={() => onSelect(product.product_id)}>
                  查看商品
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <ProductDetailDialog
        open={isDetailOpen}
        product={selectedProduct}
        isLoading={isDetailLoading}
        errorMessage={detailErrorMessage}
        onAddToCart={onAddToCart}
        onClose={onCloseDetail}
      />
    </section>
  )
}
