const SESSION_KEY = 'serviceflow.session_id'

export function readSessionId(): string | null {
  const value = window.localStorage.getItem(SESSION_KEY)
  return value?.trim() || null
}

export function saveSessionId(sessionId: string): void {
  window.localStorage.setItem(SESSION_KEY, sessionId)
}

export function clearSessionId(): void {
  window.localStorage.removeItem(SESSION_KEY)
}
