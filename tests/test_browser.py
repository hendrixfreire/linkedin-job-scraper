from pathlib import Path

from playwright.sync_api import sync_playwright

from candidatura_agent.browser import fill_known_fields, has_submission_confirmation, run_application


def test_fill_known_fields_blocks_sensitive_required_question(tmp_path: Path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF")
    fixture = Path(__file__).parent / "fixtures" / "generic_form.html"
    profile = {
        "full_name": "Test Person", "email": "test@example.com",
        "phone": "+55 11 90000-0000", "resume": str(resume),
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(fixture.as_uri())
        result = fill_known_fields(page, profile)
        assert page.locator('input[name="name"]').input_value() == "Test Person"
        assert page.locator('input[name="email"]').input_value() == "test@example.com"
        assert page.locator('input[name="resume"]').evaluate("el => el.files.length") == 1
        assert "salary" in " ".join(result.blockers).lower()
        assert result.can_submit is False
        browser.close()


def test_fill_known_fields_survives_field_removed_during_react_rerender():
    html = """
    <label for="email">Email</label><input id="email" name="email" required>
    <textarea id="captcha" name="g-recaptcha-response" style="display:none"></textarea>
    <script>
      document.querySelector('#email').addEventListener('input', () => {
        document.querySelector('#captcha')?.remove();
      });
    </script>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(500)
        page.set_content(html)

        result = fill_known_fields(page, {"email": "test@example.com"})

        assert page.locator("#email").input_value() == "test@example.com"
        assert result.blockers == []
        browser.close()


def test_fill_known_fields_identifies_resume_by_input_id(tmp_path: Path):
    resume = tmp_path / "tailored.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF")
    html = '<label for="resume">Attach</label><input id="resume" type="file">'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"resume": str(resume)})

        assert page.locator("#resume").evaluate("el => el.files.length") == 1
        assert "resume" in result.filled
        browser.close()


def test_fill_known_fields_selects_custom_combobox_and_checkbox_group():
    html = """
    <label for="english">What is your English proficiency level?</label>
    <input id="english" role="combobox" aria-autocomplete="list" required>
    <div id="options" hidden><div role="option">Advanced</div><div role="option">Basic</div></div>
    <label><input type="checkbox" name="conflict[]" required>I have nothing to declare.</label>
    <label><input type="checkbox" name="conflict[]" required>I own a competing business.</label>
    <script>
      const field = document.querySelector('#english');
      field.addEventListener('click', () => options.hidden = false);
      options.addEventListener('click', event => {
        field.value = event.target.textContent;
        options.hidden = true;
      });
    </script>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {
            "english_proficiency": "Advanced",
            "conflict_nothing_to_declare": True,
        })

        assert page.locator("#english").input_value() == "Advanced"
        assert page.locator('input[name="conflict[]"]').first.is_checked()
        assert result.blockers == []
        browser.close()


def test_file_is_uploaded_after_combobox_rerenders_form(tmp_path: Path):
    resume = tmp_path / "tailored.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF")
    html = """
    <label for="resume">Resume</label><input id="resume" type="file">
    <label for="country">Country</label>
    <input id="country" role="combobox" aria-autocomplete="list" required>
    <script>
      const country = document.querySelector('#country');
      country.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
          const oldResume = document.querySelector('#resume');
          oldResume.outerHTML = oldResume.outerHTML;
        }
      });
    </script>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        fill_known_fields(page, {"country": "Brazil", "resume": str(resume)})

        assert page.locator("#resume").evaluate("el => el.files.length") == 1
        browser.close()


def test_unaddressable_required_proxy_input_is_not_a_blocker():
    """O Greenhouse cria um input required sem id/name/rótulo por combobox.

    Ele existe só para disparar a validação nativa; o campo real é o combobox ao
    lado. Tratá-lo como pergunta gerava um bloqueio falso por combobox do formulário.
    """
    html = """
    <label for="email">Email</label><input id="email" required>
    <input type="text" required class="remix-css-requiredInput">
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"email": "test@example.com"})

        assert result.blockers == []
        browser.close()


