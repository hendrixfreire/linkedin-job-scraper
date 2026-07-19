"""Automação web com Playwright; computer_use é apenas fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urljoin
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


def _dispatch_react_events(field: Any) -> None:
    """Dispatch input + change events so React/controlled forms register the value."""
    field.evaluate("""el => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        )?.set;
        const nativeTextareaValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value'
        )?.set;
        if (nativeInputValueSetter && el instanceof HTMLInputElement) {
            nativeInputValueSetter.call(el, el.value);
        } else if (nativeTextareaValueSetter && el instanceof HTMLTextAreaElement) {
            nativeTextareaValueSetter.call(el, el.value);
        }
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }""")


def _fill_react_field(field: Any, value: str) -> None:
    """Fill a text input/textarea in a way that React controlled components detect.

    Strategy:
    1. Focus the field, clear it, then type the value character by character
       using press_sequentially which dispatches real keyboard events.
    2. As a fallback, use native value setter + dispatchEvent.
    """
    # Step 1: focus and clear
    field.focus()
    field.evaluate("el => { el.select(); }")
    # Step 2: type character by character — this triggers React's event handlers
    try:
        field.press_sequentially(str(value), delay=10)
    except Exception:
        # Fallback: native setter approach
        field.evaluate("""(el, val) => {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            )?.set;
            const nativeTextareaValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            )?.set;
            if (nativeInputValueSetter && el instanceof HTMLInputElement) {
                nativeInputValueSetter.call(el, val);
            } else if (nativeTextareaValueSetter && el instanceof HTMLTextAreaElement) {
                nativeTextareaValueSetter.call(el, val);
            } else {
                el.value = val;
            }
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""", value)


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


def _matching_option_index(options: list[str], value: object) -> int | None:
    """Retorna somente uma escolha React Select exatamente aprovada no perfil."""
    expected = " ".join(str(value).casefold().split())
    for index, option in enumerate(options):
        if " ".join(option.casefold().split()) == expected:
            return index
    return None


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
            # Greenhouse/React Select uses hidden text inputs alongside visible
            # dropdown components.  When a visible dropdown (preceding sibling or
            # parent-controlled input) already has a value set, the hidden control
            # input with empty label should not block.  Skip required fields that
            # have no label AND no name/placeholder — they are React internal.
            if (not label.strip() and field_type not in ("file", "checkbox", "radio")
                    and not field.get_attribute("placeholder")):
                field_id = field.get_attribute("id") or ""
                field_name = field.get_attribute("name") or ""
                # Greenhouse control inputs often have no id/name and are siblings
                # of the visible input. Skip them if they are required but labelless.
                if not field_id and not field_name and field_type in ("text", ""):
                    continue
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
                # Verify upload: check if files are attached to the input
                try:
                    upload_ok = field.evaluate(
                        "el => el.isConnected && el.files && el.files.length >= 1"
                    )
                except Exception:
                    upload_ok = False
                if not upload_ok:
                    # React may have re-rendered and replaced the input element;
                    # check if filename appears anywhere on the page as fallback
                    try:
                        page.get_by_text(path.name, exact=True).wait_for(timeout=5000)
                        upload_ok = True
                    except Exception:
                        uploaded_visible = page.locator(f"text={path.name}").count() > 0
                        if not uploaded_visible:
                            blockers.append(f"upload não confirmado: {path.name}")
                            continue
                filled.append(rule.key or label)
                continue
            # Detect React Select comboboxes FIRST — they look like text inputs
            # but need click-type-select interaction
            field_role = field.get_attribute("role")
            aria_autocomplete = field.get_attribute("aria-autocomplete")
            is_react_select = field_role == "combobox" or aria_autocomplete == "list"

            if is_react_select:
                # React Select / Downshift pattern: click, type, wait for options, select
                field.click()
                page.wait_for_timeout(300)
                # Clear any existing text and type new value
                field.press("Control+a")
                field.press("Backspace")
                # ``query_selector_all`` yields ElementHandle objects. Older
                # Playwright versions expose ``type`` on those handles but not
                # Locator-only ``press_sequentially``.
                if hasattr(field, "press_sequentially"):
                    field.press_sequentially(str(value), delay=20)
                else:
                    field.type(str(value), delay=20)
                page.wait_for_timeout(2_500 if field.get_attribute("id") == "candidate-location" else 500)
                # Try to select from the dropdown
                try:
                    options = page.locator('[role="option"]:visible')
                    option_texts = options.all_text_contents()
                    match_index = _matching_option_index(option_texts, value)
                    if match_index is None:
                        blockers.append(f"{label}: opção aprovada não encontrada")
                        continue
                    options.nth(match_index).click()
                except Exception:
                    blockers.append(f"{label}: não foi possível confirmar a opção")
                    continue
                page.wait_for_timeout(300)
            elif tag == "select":
                # Native HTML select
                # Try label first, then value, then index-based for React selects
                try:
                    field.select_option(label=str(value))
                except Exception:
                    try:
                        field.select_option(value=str(value))
                    except Exception:
                        # Fallback: iterate options to find matching text
                        field.evaluate("""(el, target) => {
                            for (const opt of el.options) {
                                if (opt.text.trim().toLowerCase().includes(target.toLowerCase())) {
                                    el.value = opt.value;
                                    el.dispatchEvent(new Event('change', {bubbles: true}));
                                    return;
                                }
                            }
                        }""", str(value))
                _dispatch_react_events(field)
            elif field_type in ("checkbox", "radio"):
                if bool(value):
                    field.check()
                    _dispatch_react_events(field)
            else:
                # Regular text input / textarea — use React-aware fill
                _fill_react_field(field, str(value))
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


def _open_application_route(page: Any, ats: str) -> None:
    """Sai da descrição pública e abre a rota real do formulário quando o ATS a separa."""
    if ats == "ashby" and not page.url.rstrip("/").endswith("/application"):
        link = page.locator('a[href*="/application"]').first
    elif ats == "factorial" and "/job_posting/" in page.url:
        link = page.locator('a[href*="/apply/"]').first
    else:
        return
    href = link.get_attribute("href") if link.count() else None
    if href:
        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1000)


def run_application(page: Any, url: str, profile: dict[str, Any], *, auto_submit: bool, allowed_ats: set[str], screenshot_dir: str | Path) -> ApplicationResult:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1000)
    ats = detect_ats(page.url)
    _open_application_route(page, ats)
    ats = detect_ats(page.url)
    challenge = has_human_challenge(page)
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

    submit = page.locator('button[type="submit"]:visible, input[type="submit"]:visible')
    if submit.count() != 1:
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
