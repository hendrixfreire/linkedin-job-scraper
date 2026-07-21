"""Testes do adaptador Ashby, com HTML mock (sem rede)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

# Garante import do pacote
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from playwright.sync_api import sync_playwright

from candidatura_agent.ashby_adapter import fill_ashby_form
from candidatura_agent.adapters import detect_ats


MOCK_HTML = """<!doctype html><html><head><meta charset=utf8></head><body>
<div>
  <div>Autofill from resume</div>
  <input type="file" id="_systemfield_resume">
  <input type="text" id="_systemfield_name" name="_systemfield_name" required>
  <input type="email" id="_systemfield_email" name="_systemfield_email" required>
</div>
<div>
  <div>Have you worked for more than 5yrs in customer experience operations, support ops, implementation, or CX agency work?</div>
  <div><button type="submit">Yes</button><button type="submit">No</button></div>
</div>
<div>
  <div>Where will you be working from?</div>
  <input type="text" role="combobox" aria-autocomplete="list" id="_systemfield_location">
</div>
<div>
  <div>What is the earliest date that you will be able to start?</div>
  <input type="text" required>
</div>
<div>
  <div>What are your salary expectations? (Annual in $)</div>
  <input type="text" id="sal-uuid" required>
</div>
<div>
  <div>How do you use AI in your workflow today and what role does it play in how you manage accounts?</div>
  <textarea id="q1-uuid" required></textarea>
</div>
<div>
  <div>Walk us through a deployment that went wrong</div>
  <textarea id="q2-uuid" required></textarea>
</div>
<div>
  <input type="checkbox" name="I agree" id="x__systemfield_data_consent_ack-labeled-checkbox-0">
</div>
<button type="submit">Upload file</button>
<button type="submit">Submit Application</button>
</body></html>"""


@pytest.fixture
def profile():
    return {
        "full_name": "Candidate Name",
        "email": "candidate@example.com",
        "linkedin": "https://linkedin.com/in/example",
        "location": "São Paulo, São Paulo, Brazil",
        "resume": "/tmp/nonexistent_resume.pdf",  # não existe; upload deve ser pulado/blocked
    }


def test_detect_ashby():
    assert detect_ats("https://jobs.ashbyhq.com/siena/abc/application") == "ashby"


def test_fill_system_fields_name_email():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.set_content(MOCK_HTML)
        page.wait_for_timeout(200)
        result = fill_ashby_form(page, {"full_name": "Candidate Name", "email": "candidate@example.com",
                                        "location": "City, Country", "resume": "/tmp/no.pdf"})
        b.close()
    assert "name" in result.filled
    assert "email" in result.filled


def test_consent_checked():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.set_content(MOCK_HTML)
        page.wait_for_timeout(200)
        fill_ashby_form(page, {"full_name": "X", "email": "x@x.com", "location": "C", "resume": "/tmp/no.pdf"})
        checked = page.evaluate("document.querySelector('input[id*=data_consent_ack]').checked")
        b.close()
    assert checked is True


def test_custom_required_without_answer_blocks():
    # salary, date e as 2 textareas são required e sem resposta aprovada no profile
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.set_content(MOCK_HTML)
        page.wait_for_timeout(200)
        result = fill_ashby_form(page, {"full_name": "X", "email": "x@x.com", "location": "C", "resume": "/tmp/no.pdf"})
        b.close()
    # deve haver blockers para os campos required sem resposta
    blockers_text = " ".join(result.blockers).lower()
    assert "salary" in blockers_text or "salário" in blockers_text
    assert "date" in blockers_text or "data" in blockers_text
    assert "ai" in blockers_text or "deployment" in blockers_text


def test_resume_not_found_blocks():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.set_content(MOCK_HTML)
        page.wait_for_timeout(200)
        result = fill_ashby_form(page, {"full_name": "X", "email": "x@x.com", "location": "C", "resume": "/tmp/no.pdf"})
        b.close()
    assert any("resume" in b.lower() or "cv" in b.lower() for b in result.blockers)


def test_submit_application_button_filtered():
    # garante que o botão certo existe e é único por texto (não testa clique aqui)
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.set_content(MOCK_HTML)
        page.wait_for_timeout(200)
        count = page.get_by_role("button", name="Submit Application").count()
        total_submit_type = page.locator("button[type=submit]").count()
        b.close()
    assert count == 1
    assert total_submit_type > 1  # prova que o filtro por texto é necessário


def test_yesno_not_blocked_when_optional():
    # a pergunta yes/no no mock é required=False, não deve virar blocker
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.set_content(MOCK_HTML)
        page.wait_for_timeout(200)
        result = fill_ashby_form(page, {"full_name": "X", "email": "x@x.com", "location": "C", "resume": "/tmp/no.pdf"})
        b.close()
    blockers_text = " ".join(result.blockers).lower()
    assert "customer experience operations" not in blockers_text