def test_required_field_with_name_but_no_label_still_blocks():
    """Um campo endereçável e sem resposta continua bloqueando."""
    html = '<input type="text" name="cpf_do_responsavel" required>'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {})

        assert len(result.blockers) == 1
        browser.close()


def test_portuguese_name_fields_are_recognized():
    html = """
    <label for="nome">Nome</label><input id="nome" name="first_name" required>
    <label for="sobrenome">Sobrenome</label><input id="sobrenome" name="last_name" required>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"first_name": "Hendrix", "last_name": "Freire"})

        assert page.locator("#nome").input_value() == "Hendrix"
        assert page.locator("#sobrenome").input_value() == "Freire"
        assert result.blockers == []
        browser.close()


def test_select_matches_option_that_only_differs_in_wording():
    """O perfil diz "Brazil"; o formulário oferece "Brazil (Brasil)"."""
    html = """
    <label for="country">Country</label>
    <select id="country" required>
      <option value="">Select…</option>
      <option>Brazil (Brasil)</option>
      <option>Portugal</option>
    </select>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"country": "Brazil"})

        assert page.locator("#country").input_value() == "Brazil (Brasil)"
        assert result.blockers == []
        browser.close()


def test_select_refuses_to_guess_between_ambiguous_options():
    html = """
    <label for="country">Country</label>
    <select id="country" required>
      <option value="">Select…</option>
      <option>Brazil (Brasil)</option>
      <option>Brazil — remote only</option>
    </select>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"country": "Brazil"})

        assert page.locator("#country").input_value() == ""
        assert len(result.blockers) == 1
        assert "ambígua" in result.blockers[0]
        browser.close()


def test_select_blocks_when_no_option_matches():
    html = """
    <label for="country">Country</label>
    <select id="country" required>
      <option value="">Select…</option>
      <option>Portugal</option>
    </select>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"country": "Brazil"})

        assert len(result.blockers) == 1
        assert "opção aprovada não encontrada" in result.blockers[0]
        browser.close()


def test_radio_group_is_answered_by_option_label():
    """Perguntas de sim/não do Greenhouse são grupos de radio, não booleanos."""
    html = """
    <fieldset>
      <legend>Você trabalha atualmente no Inter?</legend>
      <label><input type="radio" name="q_inter" value="1" required> Sim</label>
      <label><input type="radio" name="q_inter" value="0" required> Não</label>
    </fieldset>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"worked_at_hiring_company": "Não"})

        assert page.locator('input[name="q_inter"][value="0"]').is_checked()
        assert page.locator('input[name="q_inter"][value="1"]').is_checked() is False
        assert result.blockers == []
        browser.close()


def test_consent_checkbox_is_checked_by_boolean_answer():
    html = """
    <label>
      <input type="checkbox" name="lgpd" required>
      Concordo com a Política de Privacidade
    </label>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"privacy_consent": True})

        assert page.locator('input[name="lgpd"]').is_checked()
        assert result.blockers == []
        browser.close()


