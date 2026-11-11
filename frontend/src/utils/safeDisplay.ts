const SENSITIVE_KEYS = new Set([
  'address',
  'billing_address',
  'card',
  'card_number',
  'cvc',
  'cvv',
  'email',
  'api_key',
  'name',
  'payment_credential',
  'phone',
  'prompt',
  'reference_action',
  'reference_actions',
  'scoring_condition',
  'scoring_conditions',
  'expected_action',
  'security_code',
  'shipping_address',
  'system_prompt',
  'zip',
  'zip_code',
])

export function redactDisplayText(value: string): string {
  return value
    .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, '[REDACTED_EMAIL]')
    .replace(/\b(?:sk|key|token)-[A-Za-z0-9_-]{8,}\b/gi, '[REDACTED_SECRET]')
    .replace(/\b(?:\d[ -]*?){13,19}\b/g, '[REDACTED_PAYMENT]')
    .replace(/(收货地址|账单地址|地址|住址)\s*[：:=]\s*[^；;\n]+/g, '$1：[REDACTED_ADDRESS]')
    .replace(
      /\b(address|shipping_address|billing_address)\s*[:=]\s*.*?(?=\s+(?:card_number|cvv|cvc|security_code)\s*[:=]|[;\n]|$)/gi,
      '$1=[REDACTED_ADDRESS]',
    )
}

export function sanitizeForDisplay(value: unknown): unknown {
  if (Array.isArray(value)) return value.slice(0, 50).map(sanitizeForDisplay)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        SENSITIVE_KEYS.has(key.toLowerCase()) ? '[REDACTED]' : sanitizeForDisplay(item),
      ]),
    )
  }
  if (typeof value === 'string') return redactDisplayText(value).slice(0, 2_000)
  return value
}

export function safeJson(value: unknown): string {
  return JSON.stringify(sanitizeForDisplay(value), null, 2)
}
