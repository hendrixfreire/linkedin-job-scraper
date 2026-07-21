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


def _collect_yesno_questions(page: Any) -> list[dict]:
    """Mapeia perguntas Yes/No do Ashby renderizadas como <button>Yes/No</button>
    com um <input type=checkbox> escondido.

    O label do checkbox só vem "Yes\\nNo"; o texto real da pergunta está num
    <label class="...question-title"> irmão dentro do mesmo field-entry.
    Retorna [{name, question, required, options:["Yes","No"]}].
    """
    return page.evaluate(r"""() => {
      const out = [];
      // cada container _yesno_ tem um checkbox com name=UUID
      document.querySelectorAll('[class*="_yesno_"]').forEach(cont => {
        const cb = cont.querySelector('input[type=checkbox]');
        if (!cb) return;
        const name = cb.name || '';
        // field-entry pai contém o label da pergunta
        const entry = cont.closest('[class*="field-entry"], [class*="fieldEntry"]');
        let question = '';
        let required = false;
        if (entry) {
          const heading = entry.querySelector('[class*="question-title"], [class*="heading"]');
          if (heading) {
            question = (heading.innerText || '').trim();
            required = /_required/.test(heading.className || '');
          }
        }
        const options = [...cont.querySelectorAll('button')].map(b => (b.innerText || '').trim()).filter(Boolean);
        if (question && options.length >= 2) out.push({name, question, required, options});
      });
      return out;
    }""")


def _click_yesno_button(page: Any, group_name: str, answer: str) -> bool:
    """Clica no botão Yes/No do Ashby pelo name do checkbox hidden."""
    JS = r"""(args) => {
      const [name, ans] = args;
      const want = ans.toLowerCase();
      const cb = document.querySelector(`input[type=checkbox][name="${name}"]`);
      if (!cb) return {ok:false};
      const cont = cb.closest('[class*="_yesno_"]');
      if (!cont) return {ok:false};
      for (const btn of [...cont.querySelectorAll('button')]) {
        if ((btn.innerText || '').trim().toLowerCase() === want) { btn.click(); return {ok:true}; }
      }
      return {ok:false};
    }"""
    r = page.evaluate(JS, [group_name, answer])
    return bool(r.get("ok"))


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


def _collect_radio_groups(page: Any) -> list[dict]:
    """Mapeia radio groups nomeados (perguntas com opções como years/english level).

    Cada grupo: {name, question, required, options:[{id,label}]}.
    O Ashby renderiza perguntas do tipo "How many years..." e "English proficiency"
    como input[type=radio] agrupados por name; o heading da pergunta fica num
    elemento [class*="heading"] acima do grupo. O required é inferido pela
    presença da classe "_required" no heading.
    """
    return page.evaluate(r"""() => {
      const groups = [];
      const names = [...new Set([...document.querySelectorAll('input[type=radio]')]
        .map(r => r.name).filter(Boolean))];
      for (const name of names) {
        const radios = [...document.querySelectorAll(`input[type=radio][name="${name}"]`)];
        if (!radios.length) continue;
        // O heading da pergunta no Ashby tem classe contendo "_heading_" e NÃO
        // contém "option"/"_label_1258i" (que são labels das opções). Subimos dos
        // radios até achar esse heading real da pergunta.
        let heading = '';
        let required = false;
        let n = radios[0];
        for (let i = 0; i < 8 && n; i++) {
          n = n.parentElement;
          if (!n) break;
          // heading da pergunta: classe com _heading_ e sem _label_1258i/option
          const cand = [...n.querySelectorAll('[class*="heading"], [class*="_label_1e3gg"]')];
          for (const h of cand) {
            const cls = h.className || '';
            if (/_label_1258i|option/.test(cls)) continue;
            const t = (h.innerText || '').trim();
            if (t.length > 5 && t.length < 300 && !/[0-9]+\s*year|Beginner|Elementary|Intermediate|Upper|Advanced|Proficient/.test(t)) {
              heading = t;
              // required: heading ou parent próximo tem classe _required
              required = /_required/.test(cls) || /_required/.test(n.innerHTML);
              break;
            }
          }
          if (heading) break;
        }
        const options = radios.map(r => {
          let label = '';
          const lab = document.querySelector(`label[for="${r.id}"]`);
          if (lab) label = (lab.innerText || '').trim();
          if (!label) {
            const opt = r.closest('[class*="option"]');
            if (opt) label = (opt.innerText || '').trim();
          }
          return { id: r.id, label };
        }).filter(o => o.label);
        if (heading && options.length) groups.push({ name, question: heading, required, options });
      }
      return groups;
    }""")


