"""Automação web com Playwright; computer_use é apenas fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .adapters import build_answer_book, classify_field, detect_ats, match_choice


CHOICE_FAILURES = {
    "missing": "opção aprovada não encontrada",
    "ambiguous": "escolha ambígua entre as opções oferecidas",
}


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


def _as_choice(value: Any) -> str | list[str]:
    """Preserva a lista de redações alternativas; o resto vira texto."""
    if isinstance(value, list):
        return [str(item) for item in value]
    return str(value)


def _alternatives(value: Any) -> list[str]:
    """As redações aprovadas de uma resposta, sempre como lista."""
    choice = _as_choice(value)
    return choice if isinstance(choice, list) else [choice]


def _is_addressable(locator: Any) -> bool:
    """Um campo que o formulário identifica de alguma forma — id ou name."""
    return bool(locator.evaluate("el => Boolean(el.id || el.name)"))


def _choice_group_label(locator: Any) -> str:
    """Texto da pergunta que governa um grupo de radio/checkbox.

    O rótulo de um radio é só a opção ("Sim"); a pergunta vive no ancestral que
    reúne o grupo. Sem ela, toda escolha chegaria à classificação como "Sim".
    """
    return locator.evaluate(
        r"""el => {
          if (!el.name) return '';
          let node = el.parentElement;
          while (node && node !== document.body) {
            const siblings = node.querySelectorAll(
              `input[name="${CSS.escape(el.name)}"]`).length;
            if (node.matches('fieldset') || siblings > 1) return (node.innerText || '').trim();
            node = node.parentElement;
          }
          return '';
        }"""
    )


def _choice_options(locator: Any) -> list[str]:
    """Rótulos visíveis de cada opção de um grupo de radio/checkbox."""
    return locator.evaluate(
        r"""el => Array.from(document.getElementsByName(el.name)).map(item => {
          const byFor = item.id ? document.querySelector(`label[for="${CSS.escape(item.id)}"]`) : null;
          const wrapping = item.closest('label');
          return (byFor?.innerText || wrapping?.innerText || item.value || '').trim();
        })"""
    )


def _check_choice(locator: Any, index: int) -> None:
    """Marca a opção pelo Playwright, não por click() sintético.

    Um click() programático num controle dentro de <label> sobe até o rótulo, que
    o reativa — o campo marca e desmarca no mesmo gesto.
    """
    target = locator.evaluate_handle(
        "(el, index) => document.getElementsByName(el.name)[index]", index
    ).as_element()
    target.check()


def _combobox_display(locator: Any) -> str:
    """O texto que o combobox exibe ao redor do input, sem o que foi digitado.

    react-select limpa o input ao confirmar e mostra o escolhido num elemento
    próprio — mas mantém o texto digitado quando nada casa. Misturar os dois faria
    uma busca fracassada parecer uma seleção bem-sucedida.
    """
    return locator.evaluate(
        r"""el => {
          let node = el.parentElement, around = '';
          for (let level = 0; level < 3 && node; level++) {
            around = (node.innerText || '').trim();
            if (around) break;
            node = node.parentElement;
          }
          return around;
        }"""
    )


def _select_labels(locator: Any) -> list[str]:
    return locator.evaluate(
        "el => Array.from(el.options).map(o => (o.label || o.textContent || '').trim())"
    )


def _visible_options(page: Any) -> Any:
    return page.locator('[role="option"]:visible')


def _open_combobox(page: Any, locator: Any, wording: str | None = None) -> list[str]:
    """Abre a lista e devolve as opções oferecidas, filtrando se preciso."""
    locator.click()
    if wording is not None:
        locator.fill(wording)
    try:
        _visible_options(page).first.wait_for(timeout=2500)
    except Exception:
        return []
    return [text.strip() for text in _visible_options(page).all_inner_texts()]


def choose_in_combobox(page: Any, locator: Any, value: Any) -> str:
    """Escolhe clicando na opção que corresponde à resposta aprovada.

    Ler as opções e clicar na certa substitui digitar e supor: o react-select
    mantém no input o texto que não casou nada, e isso fazia uma busca fracassada
    passar por seleção — o formulário do C6 foi dado como completo com o campo de
    raça/cor em branco. Devolve "ok", "missing" ou "ambiguous".
    """
    options = _open_combobox(page, locator)
    index, verdict = match_choice(_as_choice(value), options)
    if index is None:
        for wording in _alternatives(value):
            options = _open_combobox(page, locator, wording)
            index, verdict = match_choice(wording, options)
            if index is not None:
                break
    if index is None:
        # Sem limpar, o texto da última tentativa fica no campo e parece resposta.
        locator.fill("")
        locator.press("Escape")
        return verdict
    _visible_options(page).nth(index).click()
    return "ok"


def fill_known_fields(page: Any, profile: dict[str, Any]) -> FillResult:
    filled: list[str] = []
    blockers: list[str] = []
    answers = build_answer_book(profile)
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
            if not label.strip() and not _is_addressable(field):
                # Proxy de validação do react-select: sem id, sem name e sem rótulo,
                # não é uma pergunta — o campo real é o combobox que o acompanha.
                continue
            if field_type in ("checkbox", "radio"):
                label = " ".join(filter(None, (_choice_group_label(field), label)))
            rule = classify_field(label, answers)
            required = field.get_attribute("required") is not None or field.get_attribute("aria-required") == "true"
            if required and field_type not in ("file", "checkbox", "radio"):
                current_value = field.input_value()
                if current_value.strip():
                    continue
            if rule.blocked:
                if required:
                    blockers.append(label or f"campo obrigatório #{index + 1}")
                continue
            value = rule.value if rule.value is not None else profile.get(rule.key or "")
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
                options = _select_labels(field)
                index, verdict = match_choice(_as_choice(value), options)
                if index is None:
                    blockers.append(f"{label}: {CHOICE_FAILURES[verdict]}")
                    continue
                field.select_option(index=index)
            elif field.get_attribute("role") == "combobox":
                verdict = choose_in_combobox(page, field, value)
                if verdict != "ok":
                    blockers.append(f"{label}: {CHOICE_FAILURES[verdict]}")
                    continue
            elif field_type in ("checkbox", "radio"):
                if isinstance(value, bool):
                    if value:
                        field.check()
                else:
                    index, verdict = match_choice(_as_choice(value), _choice_options(field))
                    if index is None:
                        blockers.append(f"{label}: {CHOICE_FAILURES[verdict]}")
                        continue
                    _check_choice(field, index)
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


SUBMIT_NAMES = re.compile(r"submit|send|enviar|candidatar|apply", re.I)


def _wait_for_form(page: Any) -> None:
    """Espera o formulário montar antes de julgar a página.

    Formulários React só existem depois do domcontentloaded; medir cedo demais
    mostra uma página quase vazia, sem perguntas e portanto sem bloqueios.
    """
    try:
        page.locator("input:not([type=hidden]), select, textarea").first.wait_for(timeout=8000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1000)


def _submit_button(page: Any) -> Any | None:
    """O botão que realmente envia, ou None se não der para decidir com certeza.

    Greenhouse em PT expõe "Candidate-se" — uma âncora que apenas rola até o
    formulário, mas cujo nome acessível ("Apply for this job") casa o mesmo padrão
    do botão de envio. O desempate é `type=submit`, e só quando houver um único.
    """
    matches = page.get_by_role("button", name=SUBMIT_NAMES)
    total = matches.count()
    if total == 1:
        return matches.first
    submitters = [
        index for index in range(total)
        if (matches.nth(index).get_attribute("type") or "").lower() == "submit"
    ]
    if len(submitters) == 1:
        return matches.nth(submitters[0])
    return None


def run_application(page: Any, url: str, profile: dict[str, Any], *, auto_submit: bool, allowed_ats: set[str], screenshot_dir: str | Path) -> ApplicationResult:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    _wait_for_form(page)
    challenge = has_human_challenge(page)
    ats = detect_ats(page.url)
    if challenge:
        return ApplicationResult("blocked", ats, page.url, [challenge], [])

    fill = fill_known_fields(page, profile)
    blockers = list(fill.blockers)
    if not fill.filled and not fill.blockers:
        # Nada preenchido e nada bloqueado significa que não havia formulário:
        # vaga expirada, página de erro ou formulário que só abre após um clique.
        blockers.append("formulário de candidatura não encontrado")
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

    submit = _submit_button(page)
    if submit is None:
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
