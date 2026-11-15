const SESSION_KEY = 'serviceflow.session_id'
const SUPPORT_CONTEXT_KEY = 'serviceflow.support_context'
const GENERAL_CONTEXT = 'general'

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

/** The open support window is a UI hint only; the server still resolves the thread. */
export function readSupportContext(): string | null {
  const value = window.localStorage.getItem(SUPPORT_CONTEXT_KEY)?.trim()
  return value || null
}

export function saveSupportContext(orderId: string | null): void {
  window.localStorage.setItem(SUPPORT_CONTEXT_KEY, orderId ?? GENERAL_CONTEXT)
}

export function clearSupportContext(): void {
  window.localStorage.removeItem(SUPPORT_CONTEXT_KEY)
}
