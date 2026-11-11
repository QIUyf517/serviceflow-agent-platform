import { Link, NavLink, Outlet } from 'react-router-dom'

export function AppFrame() {
  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <header className="site-header">
        <Link className="brand" to="/support" aria-label="ServiceFlow 售后服务台首页">
          <span className="brand-mark" aria-hidden="true">SF</span>
          <span>
            <strong>ServiceFlow</strong>
            <small>可信售后服务台</small>
          </span>
        </Link>
        <nav className="primary-nav" aria-label="主要导航">
          <NavLink to="/support">用户服务台</NavLink>
          <NavLink to="/admin">管理后台</NavLink>
          <NavLink to="/developer">开发者追踪</NavLink>
        </nav>
        <p className="trust-note">关键操作由服务端校验并留痕</p>
      </header>
      <main id="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  )
}
