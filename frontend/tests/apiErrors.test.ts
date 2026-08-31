import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getSendErrorMessage, readApiError } from '../src/apiErrors.ts'

test('AI timeout keeps its diagnostic ID without displaying raw server detail', async () => {
  const id = '12345678-1234-1234-1234-123456789abc'
  const error = await readApiError(Response.json({ code: 'AI_UNAVAILABLE', request_id: id, detail: 'private diagnostic text' }, { status: 503 }))
  const message = getSendErrorMessage(error)
  assert.match(message, /Usługa AI jest chwilowo niedostępna/)
  assert.ok(message.includes(id))
  assert.ok(!message.includes('private diagnostic text'))
})

test('legacy API detail is mapped, but arbitrary text and malformed IDs are withheld', async () => {
  const legacy = await readApiError(Response.json({ detail: 'Database service is temporarily unavailable.' }, { status: 503 }))
  assert.match(getSendErrorMessage(legacy), /Baza danych/)
  const unknown = await readApiError(Response.json({ detail: 'private data', request_id: 'private data' }, { status: 500 }))
  assert.equal(unknown.requestId, null)
  assert.ok(!getSendErrorMessage(unknown).includes('private data'))
})

test('HTML proxy errors and network failures produce readable fallback messages', async () => {
  const error = await readApiError(new Response('<h1>Bad Gateway</h1>', { status: 502 }))
  assert.match(getSendErrorMessage(error), /HTTP 502/)
  assert.match(getSendErrorMessage(new TypeError('Failed to fetch')), /Nie otrzymano odpowiedzi/)
})
