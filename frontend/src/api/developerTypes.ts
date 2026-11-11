import type { TraceEvent } from './types'

export interface PersistedTrace {
  trace_id: string
  events: TraceEvent[]
  elapsed_ms: number
  token_usage: Record<string, number> | null
}
