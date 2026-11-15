import { useMemo, useState, type ReactNode } from 'react'

import type { ConversationResponse } from '../api/types'
import { TraceWorkspaceContext, type TraceWorkspaceValue } from './TraceWorkspaceContext'

export function TraceWorkspaceProvider({ children }: { children: ReactNode }) {
  const [latest, setLatest] = useState<ConversationResponse | null>(null)
  const [capturedAt, setCapturedAt] = useState<number | null>(null)
  const value = useMemo<TraceWorkspaceValue>(() => ({
    latest,
    capturedAt,
    record: (response) => {
      setLatest(response)
      setCapturedAt(Date.now())
    },
    clear: () => {
      setLatest(null)
      setCapturedAt(null)
    },
  }), [latest, capturedAt])

  return <TraceWorkspaceContext.Provider value={value}>{children}</TraceWorkspaceContext.Provider>
}
