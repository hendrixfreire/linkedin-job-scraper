"""Detecção de ATS e classificação conservadora de campos."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class FieldRule:
    key: str | None
    blocked: bool
    reason: str = ""


def detect_ats(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if "myworkdayjobs.com" in host or "workday.com" in host:
        return "workday"
    if "gupy.io" in host:
        return "gupy"
    if "peopleforce.io" in host or "peopleforce.com" in host:
        return "peopleforce"
    if "factorialhr.com" in host or "factorialhr.com.br" in host:
        return "factorial"
    return "generic"


KNOWN_FIELDS = {
    "full name": "full_name", "nome completo": "full_name",
    "first name": "first_name", "last name": "last_name",
    "email": "email", "e-mail": "email", "phone": "phone", "telefone": "phone",
    "linkedin": "linkedin", "location": "location", "localização": "location",
    "resume": "resume", "currículo": "resume", "cv": "resume",
}
APPROVED_QUESTION_FIELDS = {
    "country phone code": "phone_country_code",
    "english proficiency level": "english_proficiency",
    "currently employed": "current_employer",
    "current base salary": "current_base_salary_answer",
    "expected base salary": "expected_base_salary_answer",
    "citizen or permanent resident": "citizen_answer",
    "how did you hear about this opportunity": "application_source",
    "i have nothing to declare": "conflict_nothing_to_declare",
    "if you checked any of the options above": "conflict_details",
    "country": "country",
}
BLOCKED_TERMS = (
    "salary", "salário", "pretensão", "compensation", "disability", "deficiência",
    "race", "raça", "ethnicity", "etnia", "gender", "gênero", "veteran",
    "criminal", "antecedentes", "conflict of interest", "conflito de interesse",
    "visa", "sponsorship", "patrocínio", "work authorization", "autorização para trabalhar",
)


def classify_field(label: str) -> FieldRule:
    normalized = " ".join(label.lower().split())
    for term, key in APPROVED_QUESTION_FIELDS.items():
        if term in normalized:
            return FieldRule(key, False)
    if any(term in normalized for term in BLOCKED_TERMS):
        return FieldRule(None, True, "campo sensível ou legal")
    for term, key in KNOWN_FIELDS.items():
        if term in normalized:
            return FieldRule(key, False)
    return FieldRule(None, True, "pergunta desconhecida")
