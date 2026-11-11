export interface ApiErrorPayload {
  error?: { code?: string }
  detail?: string | Array<{ msg?: string }>
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly details?: unknown,
  ) {
    super(code)
    this.name = 'ApiError'
  }
}

export async function parseApiError(response: Response): Promise<ApiError> {
  let payload: ApiErrorPayload | undefined

  try {
    payload = (await response.json()) as ApiErrorPayload
  } catch {
    return new ApiError(response.status, `http_${response.status}`)
  }

  const code =
    payload.error?.code ??
    (typeof payload.detail === 'string' ? payload.detail : undefined) ??
    `http_${response.status}`

  return new ApiError(response.status, code, payload.detail)
}