def _select_radio_by_label(page: Any, group_name: str, target_label: str) -> bool:
    """Clica no radio cujo label casa (case-insensitive, substring).

    O Ashby renderiza radios como inputs hidden controlados por React; clicar
    no input via page.check() não dispara o onChange. Precisamos clicar no
    elemento visível (label[for] ou wrapper .option) que o usuário clicaria.
    """
    want = target_label.lower()
    # localiza o seletor CSS do wrapper visível (label[for] preferencial)
    target_sel = page.evaluate(
        r"""(args) => {
          const [name, want] = args;
          const w = want.toLowerCase();
          const radios = [...document.querySelectorAll(`input[type=radio][name="${name}"]`)];
          for (const r of radios) {
            let label = '';
            const lab = document.querySelector(`label[for="${r.id}"]`);
            if (lab) label = (lab.innerText || '').trim().toLowerCase();
            if (!label) {
              const opt = r.closest('[class*="option"]');
              if (opt) label = (opt.innerText || '').trim().toLowerCase();
            }
            if (label && label.includes(w)) {
              // preferir label[for]; senão o wrapper option
              if (lab) return {sel: `label[for="${r.id}"]`, id: r.id};
              const opt = r.closest('[class*="option"]');
              if (opt) return {sel: null, id: r.id, optId: opt.id || ''};
            }
          }
          return null;
        }""",
        [group_name, target_label],
    )
    if not target_sel:
        return False
    try:
        if target_sel.get("sel"):
            page.locator(target_sel["sel"]).first.click(timeout=5000)
        else:
            # clica no wrapper option via evaluate (React onClick)
            page.evaluate(
                r"""(id) => {
                  const r = document.getElementById(id);
                  if (!r) return;
                  const opt = r.closest('[class*="option"]') || r.closest('label') || r;
                  opt.click();
                }""",
                target_sel["id"],
            )
        return True
    except Exception:
        return False


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

    # 4b. Radio groups nomeados (years of experience, english proficiency, etc.)
    # O Ashby renderiza perguntas com opções fixas como input[type=radio] agrupados
    # por name. _collect_custom_fields captura cada radio individual, mas sem a
    # noção de grupo; este bloco resolve o grupo inteiro de uma vez, casando a
    # pergunta contra o profile e selecionando a opção cujo label contém o valor.
    radio_groups = _collect_radio_groups(page)
    for g in radio_groups:
        question = g.get("question", "") or ""
        options = g.get("options", [])
        gname = g.get("name", "")
        greq = g.get("required", False)
        if not question or not options:
            continue
        # pula consent
        if "data_consent_ack" in gname:
            continue
        rule = classify_field(question)
        if rule.blocked:
            if greq:
                result.blockers.append(question[:80])
            continue
        value = profile.get(rule.key or "") if rule.key else None
        if value in (None, ""):
            if greq:
                result.blockers.append(question[:80])
            continue
        if _select_radio_by_label(page, gname, str(value)):
            result.filled.append(rule.key or question[:40])
        elif greq:
            result.blockers.append(question[:80])

    # 4c. Perguntas Yes/No renderizadas como <button>Yes/No</button> (Ashby).
    # O checkbox hidden dessas perguntas chega ao _collect_custom_fields com
    # label "Yes\nNo" (sem o texto da pergunta), por isso não são resolvidas
    # no bloco 4. Aqui mapeamos pelo question-title do field-entry pai.
    yesno_groups = _collect_yesno_questions(page)
    for g in yesno_groups:
        question = g.get("question", "") or ""
        gname = g.get("name", "")
        greq = g.get("required", False)
        if not question or not gname:
            continue
        rule = classify_field(question)
        if rule.blocked:
            if greq:
                result.blockers.append(question[:80])
            continue
        value = profile.get(rule.key or "") if rule.key else None
        if value in (None, ""):
            if greq:
                result.blockers.append(question[:80])
            continue
        ans = "Yes" if str(value).lower() in ("yes", "true", "sim", "1") else "No"
        if _click_yesno_button(page, gname, ans):
            result.filled.append(rule.key or question[:40])
        elif greq:
            result.blockers.append(question[:80])

    # 5. Consent checkbox
    try:
        page.locator("input[type=checkbox][id*='data_consent_ack']").first.check(force=True)
        result.filled.append("consent")
    except Exception:
        pass  # consent nem sempre presente

    # 6. Verificação pós-preenchimento: lê de volta o estado de cada campo e
    # compara com o esperado. Se algo não bate, vira blocker explícito. Isso
    # garante que não enviemos com opção errada/branca por preenchimento rápido.
    result = _verify_filled_state(page, profile, result)
    return result


