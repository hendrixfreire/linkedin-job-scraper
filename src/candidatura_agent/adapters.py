"""Detecção de ATS e classificação conservadora de campos."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import unicodedata
from urllib.parse import urlparse


@dataclass(frozen=True)
class FieldRule:
    key: str | None
    blocked: bool
    reason: str = ""
    value: Any = None


# Registro único de ATS, consumido tanto pela detecção em página quanto pela
# validação de URL externa. Cobre os sistemas efetivamente encontrados nas vagas
# do funil — vagas com URL oficial correta vinham sendo descartadas por ausência
# do host nesta lista.
ATS_HOSTS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("greenhouse.io",),
    "lever": ("lever.co",),
    "ashby": ("ashbyhq.com",),
    "workday": ("myworkdayjobs.com", "workday.com"),
    "gupy": ("gupy.io",),
    "peopleforce": ("peopleforce.io", "peopleforce.com"),
    "factorial": ("factorialhr.com", "factorialhr.com.br"),
    "smartrecruiters": ("smartrecruiters.com",),
    "solides": ("solides.jobs", "solides.com.br"),
    "recruitee": ("recruitee.com",),
    "workable": ("workable.com",),
    "teamtailor": ("teamtailor.com",),
    "bamboohr": ("bamboohr.com",),
    "jobvite": ("jobvite.com",),
    "icims": ("icims.com",),
    "jazzhr": ("applytojob.com",),
    "breezy": ("breezy.hr",),
    "taleo": ("taleo.net",),
    "oracle": ("oraclecloud.com",),
    "successfactors": ("successfactors.com", "sapsf.com"),
    "abler": ("abler.com.br",),
    "kenoby": ("kenoby.com",),
    "pandape": ("pandape.com", "pandape.infojobs.com.br"),
    "inhire": ("inhire.app", "inhire.io"),
    "quickin": ("quickin.io",),
    "compleo": ("compleo.com.br",),
    "inrecruiting": ("inrecruiting.com",),
    "vagas": ("vagas.com.br",),
    "infojobs": ("infojobs.com.br",),
}


def match_ats_host(host: str) -> str | None:
    """Casa o host pelo domínio registrável, não por substring.

    "evil-greenhouse.io.attacker.com" não pode passar por Greenhouse: `detect_ats`
    alimenta a checagem de ATS liberado antes do envio.
    """
    host = (host or "").lower().split(":")[0]
    for ats, markers in ATS_HOSTS.items():
        if any(host == marker or host.endswith("." + marker) for marker in markers):
            return ats
    return None


def detect_ats(url: str) -> str:
    return match_ats_host(urlparse(url).netloc) or "generic"


KNOWN_FIELDS = {
    "full name": "full_name", "nome completo": "full_name",
    "first name": "first_name", "last name": "last_name",
    "nome": "first_name", "sobrenome": "last_name", "primeiro nome": "first_name",
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

# Perguntas recorrentes observadas nos formulários reais, mapeadas para a chave do
# perfil que já contém a resposta. Um padrão só entra no caderno de respostas quando
# a chave correspondente está preenchida — nada é inferido do texto da vaga.
QUESTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("cpf", "cpf"),
    ("nome de preferência", "first_name"),
    ("preferred name", "first_name"),
    ("identidade de gênero", "gender_identity"),
    ("gender identity", "gender_identity"),
    ("raça e/ou cor", "race_ethnicity"),
    ("orientação sexual", "sexual_orientation"),
    ("sexual orientation", "sexual_orientation"),
    ("underrepresented group", "underrepresented_group"),
    ("grupo sub-representado", "underrepresented_group"),
    ("race and/or color", "race_ethnicity"),
    ("possui alguma deficiência", "person_with_disability"),
    ("person with a disability", "person_with_disability"),
    ("pessoa com deficiência", "person_with_disability"),
    ("nível de fluência na língua inglesa", "greenhouse_recurring_answers.english_level"),
    ("nível de inglês", "greenhouse_recurring_answers.english_level"),
    ("english level", "greenhouse_recurring_answers.english_level"),
    ("english proficiency", "english_proficiency"),
    ("nível de fluência na língua espanhola", "greenhouse_recurring_answers.spanish_level"),
    ("spanish level", "greenhouse_recurring_answers.spanish_level"),
    ("authorized to work", "greenhouse_recurring_answers.work_authorization"),
    ("autorização para trabalhar", "greenhouse_recurring_answers.work_authorization"),
    ("salário atual", "current_base_salary_answer"),
    ("current base salary", "current_base_salary_answer"),
    ("expected base salary", "expected_base_salary_answer"),
    ("salary expectation", "expected_base_salary_answer"),
    ("pretensão salarial", "expected_base_salary_answer"),
    ("benefícios atuais", "current_benefits"),
    ("availability to start", "start_availability"),
    ("disponibilidade para início", "start_availability"),
    ("expected monthly gross wage in euros", "expected_monthly_gross_eur"),
    ("trabalha atualmente no", "worked_at_hiring_company"),
    ("trabalha atualmente na", "worked_at_hiring_company"),
    ("já trabalhou em algum momento", "worked_at_hiring_company"),
    ("você trabalha no", "worked_at_hiring_company"),
    ("are you a currently", "worked_at_hiring_company"),
    ("are you currently an employee", "worked_at_hiring_company"),
    ("have you ever been a", "worked_at_hiring_company"),
    ("have you previously worked at", "worked_at_hiring_company"),
    ("pessoa indicada por", "referred_by_employee"),
    ("conhece alguém que trabalha", "referred_by_employee"),
    ("refer you", "referred_by_employee"),
    ("grau de parentesco", "relative_at_hiring_company"),
    ("relatives currently working", "relative_at_hiring_company"),
    ("how did you hear about", "application_source"),
    ("como você nos conheceu", "application_source"),
    ("curso superior completo", "higher_education_complete"),
    ("em qual curso você se formou", "degree_field"),
    ("possui alguma certificação", "certifications"),
    ("conhecimento em python", "python_skill_level"),
    ("conhecimento em sql", "sql_skill_level"),
    ("nome da empresa", "last_employer"),
    ("company name", "last_employer"),
    ("nothing to declare", "conflict_nothing_to_declare"),
    ("política de privacidade", "privacy_consent"),
    ("aviso de privacidade", "privacy_consent"),
    ("privacy policy", "privacy_consent"),
    ("privacy notice", "privacy_consent"),
    ("processing your personal information", "privacy_consent"),
    ("modelo 100% presencial", "fulltime_onsite_answer"),
    ("work from the office", "onsite_availability_answer"),
    ("in-office work", "onsite_availability_answer"),
)


def _normalize(text: str) -> str:
    """Reduz um rótulo ao seu texto comparável: sem acento, sem ruído técnico."""
    lowered = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(char for char in lowered if not unicodedata.combining(char))
    stripped = re.sub(r"question_\d+|custom-field-\d+|_\d{4,}", " ", stripped)
    return " ".join(re.sub(r"[*\[\].,;:?!/()\"'\-]", " ", stripped).split())


def _names_the_field(normalized: str, term: str) -> bool:
    """Um rótulo de identidade nomeia o campo logo no início, não no meio de uma frase.

    Sem isso, "the specified location" numa pergunta de mudança de cidade seria
    preenchido com a cidade do candidato.
    """
    head = " ".join(normalized.split()[:4])
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", head) is not None


def _profile_value(profile: dict[str, Any], path: str) -> Any:
    current: Any = profile
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def build_answer_book(profile: dict[str, Any]) -> dict[str, Any]:
    """Consolida as respostas que o perfil autoriza, indexadas pelo texto da pergunta.

    Precedência crescente: padrões embutidos, respostas recorrentes do Greenhouse e,
    por último, `question_answers` — o bloco livre onde o usuário resolve perguntas
    novas sem tocar no código.
    """
    book: dict[str, Any] = {}
    for pattern, path in QUESTION_PATTERNS:
        value = _profile_value(profile, path)
        if value not in (None, ""):
            book[_normalize(pattern)] = value
    for question, value in (profile.get("question_answers") or {}).items():
        if value not in (None, ""):
            book[_normalize(question)] = value
    return book


def _matching_answer(normalized: str, answers: dict[str, Any]) -> str | None:
    """Devolve o padrão mais específico que descreve o rótulo, ou None."""
    matches = [pattern for pattern in answers if pattern and pattern in normalized]
    return max(matches, key=len) if matches else None


def match_choice(value: str | list[str], options: list[str]) -> tuple[int | None, str]:
    """Casa uma resposta aprovada com as opções oferecidas pelo formulário.

    Escada de tolerância: texto idêntico, texto normalizado, e por fim opção que
    contém a resposta — esta última só quando houver uma única candidata. A
    ambiguidade nunca é resolvida por chute; vira bloqueio.

    Uma lista declara redações alternativas da mesma resposta ("Prefiro não
    responder" / "Prefer not to say"), tentadas na ordem em que foram aprovadas.
    """
    if isinstance(value, list):
        verdict = "missing"
        for alternative in value:
            index, verdict = match_choice(alternative, options)
            if index is not None:
                return index, verdict
        return None, verdict
    wanted = _normalize(value)
    if not wanted:
        return None, "missing"
    for index, option in enumerate(options):
        if option.strip() == value.strip():
            return index, "ok"
    normalized = [_normalize(option) for option in options]
    exact = [index for index, option in enumerate(normalized) if option == wanted]
    if len(exact) == 1:
        return exact[0], "ok"
    if len(exact) > 1:
        return None, "ambiguous"
    partial = [index for index, option in enumerate(normalized) if option and wanted in option]
    if len(partial) == 1:
        return partial[0], "ok"
    if len(partial) > 1:
        return None, "ambiguous"
    return None, "missing"


def classify_field(label: str, answers: dict[str, Any] | None = None) -> FieldRule:
    normalized = _normalize(label)
    if answers:
        pattern = _matching_answer(normalized, answers)
        if pattern is not None:
            return FieldRule(None, False, value=answers[pattern])
    for term, key in APPROVED_QUESTION_FIELDS.items():
        if _normalize(term) in normalized:
            return FieldRule(key, False)
    if any(_normalize(term) in normalized for term in BLOCKED_TERMS):
        return FieldRule(None, True, "campo sensível ou legal")
    for term, key in KNOWN_FIELDS.items():
        if _names_the_field(normalized, _normalize(term)):
            return FieldRule(key, False)
    return FieldRule(None, True, "pergunta desconhecida")
