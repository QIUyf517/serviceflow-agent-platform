import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <section className="state-page" aria-labelledby="not-found-title">
      <p className="state-code">404</p>
      <h1 id="not-found-title">没有这个页面</h1>
      <p>地址可能已变更。返回售后服务台继续处理。</p>
      <Link className="button button-primary" to="/support">
        返回服务台
      </Link>
    </section>
  )
}
