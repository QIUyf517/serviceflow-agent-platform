import { useState, type FormEvent } from 'react'

import { StateNotice } from '../StateNotice'

interface OperatorGateProps {
  errorMessage?: string
  onUnlock: (token: string) => void
}

export function OperatorGate({ errorMessage, onUnlock }: OperatorGateProps) {
  const [token, setToken] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token.trim()) onUnlock(token)
  }

  return (
    <section className="operator-gate" aria-labelledby="operator-gate-title">
      <div>
        <p className="status-kicker">操作员边界</p>
        <h1 id="operator-gate-title">进入人工处理台</h1>
        <p>
          当前认证仅用于本地演示，不是生产 IAM。操作员 token 与客户 session 完全独立，
          不会获得代客户确认的能力。
        </p>
      </div>
      <form className="operator-token-form" onSubmit={submit}>
        <label>
          X-Operator-Token
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            required
          />
        </label>
        <p>token 仅保存在当前标签会话的 sessionStorage，不进入 URL、源码或构建变量。</p>
        {errorMessage ? <StateNotice kind="error" title="操作员认证失败">{errorMessage}</StateNotice> : null}
        <button className="button button-primary" type="submit" disabled={!token.trim()}>
          验证并打开工单
        </button>
      </form>
    </section>
  )
}
