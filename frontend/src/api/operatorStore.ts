const OPERATOR_TOKEN_KEY = 'serviceflow.operator_token'

export function readOperatorToken(): string | null {
  const value = window.sessionStorage.getItem(OPERATOR_TOKEN_KEY)
  return value?.trim() || null
}

export function saveOperatorToken(token: string): void {
  const normalized = token.trim()
  if (!normalized) throw new Error('operator_token_required')
  window.sessionStorage.setItem(OPERATOR_TOKEN_KEY, normalized)
}

export function clearOperatorToken(): void {
  window.sessionStorage.removeItem(OPERATOR_TOKEN_KEY)
}
