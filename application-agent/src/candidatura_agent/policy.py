"""Política explicável de aderência e envio."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Assessment:
    score: int
    eligible: bool
    reasons: list[str]
    blockers: list[str]


@dataclass(frozen=True)
class SubmissionDecision:
    action: str
    reason: str


def assess_job(job: dict, profile: dict, learned_weights: dict[str, int] | None = None) -> Assessment:
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    text = f"{title} {job.get('description') or ''}".lower()
    blockers: list[str] = []
    reasons: list[str] = []

    if any(term in title for term in profile.get("blocked_title_terms", [])):
        blockers.append("senioridade")
    if not any(term in location for term in profile.get("allowed_locations", [])):
        blockers.append("localização")
    if blockers:
        return Assessment(0, False, [], blockers)

    score = 0
    matched_titles = [term for term in profile.get("target_titles", []) if term in title]
    if matched_titles:
        score += 30
        reasons.append(f"cargo-alvo: {matched_titles[0]}")

    score += 15
    reasons.append("localização aceita")

    if any(term in title for term in ("senior", "sênior", "lead", "manager", "head", "staff", "principal")):
        score += 10
        reasons.append("nível sênior/liderança")

    skills = [skill for skill in profile.get("preferred_skills", []) if skill.lower() in text]
    skill_points = min(30, len(skills) * 6)
    score += skill_points
    if skills:
        reasons.append("stack: " + ", ".join(skills[:5]))

    heuristic = int(job.get("heuristic_score") or 0)
    score += min(15, heuristic * 3)

    # O scraper existente já produz um score conservador (1–5 estrelas,
    # persistido como 20–100). Preservar 80% dessa evidência evita descartar
    # vagas boas quando a API do LinkedIn entrega descrição vazia.
    upstream_score = int(job.get("source_score") or job.get("fit_score") or 0)
    if upstream_score:
        preserved = round(upstream_score * 0.8)
        if preserved > score:
            score = preserved
            reasons.append(f"pré-score do scraper: {upstream_score}/100")

    for term, weight in (learned_weights or {}).items():
        if term.lower() in text:
            delta = max(-15, min(15, int(weight)))
            score += delta
            reasons.append(f"feedback {term}: {delta:+d}")

    score = max(0, min(100, score))
    eligible = score >= int(profile.get("min_fit_score", 70))
    if not eligible:
        blockers.append("aderência")
    return Assessment(score, eligible, reasons, blockers)


def decide_submission(*, fit_score: int, min_fit_score: int, auto_submit: bool, ats: str, allowed_ats: set[str], blockers: list[str]) -> SubmissionDecision:
    if blockers:
        return SubmissionDecision("pause", "campos bloqueantes: " + ", ".join(blockers))
    if fit_score < min_fit_score:
        return SubmissionDecision("skip", "aderência insuficiente")
    if ats not in allowed_ats:
        return SubmissionDecision("pause", f"ATS não liberado: {ats}")
    if not auto_submit:
        return SubmissionDecision("review", "modo dry_run")
    return SubmissionDecision("submit", "todos os controles aprovados")
