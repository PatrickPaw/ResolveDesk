import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type Props = {
  apiUrl: string
  conversationId: string
  onFinish: () => void
}

type Challenge = {
  challenge_id: string
  demo_code: string
  expires_in_seconds: number
  retry_after_seconds: number
}

export function PasswordResetDemo({ apiUrl, conversationId, onFinish }: Props) {
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [verified, setVerified] = useState(false)
  const [expiresAt, setExpiresAt] = useState(0)
  const [retryAt, setRetryAt] = useState(0)
  const [now, setNow] = useState(Date.now)

  useEffect(() => {
    if (!challenge || verified) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [challenge, verified])

  async function requestCode() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${apiUrl}/demo/password-reset/request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: conversationId }),
      })
      if (!response.ok) {
        setError(response.status === 429
          ? 'Poczekaj minutę przed kolejnym wysłaniem kodu demo.'
          : 'Nie udało się wysłać kodu demo. Spróbuj ponownie lub rozpocznij nową rozmowę.')
        return
      }
      const data: Challenge = await response.json()
      const receivedAt = Date.now()
      setChallenge(data)
      setCode('')
      setNow(receivedAt)
      setExpiresAt(receivedAt + data.expires_in_seconds * 1000)
      setRetryAt(receivedAt + data.retry_after_seconds * 1000)
    } catch {
      setError('Nie udało się połączyć. Kod mógł zostać wygenerowany — odczekaj minutę przed ponowną próbą.')
    } finally {
      setBusy(false)
    }
  }

  async function verifyCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!challenge || busy || verified) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${apiUrl}/demo/password-reset/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: conversationId, challenge_id: challenge.challenge_id, code }),
      })
      if (!response.ok) {
        const errors: Record<number, string> = {
          400: 'Nieprawidłowy kod demo. Sprawdź kod w symulowanej skrzynce.',
          429: 'Wyczerpano limit prób. Wyślij nowy kod demo po upływie minuty.',
          410: 'Kod wygasł, został wykorzystany lub zastąpiony. Wyślij nowy kod demo.',
        }
        setError(errors[response.status] ?? 'Pokaz jest niedostępny. Rozpocznij nową rozmowę.')
        return
      }
      setVerified(true)
      setCode('')
      setChallenge(null)
    } catch {
      setError('Nie udało się odczytać wyniku. Kod mógł zostać zużyty — w razie potrzeby wygeneruj nowy.')
    } finally {
      setBusy(false)
    }
  }

  const secondsLeft = Math.max(0, Math.ceil((expiresAt - now) / 1000))
  const retrySeconds = Math.max(0, Math.ceil((retryAt - now) / 1000))

  return (
    <section className="password-demo" aria-label="Demonstracja odzyskiwania hasła">
      <strong>DEMO · Odzyskiwanie hasła</strong>
      <p>Symulacja bez prawdziwego maila i bez zmiany hasła firmowego. Nie wpisuj tutaj prawdziwych haseł ani kodów.</p>
      {verified ? (
        <>
          <p role="status">Kod demo potwierdzony i wykorzystany. Pokaz zakończony — żadne hasło firmowe nie zostało zmienione.</p>
          <button type="button" onClick={onFinish}>Zakończ pokaz i otwórz nową rozmowę</button>
        </>
      ) : (
        <>
          <button type="button" onClick={requestCode} disabled={busy || retrySeconds > 0}>
            {challenge ? 'Wyślij nowy kod demo' : 'Wyślij kod do skrzynki demo'}
            {retrySeconds > 0 ? ` (za ${retrySeconds} s)` : ''}
          </button>
          {challenge && (
            <>
              <div className="demo-mailbox" role="status">
                <strong>Symulowana skrzynka odbiorcza</strong>
                <p>Kod prezentacyjny: <output className="demo-code">{challenge.demo_code}</output></p>
                <small>{secondsLeft > 0 ? `Ważny jeszcze ${secondsLeft} s. Maksymalnie 5 prób.` : 'Kod wygasł. Wyślij nowy kod demo.'}</small>
              </div>
              <form className="demo-code-form" onSubmit={verifyCode}>
                <label htmlFor="demo-code">Jednorazowy kod z tej skrzynki demo</label>
                <input id="demo-code" inputMode="numeric" autoComplete="off" pattern="[0-9]{6}" maxLength={6}
                  value={code} onChange={(event) => setCode(event.target.value.replace(/[^0-9]/g, ''))}
                  disabled={busy || secondsLeft === 0} required />
                <button type="submit" disabled={busy || code.length !== 6 || secondsLeft === 0}>Potwierdź kod demo</button>
              </form>
            </>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  )
}
