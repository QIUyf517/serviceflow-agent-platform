import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { App } from '../app/App'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestOf(input: URL | RequestInfo, init?: RequestInit): Request {
  if (input instanceof Request) return new Request(input, init)
  const raw = input instanceof URL ? input.href : input
  return new Request(new URL(raw, window.location.origin), init)
}

function renderDeveloper(sessionId = 'session-owner') {
  window.localStorage.setItem('serviceflow.session_id', sessionId)
  window.history.replaceState({}, '', '/developer')
  return render(<App />)
}

describe('DeveloperPage', () => {
  it('reads current task and a redacted persisted trace with empty token usage', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const request = requestOf(input, init)
      expect(request.headers.get('X-Session-Id')).toBe('session-owner')
      if (request.url.endsWith('/api/v1/multi-agent/tasks/current')) {
        return Promise.resolve(json({
          thread_id: 'session-owner',
          task_status: 'pending_confirmation',
          current_task: 'task-2',
          task_plan: [{
            task_id: 'task-2', intent: 'cancel_order', target_agent: 'resolution', required_inputs: ['order_id'], dependencies: ['task-1'], status: 'ready',
          }],
          order_context: { order_id: '#W100', status: 'pending' },
          policy_context: [],
          resolution_proposal: null,
          eligibility_result: null,
          pending_confirmation: null,
          execution_result: null,
          trace: [{ node: 'triage_agent', status: 'completed', elapsed_ms: 4 }],
          final_response: '',
        }))
      }
      if (request.url.endsWith('/api/v1/traces/trace-1')) {
        return Promise.resolve(json({
          trace_id: 'trace-1',
          events: [{
            node: 'policy_agent',
            status: 'completed',
            elapsed_ms: 7,
            email: 'customer@example.invalid',
            prompt: 'full secret prompt',
            reference_action: 'expected hidden action',
          }],
          elapsed_ms: 14,
          token_usage: null,
        }))
      }
      throw new Error(`Unhandled request ${request.url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDeveloper()

    await user.click(screen.getByRole('button', { name: '读取当前任务' }))
    expect(await screen.findByText('task-2')).toBeInTheDocument()
    expect(screen.getByText(/依赖：task-1/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('trace_id'), 'trace-1')
    await user.click(screen.getByRole('button', { name: '读取 trace' }))
    expect(await screen.findByText('trace-1')).toBeInTheDocument()
    expect(screen.getByText('未提供（null）')).toBeInTheDocument()
    expect(screen.queryByText('customer@example.invalid')).not.toBeInTheDocument()
    expect(screen.queryByText('full secret prompt')).not.toBeInTheDocument()
    expect(screen.queryByText('expected hidden action')).not.toBeInTheDocument()
    expect(screen.getAllByText(/\[REDACTED/).length).toBeGreaterThan(0)
  })

  it.each([
    ['不存在的 trace', 'session-owner'],
    ['跨 session trace', 'session-other'],
  ])('safely rejects %s', async (_label, sessionId) => {
    const user = userEvent.setup()
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const request = requestOf(input, init)
      expect(request.headers.get('X-Session-Id')).toBe(sessionId)
      return Promise.resolve(json({ error: { code: 'trace_not_found' } }, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDeveloper(sessionId)

    await user.type(screen.getByLabelText('trace_id'), 'trace-private')
    await user.click(screen.getByRole('button', { name: '读取 trace' }))

    expect(await screen.findByText(/trace 不存在，或不属于当前 session/)).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  })
})
