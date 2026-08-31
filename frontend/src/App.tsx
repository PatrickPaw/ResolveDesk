import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { getSendErrorMessage, readApiError } from './apiErrors'
import { PasswordResetDemo } from './PasswordResetDemo'
import { ExplainabilityPanel } from './ExplainabilityPanel'
import type { ExplainabilityTrace } from './ExplainabilityPanel'
import './App.css'

type ConversationStage =
  | 'ACTIVE'
  | 'RESOLUTION'
  | 'RESOLVED'
  | 'ESCALATED'

type ChatResponse = {
  conversation_id: string
  stage: ConversationStage
  incident: Record<string, unknown>
  reply: string
  ticket_id: string | null
  password_reset_demo_available?: boolean
  explainability?: ExplainabilityTrace | null
}

type Message = {
  id: number
  role: 'assistant' | 'user'
  content: string
  explainability?: ExplainabilityTrace | null
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'
const CONVERSATION_KEY = 'resolvedesk.conversation_id'

const initialMessage: Message = {
  id: 0,
  role: 'assistant',
  content:
    'Dzień dobry.\nOpisz problem, z którym się spotkałeś. Zadam tylko pytania potrzebne do diagnozy i spróbuję pomóc Ci go rozwiązać.',
}

function App() {
  const [messages, setMessages] = useState<Message[]>([initialMessage])
  const [message, setMessage] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [stage, setStage] = useState<ConversationStage | null>(null)
  const [ticketId, setTicketId] = useState<string | null>(null)
  const [passwordDemoAvailable, setPasswordDemoAvailable] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const busy = loading

  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const conversationClosed =
    stage === 'RESOLVED' || stage === 'ESCALATED'

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: 'smooth',
    })
  }, [messages, loading])

  useEffect(() => {
    try {
      sessionStorage.removeItem(CONVERSATION_KEY)
    } catch {
      // A fresh in-memory conversation does not depend on browser storage.
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const trimmedMessage = message.trim()

    if (!trimmedMessage || busy || conversationClosed) {
      return
    }

    const userMessage: Message = {
      id: Date.now(),
      role: 'user',
      content: trimmedMessage,
    }

    setMessages((current) => [...current, userMessage])
    setMessage('')
    setSendError(null)
    setLoading(true)

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: trimmedMessage,
          conversation_id: conversationId,
          include_explainability: true,
        }),
      })

      if (!response.ok) {
        throw await readApiError(response)
      }

      const data: ChatResponse = await response.json()

      setConversationId(data.conversation_id)
      setStage(data.stage)
      setTicketId(data.ticket_id)
      setPasswordDemoAvailable(Boolean(data.password_reset_demo_available))

      const assistantMessage: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: data.ticket_id
          ? `${data.reply}\n\nNumer zgłoszenia: ${data.ticket_id}`
          : data.reply,
        explainability: data.explainability,
      }

      setMessages((current) => [...current, assistantMessage])
    } catch (error) {
      setMessages((current) => current.filter((item) => item.id !== userMessage.id))
      setMessage(trimmedMessage)
      setSendError(getSendErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  function handleCloseConversation() {
    setConversationId(null)
    setMessages([initialMessage])
    setMessage('')
    setSendError(null)
    setStage(null)
    setTicketId(null)
    setPasswordDemoAvailable(false)
  }

  function getStatusText() {
    if (loading) {
      return 'Analizuję zgłoszenie...'
    }

    if (stage === 'RESOLVED') {
      return 'Problem rozwiązany'
    }

    if (stage === 'ESCALATED') {
      return 'Zgłoszenie przekazane do IT'
    }

    if (stage === 'RESOLUTION') {
      return 'Rozwiązywanie problemu'
    }

    if (stage === 'ACTIVE') {
      return 'Diagnoza i zbieranie informacji'
    }

    return 'Gotowy do przyjęcia zgłoszenia'
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-logo">
            <img src="/favicon.png" alt="Pomoc IT" />
          </div>

          <div className="brand-text">
            <span className="brand-name">Pomoc IT<br /></span>
            <span className="brand-subtitle">Wsparcie techniczne</span>
          </div>
        </div>

      </header>

      <main className="page">
        <section className="chat">
          <header className="chat-header">
            <div className="assistant-avatar">
              <span>AI</span>
            </div>

            <div className="assistant-info">
              <strong>Asystent IT</strong>

              <div className="assistant-status">
                <span className="status-dot" />
                <span>{getStatusText()}</span>
              </div>
            </div>
          </header>

          <div className="chat-messages">
            {messages.map((chatMessage) => (
              <div
                key={chatMessage.id}
                className={`message-row ${
                  chatMessage.role === 'user'
                    ? 'user-message-row'
                    : 'assistant-message-row'
                }`}
              >
                <div
                  className={`message ${
                    chatMessage.role === 'user'
                      ? 'user-message'
                      : 'assistant-message'
                  }`}
                >
                  <p>{chatMessage.content}</p>
                  {chatMessage.explainability && (
                    <ExplainabilityPanel trace={chatMessage.explainability} />
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="message-row assistant-message-row">
                <div className="message assistant-message loading-message">
                  <span className="loading-dot" />
                  <span className="loading-dot" />
                  <span className="loading-dot" />
                </div>
              </div>
            )}

            {passwordDemoAvailable && conversationId && !conversationClosed && (
              <PasswordResetDemo key={conversationId} apiUrl={API_URL} conversationId={conversationId} onFinish={handleCloseConversation} />
            )}
            <div ref={messagesEndRef} />
          </div>

          <footer className="chat-footer">
            {sendError && (
              <div className="send-error" role="alert">
                <p>{sendError}</p>
                <button type="button" disabled={busy} onClick={handleCloseConversation}>Nowa rozmowa</button>
              </div>
            )}
            {conversationClosed ? (
              <div className="closed-conversation">
                <div className="closed-status">
                  {stage === 'RESOLVED'
                    ? 'Problem został rozwiązany.'
                    : 'Zgłoszenie zostało przekazane do IT.'}

                  {ticketId && (
                    <span> Numer zgłoszenia: {ticketId}</span>
                  )}
                </div>

                <button
                  className="close-conversation-button"
                  type="button"
                  onClick={handleCloseConversation}
                >
                  Zamknij rozmowę
                </button>
              </div>
            ) : (
              <>
                <form
                  className="message-input-wrapper"
                  onSubmit={handleSubmit}
                >
                  <textarea
                    className="message-input"
                    placeholder="Opisz swój problem..."
                    rows={1}
                    maxLength={10000}
                    value={message}
                    disabled={busy}
                    onChange={(event) => setMessage(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === 'Enter' &&
                        !event.shiftKey
                      ) {
                        event.preventDefault()
                        event.currentTarget.form?.requestSubmit()
                      }
                    }}
                  />

                  <button
                    className="send-button"
                    type="submit"
                    aria-label="Wyślij wiadomość"
                    disabled={busy || !message.trim()}
                  >
                    ➜
                  </button>
                </form>

                <p className="security-message">
                  Nie podawaj haseł, kodów jednorazowych ani innych
                  danych poufnych. ResolveDesk może popełniać błędy.
                </p>
              </>
            )}
          </footer>
        </section>
      </main>
    </div>
  )
}

export default App
