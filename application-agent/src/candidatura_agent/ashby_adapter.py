"""Adaptador Ashby: preenchimento de forms jobs.ashbyhq.com.

O `fill_known_fields` genérico de browser.py não cobre campos customizados do
Ashby (UUIDs, combobox React Select, date, Yes/No como <button>). Este módulo
implementa o preenchimento específico, seguindo a receita DOM verificada na
skill ats-ashby-form.

Regras de segurança (herdadas do pipeline):
- NUNCA inventa respostas factuais. Campos customizados (discursivas, salário,
  data, elegibilidade) só são preenchidos se houver valor aprovado mapeável no
  profile; caso contrário, se required, viram blocker com o label da pergunta.
- Campos de sistema (nome, email, location, consent) são preenchidos sempre.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import classify_field


@dataclass
class FillResult:
    filled: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def _react_set_value_js() -> str:
    return r"""(args) => {
      const [id, val] = args;
      const el = document.getElementById(id);
      if (!el) return {ok:false, reason:"element not found"};
      el.scrollIntoView({block:"center"});
      el.focus();
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(el, val); else el.value = val;
      el.dispatchEvent(new Event("input", {bubbles:true}));
      el.dispatchEvent(new Event("change", {bubbles:true}));
      el.dispatchEvent(new Event("blur", {bubbles:true}));
      return {ok:true, valueLen: el.value ? el.value.length : 0};
    }"""


def _fill_by_id(page: Any, field_id: str, value: str, label: str) -> bool:
    r = page.evaluate(_react_set_value_js(), [field_id, value])
    if r.get("ok"):
        return True
    return False


def _fill_by_wrapper(page: Any, question: str, value: str) -> bool:
    """Preenche input/textarea sem ID casando pelo texto da pergunta no parent imediato."""
    JS = r"""(args) => {
      const [q, val] = args;
      const ql = q.toLowerCase();
      const els = [...document.querySelectorAll("input,textarea")];
      for (const el of els) {
        // parent imediato (depth 0) isola a pergunta deste campo
        const p0 = el.parentElement;
        const t0 = (p0 ? p0.innerText : "").toLowerCase();
        let matched = t0.includes(ql);
        if (!matched) {
          let n = el.parentElement; let best = "";
          for (let i=0;i<3 && n;i++){ const t=(n.innerText||"").trim(); if(t.length>5&&t.length<350) best=t; n=n.parentElement; }
          matched = best.toLowerCase().includes(ql);
        }
        if (matched) {
          el.scrollIntoView({block:"center"}); el.focus();
          const setter = (el instanceof HTMLTextAreaElement)
            ? Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set
            : Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
          if (setter) setter.call(el, val); else el.value = val;
          el.dispatchEvent(new Event("input", {bubbles:true}));
          el.dispatchEvent(new Event("change", {bubbles:true}));
          el.dispatchEvent(new Event("blur", {bubbles:true}));
          return {ok:true};
        }
      }
      return {ok:false};
    }"""
    r = page.evaluate(JS, [question, value])
    return bool(r.get("ok"))


def _click_yesno(page: Any, question: str, answer: str) -> bool:
    """Clica no <button> Yes/No dentro do wrapper da pergunta."""
    JS = r"""(args) => {
      const [q, ans] = args;
      const ql = q.toLowerCase(); const want = ans.toLowerCase();
      let wrapper = null;
      for (const el of [...document.querySelectorAll("div, section, fieldset")]) {
        const t = (el.innerText || "").toLowerCase();
        // wrapper deve conter pergunta E resposta (garante que inclui os botões)
        if (t.includes(ql) && t.includes(want) && t.length < 700) {
          if (!wrapper || el.querySelectorAll("*").length < wrapper.querySelectorAll("*").length) wrapper = el;
        }
      }
      if (!wrapper) return {clicked:false, reason:"wrapper not found"};
      for (const el of [...wrapper.querySelectorAll("label, button, span, div, input")]) {
        if ((el.innerText || el.value || "").trim().toLowerCase() === want) {
          const target = (el.tagName === "INPUT") ? el : (el.querySelector("input[type=radio],input[type=checkbox]") || el);
          target.click();
          return {clicked:true};
        }
      }
      return {clicked:false, reason:"yes/no not found"};
    }"""
    r = page.evaluate(JS, [question, answer])
    return bool(r.get("clicked"))


def _field_label(page: Any, el_ref_id: str) -> str:
    """Extrai o label/pergunta de um campo pelo parent imediato."""
    return page.evaluate(r"""(id) => {
      const el = document.getElementById(id);
      if (!el) return "";
      const p0 = el.parentElement;
      return (p0 ? p0.innerText : "").trim();
    }""", el_ref_id)


def _collect_custom_fields(page: Any) -> list[dict]:
    """Lista campos customizados (input/textarea com id UUID ou sem id) com label e required."""
    return page.evaluate(r"""() => {
      const out = [];
      document.querySelectorAll("input,textarea,select").forEach(el => {
        const id = el.id || "";
        const name = el.name || "";
        // pula campos de sistema
        if (id.startsWith("_systemfield")) return;
        if (id === "" && name === "") {
          // sem id/name: só relevante se tiver wrapper de pergunta
        }
        const p0 = el.parentElement;
        let label = (p0 ? p0.innerText : "").trim();
        if (!label) {
          let n = el.parentElement; let d=0;
          while (n && d<3) { const t=(n.innerText||"").trim(); if(t.length>5&&t.length<350){label=t;break;} n=n.parentElement; d++; }
        }
        out.push({id, name, type: el.type, required: el.required, label: label.slice(0,200), role: el.getAttribute("role")});
      });
      return out.filter(f => f.label && !f.label.toLowerCase().includes("autofill"));
    }""")


def fill_ashby_form(page: Any, profile: dict) -> FillResult:
    """Preenche um form Ashby. Retorna FillResult(filled, blockers).

    Campos de sistema (nome, email, resume, location, consent) sempre preenchidos.
    Campos customizados: só preenchidos se houver valor aprovado mapeável no
    profile via classify_field; senão, se required, viram blocker.
    """
    result = FillResult()

    # 1. Resume upload (pode disparar autofill)
    resume_path = profile.get("resume")
    if resume_path and Path(str(resume_path)).expanduser().exists():
        try:
            page.locator("input#_systemfield_resume").first.set_input_files(str(Path(str(resume_path)).expanduser()))
            page.wait_for_timeout(800)
            result.filled.append("resume")
        except Exception as e:
            result.blockers.append(f"resume upload falhou: {type(e).__name__}")
    else:
        result.blockers.append("resume: arquivo não encontrado (campo obrigatório)")

    # 2. Nome e email por ID estável
    if _fill_by_id(page, "_systemfield_name", profile.get("full_name", ""), "name"):
        result.filled.append("name")
    if _fill_by_id(page, "_systemfield_email", profile.get("email", ""), "email"):
        result.filled.append("email")

    # 3. Location (combobox React Select) — se existir o campo
    loc = profile.get("location")
    if loc:
        try:
            combo = page.locator('input[role="combobox"]').first
            if combo.count():
                combo.scroll_into_view_if_needed(timeout=5000)
                combo.click()
                page.wait_for_timeout(400)
                combo.fill("")
                combo.press_sequentially(str(loc).split(",")[0], delay=30)
                page.wait_for_timeout(1200)
                opts = page.locator('[role="option"]:visible, [role="listbox"] [role="option"]')
                chosen = False
                for i in range(opts.count()):
                    txt = opts.nth(i).inner_text(timeout=2000).strip()
                    if str(loc).lower() in txt.lower():
                        opts.nth(i).click(); chosen = True; break
                if not chosen and opts.count() > 0:
                    opts.nth(0).click(); chosen = True
                if chosen:
                    result.filled.append("location")
        except Exception:
            pass  # location opcional no preenchimento; não bloqueia

    # 4. Campos customizados: mapear por label → classify_field → profile[key]
    custom = _collect_custom_fields(page)
    for f in custom:
        label = f.get("label", "")
        fid = f.get("id", "")
        required = f.get("required", False)
        ftype = f.get("type", "")
        # pula checkbox de consent (tratado depois) e file (resume já tratado)
        if ftype == "file":
            continue
        if "data_consent_ack" in (f.get("id","") + f.get("name","")):
            continue
        if not label:
            continue
        rule = classify_field(label)
        # Se é pergunta bloqueada (sensível/legal) e required → blocker
        if rule.blocked:
            if required:
                result.blockers.append(label[:80])
            continue
        value = profile.get(rule.key or "") if rule.key else None
        if value in (None, ""):
            if required:
                result.blockers.append(label[:80])
            continue
        # tem valor aprovado — preenche
        # Yes/No (button group): se o campo for checkbox/radio com wrapper yes/no, usa click
        if ftype in ("checkbox", "radio") or "yes" in label.lower() and "no" in label.lower():
            ans = "Yes" if str(value).lower() in ("yes","true","sim","1") else "No"
            if _click_yesno(page, label, ans):
                result.filled.append(rule.key or label[:40])
            elif required:
                result.blockers.append(label[:80])
        else:
            ok = _fill_by_id(page, fid, str(value), label) if fid else _fill_by_wrapper(page, label, str(value))
            if ok:
                result.filled.append(rule.key or label[:40])
            elif required:
                result.blockers.append(label[:80])

    # 5. Consent checkbox
    try:
        page.locator("input[type=checkbox][id*='data_consent_ack']").first.check(force=True)
        result.filled.append("consent")
    except Exception:
        pass  # consent nem sempre presente

    return result
