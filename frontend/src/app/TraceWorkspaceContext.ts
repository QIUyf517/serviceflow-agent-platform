import { createContext, useContext } from 'react'

import type { ConversationResponse } from '../api/types'

export interface TraceWorkspaceValue {
  latest: ConversationResponse | null
  capturedAt: number | null
  record: (response: ConversationResponse) => void
  clear: () => void
}

export const TraceWorkspaceContext = createContext<TraceWorkspaceValue | null>(null)

export function useTraceWorkspace(): TraceWorkspaceValue {
  const value = useContext(TraceWorkspaceContext)
  if (!value) throw new Error('TraceWorkspaceProvider is required')
  return value
}
