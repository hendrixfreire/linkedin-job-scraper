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
    "what is your availability to start": "availability_to_start",
    "expected monthly gross wage in euros": "expected_monthly_gross_eur",
    "how many years of relevant experience": "years_relevant_experience",
    "located within a ±4 hour range from the central european time": "within_cet_range",
    "qual sua pretensão salarial pj": "pj_salary_expectation",
    "qual a sua disponibilidade (em dias)": "start_availability_days",
    "atualmente você está atuando em algum projeto": "current_project_contract_type",
    "qual seu nível de inglês": "english_proficiency",
    "possui certificações": "certifications",
    "país": "greenhouse_phone_country",
    "localização (cidade)": "greenhouse_location",
    "qual é a sua pretensão salarial": "greenhouse_salary_expectation",
    "country": "country",
    "nome first_name": "first_name",
    "nome * first_name": "first_name",
    "sobrenome last_name": "last_name",
    "sobrenome * last_name": "last_name",
    "url pessoal": "linkedin",
    "name type here": "full_name",
    "empresa atual / última empresa": "last_employer",
    "cargo atual / último cargo": "last_job_title",
    "quais são os seus pronomes": "pronouns",
    "onde você descobriu a vaga": "application_source",
    "você já trabalhou no ifood": "worked_at_ifood",
    "qual seu nível de proficiência em inglês": "greenhouse_english_proficiency",
    "com qual gênero você se identifica": "gender_identity",
    "qual é sua cor ou raça": "race_ethnicity",
    "se você é uma pessoa com deficiência": "disability_details",
    "você é uma pessoa com deficiência": "person_with_disability",
    "aviso de diversidade": "demographic_consent_answer",
}
BLOCKED_TERMS = (
    "salary", "salário", "pretensão", "compensation", "disability", "deficiência",
    "race", "raça", "ethnicity", "etnia", "gender", "gênero", "veteran",
    "criminal", "antecedentes", "conflict of interest", "conflito de interesse",
    "visa", "sponsorship", "patrocínio", "work authorization", "autorização para trabalhar",
)


def classify_field(label: str) -> FieldRule:
    normalized = " ".join(label.lower().split()).rstrip("*").strip()
    if normalized == "nome":
        return FieldRule("first_name", False)
    if normalized == "sobrenome":
        return FieldRule("last_name", False)
    for term, key in APPROVED_QUESTION_FIELDS.items():
        if term in normalized:
            return FieldRule(key, False)
    if any(term in normalized for term in BLOCKED_TERMS):
        return FieldRule(None, True, "campo sensível ou legal")
    for term, key in KNOWN_FIELDS.items():
        if term in normalized:
            return FieldRule(key, False)
    return FieldRule(None, True, "pergunta desconhecida")
