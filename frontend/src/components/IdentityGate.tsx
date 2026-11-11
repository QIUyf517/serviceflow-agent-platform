import { useState, type FormEvent } from 'react'

import type { IdentityInput } from '../api/types'
import { StateNotice } from './StateNotice'

interface IdentityGateProps {
  isPending: boolean
  errorMessage?: string
  onVerify: (identity: IdentityInput) => void
}

export function IdentityGate({ isPending, errorMessage, onVerify }: IdentityGateProps) {
  const [method, setMethod] = useState<'email' | 'profile'>('email')
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [zipCode, setZipCode] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (method === 'email') {
      if (email.trim()) onVerify({ email: email.trim() })
      return
    }
    if (firstName.trim() && lastName.trim() && zipCode.trim()) {
      onVerify({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        zip_code: zipCode.trim(),
      })
    }
  }

  return (
    <section className="identity-gate" aria-labelledby="identity-title">
      <div className="identity-copy">
        <p className="status-kicker">先确认是你本人</p>
        <h1 id="identity-title">订单信息只对本人开放</h1>
        <p>使用模拟业务数据中的邮箱，或姓名与邮编完成核验。页面不会保存这些资料。</p>
      </div>
      <form className="identity-form" onSubmit={submit}>
        <div className="segmented" role="group" aria-label="核验方式">
          <button
            className={method === 'email' ? 'is-active' : ''}
            type="button"
            aria-pressed={method === 'email'}
            onClick={() => setMethod('email')}
          >
            邮箱
          </button>
          <button
            className={method === 'profile' ? 'is-active' : ''}
            type="button"
            aria-pressed={method === 'profile'}
            onClick={() => setMethod('profile')}
          >
            姓名与邮编
          </button>
        </div>
        {method === 'email' ? (
          <label>
            模拟账户邮箱
            <input
              autoComplete="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
        ) : (
          <div className="identity-fields">
            <label>
              名
              <input value={firstName} onChange={(event) => setFirstName(event.target.value)} required />
            </label>
            <label>
              姓
              <input value={lastName} onChange={(event) => setLastName(event.target.value)} required />
            </label>
            <label className="field-wide">
              邮编
              <input
                inputMode="numeric"
                value={zipCode}
                onChange={(event) => setZipCode(event.target.value)}
                required
              />
            </label>
          </div>
        )}
        {errorMessage ? <StateNotice kind="error" title="身份核验未通过">{errorMessage}</StateNotice> : null}
        <button className="button button-primary" type="submit" disabled={isPending}>
          {isPending ? '正在核验…' : '核验并查看订单'}
        </button>
      </form>
    </section>
  )
}