def _verify_filled_state(page: Any, profile: dict, result: "FillResult") -> "FillResult":
    """Lê o estado real do form e confronta com o esperado.

    Adiciona blockers para:
    - campos obrigatórios ainda vazios;
    - radios/yes-no que o profile mandou preencher mas não estão selecionados.
    """
    expected = {
        "years_relevant_experience": str(profile.get("years_relevant_experience", "")),
        "english_proficiency": str(profile.get("english_proficiency", "")),
        "within_cet_range": str(profile.get("within_cet_range", "")),
    }
    # espera o React estabilizar após os cliques antes de ler o estado
    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass
    state = page.evaluate(r"""() => {
      const out = {radios:[], yesno:[], reqEmpty:[]};
      // radios checked
      document.querySelectorAll('input[type=radio]:checked').forEach(c => {
        const l = document.querySelector(`label[for="${c.id}"]`);
        out.radios.push(l ? (l.innerText||'').trim().toLowerCase() : '');
      });
      // yes/no ativo
      document.querySelectorAll('[class*="_yesno_"]').forEach(cont => {
        const btns = [...cont.querySelectorAll('button')];
        const active = btns.find(b => /_selected_|selected|active/.test(b.className) || b.getAttribute('aria-pressed')==='true');
        out.yesno.push(active ? (active.innerText||'').trim().toLowerCase() : '');
      });
      // required empty (exclui file e hidden)
      out.reqEmpty = [...document.querySelectorAll('input[required],textarea[required]')]
        .filter(e => !e.value && e.type !== 'file' && e.type !== 'hidden')
        .map(e => e.id || e.name);
      return out;
    }""")

    # radios: years e english devem estar checked com label casando
    if expected["years_relevant_experience"]:
        if not any(expected["years_relevant_experience"].lower() in r for r in state["radios"]):
            result.blockers.append("years_relevant_experience: radio não selecionado")
    if expected["english_proficiency"]:
        if not any(expected["english_proficiency"].lower() in r for r in state["radios"]):
            result.blockers.append("english_proficiency: radio não selecionado")
    # yes/no cet
    if expected["within_cet_range"]:
        want_yes = expected["within_cet_range"].lower() in ("yes", "true", "sim", "1")
        if want_yes and "yes" not in state["yesno"]:
            result.blockers.append("within_cet_range: Yes não selecionado")
        if (not want_yes) and "no" not in state["yesno"]:
            result.blockers.append("within_cet_range: No não selecionado")
    # required empty
    for fid in state["reqEmpty"]:
        result.blockers.append(f"campo obrigatório vazio: {fid}")
    return result
