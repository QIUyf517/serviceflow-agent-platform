import type { PersistedTrace } from './developerTypes'
import { apiClient } from './client'
import type { TaskProgress } from './types'

const API = '/api/v1'

function customerRead<T>(sessionId: string, path: string): Promise<T> {
  return apiClient.request<T>(path, {
    requiresSession: false,
    headers: { 'X-Session-Id': sessionId },
  })
}

export const developerApi = {
  currentTask: (sessionId: string) =>
    customerRead<TaskProgress>(sessionId, `${API}/multi-agent/tasks/current`),

  trace: (sessionId: string, traceId: string) =>
    customerRead<PersistedTrace>(sessionId, `${API}/traces/${encodeURIComponent(traceId)}`),
}
