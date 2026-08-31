import re

from app.ai.provider import AIProvider
from app.models.incident import IncidentState
from app.models.knowledge import KnowledgeArticle
from app.models.resolution import (
    ResolutionAttempt, ResolutionFeedback, ResolutionOutcome,
    ResolutionState, ResolutionStep,
)


MAX_KNOWLEDGE_ATTEMPTS = 5

SHARED_NETWORK_EQUIPMENT = re.compile(
    r"\b(?:router\w*|ruter\w*|switch\w*|modem\w*|"
    r"przełącznik\w*\s+sieciow\w*|przelacznik\w*\s+sieciow\w*|"
    r"szaf\w*\s+(?:sieciow\w*|rack)|network\s+(?:cabinet|rack)|"
    r"punkt\w*\s+dost[eę]pow\w*|access\s+point)\b", re.IGNORECASE,
)


def normalize_instruction(text: str) -> str:
    return " ".join(text.split()).casefold()


def approved_source_lines(content: str) -> set[str]:
    return {
        normalize_instruction(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line))
        for line in content.splitlines() if line.strip()
    }


def start_resolution_step(
    resolution: ResolutionState, step: ResolutionStep,
) -> ResolutionState:
    return resolution.model_copy(update={
        "attempts": [*resolution.attempts, ResolutionAttempt(step=step)],
        "outcome": ResolutionOutcome.CONTINUE,
    })


def get_next_resolution_step(
    ai_provider: AIProvider,
    incident: IncidentState,
    knowledge: list[KnowledgeArticle],
    resolution: ResolutionState,
) -> tuple[ResolutionState, ResolutionStep | None]:
    trusted = [article for article in knowledge if article.active]
    kb_attempts = [
        attempt for attempt in resolution.attempts
        if not attempt.step.source_id.startswith("PLAYBOOK-")
    ]
    if not trusted or len(kb_attempts) >= MAX_KNOWLEDGE_ATTEMPTS:
        return resolution.model_copy(update={"knowledge_exhausted": True}), None

    proposal = ai_provider.generate_resolution_step(incident, trusted, resolution)
    step = proposal.step if proposal.applicable else None
    if step is not None:
        source = next((a for a in trusted if a.article_id == step.source_id), None)
        instruction = normalize_instruction(step.instruction)
        attempted = {
            normalize_instruction(attempt.step.instruction)
            for attempt in resolution.attempts
        }

        if (
            source is not None
            and not source.article_id.startswith("PLAYBOOK-")
            and instruction
            and instruction in approved_source_lines(source.content)
            and instruction not in attempted
            and not SHARED_NETWORK_EQUIPMENT.search(step.instruction)
        ):
            return start_resolution_step(resolution, step), step

    return resolution.model_copy(update={"knowledge_exhausted": True}), None


def apply_resolution_feedback(resolution: ResolutionState, feedback: ResolutionFeedback, message: str) -> ResolutionState:
    attempt = resolution.attempts[-1]
    if not feedback.understood:
        return resolution

    updates = {"user_response": message}
    if feedback.step_completed is not None:
        updates["step_completed"] = feedback.step_completed
    if feedback.problem_resolved is not None:
        updates["problem_resolved"] = feedback.problem_resolved

    resolved = feedback.problem_resolved is True and not feedback.clarification_requested
    return resolution.model_copy(update={
        "attempts": [*resolution.attempts[:-1], attempt.model_copy(update=updates)],
        "outcome": ResolutionOutcome.RESOLVED if resolved else ResolutionOutcome.CONTINUE,
    })
