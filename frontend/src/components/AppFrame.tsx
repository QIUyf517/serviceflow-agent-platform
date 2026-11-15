import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

export function AppFrame() {
  const { pathname } = useLocation()
  const isStorefront = pathname === '/store' || pathname === '/support'

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      {!isStorefront ? (
        <header className="site-header">
          <Link className="brand" to="/store" aria-label="ServiceFlow 模拟商店首页">
            <span className="brand-mark" aria-hidden="true">SF</span>
            <span>
              <strong>ServiceFlow</strong>
              <small>模拟商店与可信售后</small>
            </span>
          </Link>
          <nav className="primary-nav" aria-label="主要导航">
            <NavLink to="/store">模拟商店</NavLink>
            <NavLink to="/admin">管理后台</NavLink>
            <NavLink to="/developer">开发者追踪</NavLink>
          </nav>
          <p className="trust-note">关键操作由服务端校验并留痕</p>
        </header>
      ) : null}
      <main id="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
