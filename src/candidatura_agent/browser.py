"""Automação web com Playwright; computer_use é apenas fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .adapters import classify_field, detect_ats


@dataclass(frozen=True)
class FillResult:
    filled: list[str]
    blockers: list[str]

    @property
    def can_submit(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class ApplicationResult:
    status: str
    ats: str
    final_url: str
    blockers: list[str]
    filled: list[str]
    screenshot: str | None = None


def _field_label(locator: Any) -> str:
    return locator.evaluate(
        r"""el => {
          const byFor = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
          const wrapping = el.closest('label');
          const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/)
            .map(id => document.getElementById(id)?.innerText || '').join(' ');
          return [byFor?.innerText, wrapping?.innerText, labelled,
                  el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                  el.getAttribute('name'), el.id].filter(Boolean).join(' ').trim();
        }"""
    )


def fill_known_fields(page: Any, profile: dict[str, Any]) -> FillResult:
    filled: list[str] = []
    blockers: list[str] = []
    field_selectors = (
        'input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]), '
        'textarea:not([name^="g-recaptcha-response"]), select',
        'input[type=checkbox], input[type=radio]',
        'input[type=file]',
    )
    def iter_fields():
        index = 0
        for selector in field_selectors:
            for field in page.query_selector_all(selector):
                yield index, field
                index += 1

    for index, field in iter_fields():
        label = ""
        try:
            field_type = (field.get_attribute("type") or "").lower()
            if not field.is_visible() and field_type != "file":
                continue
            if field_type in ("checkbox", "radio"):
                group_checked = field.evaluate(
                    "el => el.name && Array.from(document.getElementsByName(el.name)).some(item => item.checked)"
                )
                if group_checked:
                    continue
            label = _field_label(field)
            rule = classify_field(label)
            required = field.get_attribute("required") is not None or field.get_attribute("aria-required") == "true"
            if required and field_type not in ("file", "checkbox", "radio"):
                current_value = field.input_value()
                if current_value.strip():
                    continue
            if rule.blocked:
                if required:
                    blockers.append(label or f"campo obrigatório #{index + 1}")
                continue
            value = profile.get(rule.key or "")
            if value in (None, ""):
                if required:
                    blockers.append(label or rule.key or f"campo obrigatório #{index + 1}")
                continue
            tag = field.evaluate("el => el.tagName.toLowerCase()")
            if field_type == "file":
                path = Path(str(value)).expanduser()
                if not path.exists():
                    blockers.append(f"arquivo não encontrado: {path}")
                    continue
                field.set_input_files(str(path))
                try:
                    upload_still_on_input = field.evaluate(
                        "el => el.isConnected && el.files && el.files.length === 1"
                    )
                except Exception:
                    upload_still_on_input = False
                if not upload_still_on_input:
                    page.get_by_text(path.name, exact=True).wait_for(timeout=5000)
            elif tag == "select":
                field.select_option(label=str(value))
            elif field.get_attribute("role") == "combobox":
                field.fill(str(value))
                try:
                    page.locator('[role="option"]:visible').first.wait_for(timeout=2500)
                except Exception:
                    pass
                field.press("ArrowDown")
                field.press("Enter")
            elif field_type in ("checkbox", "radio"):
                if bool(value):
                    field.check()
            else:
                field.fill(str(value))
            filled.append(rule.key or label)
        except Exception as exc:  # React pode substituir o nó durante o preenchimento.
            message = str(exc).lower()
            if "not attached" in message or "detached" in message:
                continue
            blockers.append(f"{label or f'campo #{index + 1}'}: {type(exc).__name__}")
    return FillResult(filled, blockers)


def has_human_challenge(page: Any) -> str | None:
    text = page.locator("body").inner_text(timeout=5000).lower()
    if any(term in text for term in ("captcha", "verify you are human", "verifique que você é humano")):
        return "captcha"
    if any(term in text for term in ("two-factor", "verification code", "código de verificação")):
        return "2fa"
    if page.locator('input[type="password"]').count():
        return "login"
    return None


def has_submission_confirmation(page: Any) -> bool:
    active_application_form = page.locator("input[type=file]").count() > 0
    if not active_application_form:
        submit_labels = page.locator("button[type=submit], input[type=submit]").evaluate_all(
            "els => els.map(e => (e.innerText || e.value || '').toLowerCase())"
        )
        active_application_form = any(
            "apply" in label or "submit application" in label or "enviar candidatura" in label
            for label in submit_labels
        )
    if active_application_form:
        return False

    text = page.locator("body").inner_text(timeout=5000).lower()
    text_terms = (
        "thank you for applying", "application submitted", "application has been submitted",
        "application was submitted successfully", "thanks for applying", "obrigado por se candidatar",
        "obrigada por se candidatar", "candidatura enviada", "candidatura foi enviada",
    )
    if any(term in text for term in text_terms):
        return True
    path = page.url.lower()
    return any(term in path for term in ("/confirmation", "/thank-you", "application-submitted"))


def run_application(page: Any, url: str, profile: dict[str, Any], *, auto_submit: bool, allowed_ats: set[str], screenshot_dir: str | Path) -> ApplicationResult:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1000)
    challenge = has_human_challenge(page)
    ats = detect_ats(page.url)
    if challenge:
        return ApplicationResult("blocked", ats, page.url, [challenge], [])

    fill = fill_known_fields(page, profile)
    blockers = list(fill.blockers)
    if ats not in allowed_ats:
        blockers.append(f"ATS não liberado: {ats}")

    shot_dir = Path(screenshot_dir)
    shot_dir.mkdir(parents=True, exist_ok=True)
    pre_shot = shot_dir / "last-application-pre-submit.png"
    page.screenshot(path=str(pre_shot), full_page=True)

    if blockers:
        return ApplicationResult("blocked", ats, page.url, blockers, fill.filled, str(pre_shot))
    if not auto_submit:
        return ApplicationResult("dry_run", ats, page.url, [], fill.filled, str(pre_shot))

    submit = page.get_by_role("button", name=re.compile(r"submit|send|enviar|candidatar|apply", re.I))
    if submit.count() != 1:
        return ApplicationResult("blocked", ats, page.url, ["botão de envio ambíguo"], fill.filled, str(pre_shot))
    submit.click()
    page.wait_for_timeout(1500)
    post_shot = shot_dir / "last-application-post-submit.png"
    page.screenshot(path=str(post_shot), full_page=True)
    if not has_submission_confirmation(page):
        return ApplicationResult(
            "blocked", ats, page.url, ["envio sem confirmação verificável"],
            fill.filled, str(post_shot),
        )
    return ApplicationResult("submitted", ats, page.url, [], fill.filled, str(post_shot))
