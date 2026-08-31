import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from app.models.playbook import CatalogPolicy, Playbook, PlaybookAction


CATALOG_ROOT = Path(__file__).resolve().parents[1] / "catalog"


def load_catalog(root: Path) -> tuple[Playbook, ...]:
    bundle = json.loads((root / "playbooks.json").read_text(encoding="utf-8"))
    if bundle["schema_version"] != 1:
        raise ValueError("Unsupported catalog schema")
    action_data = json.loads((root / "actions.json").read_text(encoding="utf-8"))
    actions = {key: PlaybookAction.model_validate(value) for key, value in action_data.items()}
    if any(key != value.action_id for key, value in actions.items()):
        raise ValueError("Action ID does not match its catalog key")
    result = []
    ids = set()
    for source in bundle["playbooks"]:
        data = dict(source)
        for rule in data["rules"]:
            rule["actions"] = [actions[key] for key in rule.get("actions", [])]
        playbook = Playbook.model_validate(data)
        if playbook.playbook_id in ids:
            raise ValueError("Duplicate playbook ID")
        ids.add(playbook.playbook_id)
        result.append(playbook)
    return tuple(result)


@lru_cache
def get_catalog() -> tuple[Playbook, ...]:
    return load_catalog(CATALOG_ROOT)


@lru_cache
def get_policy() -> CatalogPolicy:
    policy = CatalogPolicy.model_validate_json((CATALOG_ROOT / "policy.json").read_text(encoding="utf-8"))
    available = {p.playbook_id for p in get_catalog()}
    references = set(policy.family_playbooks.values())
    ids = set()
    for profile in policy.profiles:
        if profile.profile_id in ids:
            raise ValueError("Duplicate service profile")
        ids.add(profile.profile_id)
        references.add(profile.playbook_id)
        references.update(profile.family_overrides.values())
    if references - available:
        raise ValueError("Unknown profile/family playbook")
    return policy


def normalized_subject(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold().replace("ł", "l"))
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def select_profile(incident):
    policy = get_policy()
    explicit = next((p for p in policy.profiles if p.profile_id == incident.service_profile), None)
    if explicit:
        return explicit
    subject = normalized_subject(" ".join(filter(None, (incident.subcategory, incident.summary))))
    for profile in policy.profiles:
        if any(re.search(r"(?<!\w)" + re.escape(normalized_subject(alias)) + r"(?!\w)", subject) for alias in profile.aliases):
            return profile
    return None
