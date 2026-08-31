type FactTrace = {
  key: string
  value: unknown
  source: 'AI' | 'LITERAL' | 'PYTHON'
  evidence: string | null
  evidence_valid: boolean
}

type ValidationTrace = {
  check: string
  passed: boolean
  detail: string
}

type DecisionTrace = {
  decision_type: string
  source: 'PYTHON_RULE' | 'RAG' | 'SECURITY_RULE'
  reason: string
  question_id: string | null
  action_source_id: string | null
}

type KnowledgeTrace = {
  article_id: string
  title: string
  retrieval_method: 'VECTOR' | 'CATEGORY'
  similarity: number | null
  selected: boolean
}

export type ExplainabilityTrace = {
  mode: 'DEMO_ADMIN_ONLY'
  input_text: string
  input_redacted: boolean
  interpretation_source: 'AI' | 'LITERAL' | 'SECURITY_RULE' | null
  intent: string | null
  incident_patch: Record<string, unknown>
  extracted_facts: FactTrace[]
  validations: ValidationTrace[]
  playbook_id: string | null
  playbook_version: string | null
  decisions: DecisionTrace[]
  knowledge_candidates: KnowledgeTrace[]
  escalation_reason: string | null
}

function formatValue(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export function ExplainabilityPanel({ trace }: { trace: ExplainabilityTrace }) {
  return (
    <details className="explainability">
      <summary>Jak powstała ta decyzja? · tryb demonstracyjny</summary>
      <div className="explainability-content">
        <p><strong>Wiadomość:</strong> {trace.input_text}</p>
        <p><strong>Interpretacja:</strong> {trace.interpretation_source ?? 'brak'} · {trace.intent ?? 'brak intencji'}</p>
        <p><strong>Playbook:</strong> {trace.playbook_id ? trace.playbook_id + ' v' + (trace.playbook_version ?? '?') : 'nie wybrano'}</p>

        {trace.extracted_facts.length > 0 && (
          <section>
            <strong>Fakty i dowody</strong>
            <ul>
              {trace.extracted_facts.map((fact, index) => (
                <li key={fact.key + '-' + index}>
                  <code>{fact.key}</code> = {formatValue(fact.value)} ({fact.source})
                  {fact.evidence && (
                    <span> · cytat: „{fact.evidence}” {fact.evidence_valid ? '✓' : '✗'}</span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {trace.validations.length > 0 && (
          <section>
            <strong>Walidacja</strong>
            <ul>
              {trace.validations.map((item) => (
                <li key={item.check}>{item.passed ? '✓' : '✗'} {item.check}: {item.detail}</li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <strong>Decyzje</strong>
          <ol>
            {trace.decisions.map((decision, index) => (
              <li key={decision.decision_type + '-' + index}>
                <code>{decision.source}</code> → {decision.decision_type}: {decision.reason}
                {decision.action_source_id && <span> · źródło: {decision.action_source_id}</span>}
              </li>
            ))}
          </ol>
        </section>

        {trace.knowledge_candidates.length > 0 && (
          <section>
            <strong>Wyniki Knowledge Base</strong>
            <ul>
              {trace.knowledge_candidates.map((item) => (
                <li key={item.article_id}>
                  {item.selected ? '✓ ' : ''}{item.article_id} — {item.title}
                  {' · '}{item.retrieval_method}
                  {item.similarity !== null ? ' · podobieństwo ' + item.similarity.toFixed(3) : ''}
                </li>
              ))}
            </ul>
          </section>
        )}

        {trace.escalation_reason && <p><strong>Powód eskalacji:</strong> {trace.escalation_reason}</p>}
        <small>Ślad nie zawiera promptów systemowych, pełnej odpowiedzi modelu ani sekretów.</small>
      </div>
    </details>
  )
}
