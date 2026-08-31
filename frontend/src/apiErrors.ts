type ApiError = {
  status: number
  code: string | null
  requestId: string | null
}

const requestIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export async function readApiError(response: Response): Promise<ApiError> {
  let payload: Record<string, unknown>
  try {
    payload = await response.json()
  } catch {
    payload = {}
  }
  const requestId = typeof payload.request_id === 'string' && requestIdPattern.test(payload.request_id)
    ? payload.request_id
    : null
  let code = typeof payload.code === 'string' ? payload.code : null
  if (!code && payload.detail === 'Database service is temporarily unavailable.') code = 'DATABASE_UNAVAILABLE'
  if (!code && payload.detail === 'AI service is temporarily unavailable.') code = 'AI_UNAVAILABLE'
  return { status: response.status, code, requestId }
}

export function getSendErrorMessage(error: unknown): string {
  if (error instanceof TypeError) return 'Nie otrzymano odpowiedzi z ResolveDesk. Sprawdź połączenie i spróbuj ponownie.'
  const value = error as Partial<ApiError>
  const id = value.requestId ? ` Identyfikator błędu: ${value.requestId}` : ''
  if (value.code === 'AI_UNAVAILABLE') return `Usługa AI jest chwilowo niedostępna.${id}`
  if (value.code === 'AI_INVALID_RESPONSE') return `Model zwrócił nieprawidłową odpowiedź.${id}`
  if (value.code === 'DATABASE_UNAVAILABLE') return `Baza danych jest chwilowo niedostępna.${id}`
  if (typeof value.status === 'number') return `ResolveDesk zwrócił błąd HTTP ${value.status}.${id}`
  return 'Nie udało się wysłać wiadomości. Spróbuj ponownie.'
}
