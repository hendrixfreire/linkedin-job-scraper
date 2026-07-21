from pathlib import Path

from playwright.sync_api import sync_playwright

from candidatura_agent.browser import _matching_option_index, fill_known_fields, has_submission_confirmation, run_application


def test_matching_option_index_requires_an_exact_normalized_choice():
    options = ["Pardo", "Branco", "Não quero responder"]
    assert _matching_option_index(options, "branco") == 1
    assert _matching_option_index(options, "Branca") is None


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
    <div id="options" hidden><div role="option">Advanced</div></div>
    <label><input type="checkbox" name="conflict[]" required>I have nothing to declare.</label>
    <label><input type="checkbox" name="conflict[]" required>I own a competing business.</label>
    <script>
      const field = document.querySelector('#english');
      field.addEventListener('focus', () => options.hidden = false);
      // React Select-like: clicking an option sets the value
      document.querySelector('[role="option"]').addEventListener('click', () => {
        field.value = 'Advanced';
        options.hidden = true;
      });
      // Also support keyboard Enter for accessibility
      field.addEventListener('keydown', event => {
        if (event.key === 'Enter') { field.value = 'Advanced'; options.hidden = true; }
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


def test_run_application_requires_visible_submission_confirmation(tmp_path: Path):
    confirmed = tmp_path / "confirmed.html"
    confirmed.write_text("""
    <button type="button">Apply</button>
    <label for="email">Email</label><input id="email" required>
    <button type="submit" onclick="document.body.innerHTML='<h1>Thank you for applying</h1>'">Submit application</button>
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


def test_ashby_submit_button_selector_matches_without_type_submit(tmp_path: Path):
    """Ashby renderiza o botão de envio sem type=submit, usando classe própria.

    Simula o DOM real (button.ashby-application-form-submit-button com span
    "Submit Application") e garante que o dry-run não bloqueia por
    "botão de envio ambíguo".
    """
    from candidatura_agent.adapters import detect_ats

    html = """
    <input type='email' id='_systemfield_email'>
    <input type='text' id='_systemfield_name'>
    <button class='ashby-application-form-submit-button'><span>Submit Application</span></button>
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        # seletor estável pela classe deve casar exatamente 1
        submit = page.locator("button.ashby-application-form-submit-button")
        assert submit.count() == 1
        assert "Submit Application" in submit.inner_text()
        browser.close()
