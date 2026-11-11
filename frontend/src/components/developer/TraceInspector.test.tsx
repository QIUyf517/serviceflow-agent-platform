import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ConversationResponse } from '../../api/types'
import { TraceInspector } from './TraceInspector'

const LATEST: ConversationResponse = {
  trace_id: 'trace-latest',
  task_status: 'failed',
  request_id: 'request-1',
  pending_confirmation: null,
  resolution_proposal: null,
  eligibility_result: null,
  execution_result: null,
  failure_reason: 'tool_failed',
  task_plan: [{
    task_id: 'task-2', intent: 'cancel_order', target_agent: 'execution', required_inputs: [], dependencies: ['task-1'], status: 'failed',
  }],
  ticket: { id: 'ticket-1', ticket_no: 'TK-1', status: 'open' },
  trace: [{ node: 'execution_agent', status: 'error', code: 'order_changed', elapsed_ms: 12 }],
  tool_results: [{ tool: 'cancel_order', status: 'error', code: 'order_changed', elapsed_ms: 8 }],
  metrics: {
    elapsed_ms: 25,
    node_count: 1,
    tool_calls: 1,
    nodes: ['execution_agent'],
    node_timings_ms: [{ node: 'execution_agent', elapsed_ms: 12, result: 'error', error_code: 'order_changed' }],
    provider: 'mock_local',
    model: 'deterministic-v1',
    token_usage: null,
  },
  final_response: '执行失败',
}

describe('TraceInspector', () => {
  it('shows failed nodes, tools, dependencies, and truthfully labels the mock provider', () => {
    render(<TraceInspector latest={LATEST} persisted={null} task={null} />)

    expect(screen.getByRole('heading', { name: '失败 trace' })).toBeInTheDocument()
    expect(screen.getByText('task-1', { exact: false })).toBeInTheDocument()
    expect(screen.getAllByText('execution_agent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('cancel_order').length).toBeGreaterThan(0)
    expect(screen.getAllByText('mock_local').length).toBeGreaterThan(0)
    expect(screen.getByText(/不是 DeepSeek/)).toBeInTheDocument()
    expect(screen.getByText('未提供（null）')).toBeInTheDocument()
  })
})
