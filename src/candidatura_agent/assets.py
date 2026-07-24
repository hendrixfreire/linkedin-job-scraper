"""Preparação segura dos ativos necessários antes de abrir um formulário."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .db import Database


from .adapters import ATS_HOSTS, match_ats_host

# Uma fonte só: detecção em página e validação de URL externa compartilham o registro.
ATS_HOST_MARKERS = ATS_HOSTS


class _DescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class") or ""
        if self.depth:
            self.depth += 1
        elif "show-more-less-html__markup" in classes:
            self.depth = 1
        if self.depth and tag in {"p", "li", "br", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            if tag in {"p", "li", "h2", "h3"}:
                self.parts.append("\n")
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def extract_linkedin_description(html: str) -> str:
    """Extrai a descrição integral do endpoint público de detalhes do LinkedIn."""
    parser = _DescriptionParser()
    parser.feed(html)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def infer_ats(url: str) -> str:
    return match_ats_host(urlsplit(url).hostname or "") or "unknown"


def validate_external_apply_url(url: str) -> str:
    """Aceita somente HTTPS e ATS conhecidos; nunca devolve a origem LinkedIn."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("URL de candidatura deve usar HTTPS")
    if parsed.hostname == "linkedin.com" or parsed.hostname.endswith(".linkedin.com"):
        raise ValueError("URL externa não pode apontar para o LinkedIn")
    ats = infer_ats(url)
    if ats == "unknown":
        raise ValueError("ATS não reconhecido")
    return ats


def _fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 candidatura-agent/1.0"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def enrich_job_description(
    db: Database, job: dict, *, fetch_html: Callable[[str], str] = _fetch_html,
) -> str:
    """Busca e persiste a descrição integral de uma origem LinkedIn."""
    source = str(job.get("source_url") or "")
    external_id = str(job.get("external_id") or "")
    if not external_id:
        match = re.search(r"/jobs/view/(\d+)", source)
        external_id = match.group(1) if match else ""
    if not external_id:
        raise ValueError("ID do LinkedIn ausente")
    endpoint = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{external_id}"
    description = extract_linkedin_description(fetch_html(endpoint))
    if not description:
        raise ValueError("descrição do LinkedIn não encontrada")
    db.update_job_description(int(job["id"]), description)
    return description


def record_job_resolution(
    db: Database, job_id: int, apply_url: str, *, company: str | None,
    resolution_source: str,
) -> str:
    ats = validate_external_apply_url(apply_url)
    db.set_job_resolution(
        job_id, apply_url=apply_url, ats=ats, company=company,
        resolution_source=resolution_source,
    )
    return ats


def record_job_resume(db: Database, job_id: int, resume_path: str | Path) -> str:
    path = Path(resume_path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError("currículo precisa ser um PDF existente")
    if path.read_bytes()[:5] != b"%PDF-":
        raise ValueError("arquivo informado não é um PDF válido")
    db.set_job_resume(job_id, str(path))
    return str(path)