def test_consent_checkbox_accepts_alternative_wordings():
    """Cada ATS redige o aceite de forma diferente; a resposta aprovada é a mesma."""
    html = """
    <label>
      <input type="checkbox" name="lgpd" required>
      Concordo que os dados pessoais serão tratados conforme a Política de Privacidade
    </label>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"privacy_consent": ["De acordo", "Concordo", "Yes"]})

        assert page.locator('input[name="lgpd"]').is_checked()
        assert result.blockers == []
        browser.close()


def test_run_application_requires_visible_submission_confirmation(tmp_path: Path):
    confirmed = tmp_path / "confirmed.html"
    confirmed.write_text("""
    <label for="email">Email</label><input id="email" required>
    <button onclick="document.body.innerHTML='<h1>Thank you for applying</h1>'">Submit application</button>
    """)
    unconfirmed = tmp_path / "unconfirmed.html"
    unconfirmed.write_text("""
    <label for="email">Email</label><input id="email" required>
    <button onclick="document.body.innerHTML='<h1>Processing</h1>'">Submit application</button>
    """)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        ok = run_application(
            page, confirmed.as_uri(), {"email": "test@example.com"}, auto_submit=True,
            allowed_ats={"generic"}, screenshot_dir=tmp_path / "shots-ok",
        )
        uncertain = run_application(
            page, unconfirmed.as_uri(), {"email": "test@example.com"}, auto_submit=True,
            allowed_ats={"generic"}, screenshot_dir=tmp_path / "shots-uncertain",
        )
        assert ok.status == "submitted"
        assert ok.screenshot and ok.screenshot.endswith("last-application-post-submit.png")
        assert Path(ok.screenshot).exists()
        assert uncertain.status == "blocked"
        assert uncertain.screenshot and uncertain.screenshot.endswith("last-application-post-submit.png")
        assert uncertain.blockers == ["envio sem confirmação verificável"]
        browser.close()


def test_combobox_that_selects_nothing_becomes_a_blocker():
    """fill + Enter num combobox pode não selecionar nada e ficava silencioso.

    O formulário do C6 foi recusado com quatro campos obrigatórios em branco que o
    agente havia dado como preenchidos.
    """
    html = """
    <label for="race">Você se identifica com qual raça e/ou cor?</label>
    <div><input id="race" role="combobox" aria-autocomplete="list" required>
    <div id="opts"><div role="option">Amarela</div><div role="option">Indígena</div></div></div>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"race_ethnicity": "Branco: fenótipo europeu"})

        assert page.locator("#race").input_value() == ""
        assert len(result.blockers) == 1
        assert "opção aprovada não encontrada" in result.blockers[0]
        browser.close()


def test_typed_text_with_the_list_still_open_is_not_a_selection():
    """react-select mantém o texto digitado quando nada casa e o descarta no blur.

    Ler esse texto como sucesso fez o formulário do C6 ser dado como completo com
    o campo de raça/cor em branco.
    """
    html = """
    <label for="race">Você se identifica com qual raça e/ou cor?</label>
    <div><input id="race" role="combobox" aria-autocomplete="list" required>
    <div id="opts"><div role="option">Amarela</div><div role="option">Preta</div></div></div>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"race_ethnicity": ["Branca", "Branco"]})

        assert page.locator("#race").input_value() == ""
        assert len(result.blockers) == 1
        assert "opção aprovada não encontrada" in result.blockers[0]
        browser.close()


def test_combobox_tries_each_approved_wording():
    """A pergunta vem em português e as opções em inglês (caso real do C6 Bank)."""
    html = """
    <label for="worked">Você trabalha no C6 Bank?</label>
    <div><input id="worked" role="combobox" aria-autocomplete="list" required>
    <div id="opts"><div role="option">Yes</div><div role="option">No</div></div></div>
    <script>
      const opts = document.querySelector('#opts');
      opts.addEventListener('click', event => {
        document.querySelector('#worked').value = event.target.textContent;
        opts.hidden = true;
      });
    </script>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"worked_at_hiring_company": ["Não", "No"]})

        assert page.locator("#worked").input_value() == "No"
        assert result.blockers == []
        browser.close()


