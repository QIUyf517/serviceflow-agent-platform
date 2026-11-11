export function newIdempotencyKey(scope: string): string {
  const token = crypto.randomUUID().replaceAll('-', '')
  return `${scope}-${token}`
}