def test_combobox_selection_shown_outside_the_input_is_accepted():
    """react-select mostra o escolhido num chip e esvazia o input; isso é sucesso."""
    html = """
    <label for="worked">Você trabalha no C6 Bank?</label>
    <div id="wrap"><input id="worked" role="combobox" aria-autocomplete="list" required>
    <div id="opts"><div role="option">Sim</div><div role="option">Não</div></div></div>
    <script>
      const field = document.querySelector('#worked');
      field.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
          field.value = '';
          const chip = document.createElement('span');
          chip.textContent = 'Não';
          document.querySelector('#wrap').prepend(chip);
        }
      });
    </script>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)

        result = fill_known_fields(page, {"worked_at_hiring_company": "Não"})

        assert result.blockers == []
        browser.close()


def test_anchor_button_does_not_make_the_real_submit_ambiguous(tmp_path: Path):
    """Greenhouse em PT tem "Candidate-se" (âncora) e "Enviar inscrição" (envio).

    Ambos casam o padrão de nome; só o segundo é type=submit.
    """
    form = tmp_path / "two-buttons.html"
    form.write_text("""
    <label for="email">Email</label><input id="email" required>
    <button type="button" aria-label="Apply for this job">Candidate-se</button>
    <button type="submit"
      onclick="document.body.innerHTML='<h1>Candidatura enviada</h1>'">Enviar inscrição</button>
    """)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        result = run_application(
            page, form.as_uri(), {"email": "test@example.com"}, auto_submit=True,
            allowed_ats={"generic"}, screenshot_dir=tmp_path / "shots",
        )

        assert result.status == "submitted"
        browser.close()


def test_two_real_submit_buttons_still_block(tmp_path: Path):
    form = tmp_path / "ambiguous.html"
    form.write_text("""
    <label for="email">Email</label><input id="email" required>
    <button type="submit">Enviar inscrição</button>
    <button type="submit">Submit application</button>
    """)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        result = run_application(
            page, form.as_uri(), {"email": "test@example.com"}, auto_submit=True,
            allowed_ats={"generic"}, screenshot_dir=tmp_path / "shots",
        )

        assert result.status == "blocked"
        assert result.blockers == ["botão de envio ambíguo"]
        browser.close()


def test_waits_for_a_form_that_mounts_after_load(tmp_path: Path):
    """Formulários React montam depois do domcontentloaded.

    Avaliar cedo demais fazia a página aparecer sem as perguntas: poucos campos,
    nenhum bloqueio, vaga dada como pronta com obrigatórios em branco.
    """
    late = tmp_path / "late.html"
    late.write_text("""
    <div id="root"></div>
    <script>
      setTimeout(() => {
        document.querySelector('#root').innerHTML =
          '<label for="email">Email</label><input id="email" required>' +
          '<input id="cpf" name="cpf" aria-label="CPF" required>';
      }, 1200);
    </script>
    """)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        result = run_application(
            page, late.as_uri(), {"email": "test@example.com"}, auto_submit=False,
            allowed_ats={"generic"}, screenshot_dir=tmp_path / "shots",
        )

        assert page.locator("#email").input_value() == "test@example.com"
        assert result.blockers == ["CPF cpf cpf"]
        browser.close()


def test_page_without_an_application_form_is_never_ready_to_submit(tmp_path: Path):
    """Vaga removida devolve uma página sem campos — zero campos obrigatórios.

    Sem esta trava, "nenhum bloqueio" era lido como "formulário completo": páginas
    de erro do Greenhouse e vagas expiradas apareciam prontas para envio.
    """
    dead = tmp_path / "dead.html"
    dead.write_text("<h1>This job is no longer available</h1>")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        result = run_application(
            page, dead.as_uri(), {"email": "test@example.com"}, auto_submit=True,
            allowed_ats={"generic"}, screenshot_dir=tmp_path / "shots",
        )

        assert result.status == "blocked"
        assert result.blockers == ["formulário de candidatura não encontrado"]
        browser.close()


def test_peopleforce_success_phrase_is_recognized():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<main>Application was submitted successfully.</main>")
        assert has_submission_confirmation(page) is True
        page.set_content("""
            <form>
              <div contenteditable="true">Thank you for applying</div>
              <input type="file" name="resume">
              <button type="submit">Apply</button>
            </form>
        """)
        assert has_submission_confirmation(page) is False
        browser.close()
