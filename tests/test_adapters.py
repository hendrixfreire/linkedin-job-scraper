from candidatura_agent.adapters import build_answer_book, detect_ats, classify_field


def test_detects_supported_ats_domains():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/job") == "workday"
    assert detect_ats("https://portal.gupy.io/job/123") == "gupy"
    assert detect_ats("https://dadoteca.factorialhr.com.br/job_posting/123") == "factorial"


def test_detect_ats_is_not_fooled_by_lookalike_hosts():
    """detect_ats alimenta a checagem de ATS liberado imediatamente antes do envio."""
    assert detect_ats("https://evil-greenhouse.io.attacker.com/apply") == "generic"
    assert detect_ats("https://greenhouse.io.example.com/apply") == "generic"
    assert detect_ats("https://notgreenhouse.io/apply") == "generic"


def test_sensitive_or_unknown_fields_block():
    assert classify_field("What is your salary expectation?").blocked is True
    assert classify_field("Do you have a disability?").blocked is True
    assert classify_field("Full name").key == "full_name"
    assert classify_field("A philosophical essay about our culture").blocked is True


def test_exact_approved_greenhouse_questions_map_to_profile_keys():
    assert classify_field("What is your current base salary? (in reais)").key == "current_base_salary_answer"
    assert classify_field("What is your expected base salary for this role? (in reais)").key == "expected_base_salary_answer"
    assert classify_field("I have nothing to declare.").key == "conflict_nothing_to_declare"
    assert classify_field("How did you hear about this opportunity?").key == "application_source"


def test_sensitive_question_with_approved_answer_is_filled():
    """Pergunta sensível deixa de bloquear quando o perfil já traz a resposta."""
    book = build_answer_book({
        "gender_identity": "Homem cisgênero",
        "cpf": "34442157898",
        "person_with_disability": "Não",
    })

    gender = classify_field("Qual a sua identidade de gênero?*", book)
    assert gender.blocked is False
    assert gender.value == "Homem cisgênero"

    cpf = classify_field("CPF* CPF question_8892693005", book)
    assert cpf.value == "34442157898"

    pcd = classify_field("Person with a disability (PCD - Pessoa com Deficiência)?*", book)
    assert pcd.value == "Não"


def test_sensitive_question_without_answer_still_blocks():
    book = build_answer_book({"cpf": "34442157898"})
    assert classify_field("Qual a sua identidade de gênero?*", book).blocked is True
    assert classify_field("Qual sua orientação sexual?*", book).blocked is True


def test_unknown_question_still_blocks_even_with_answer_book():
    book = build_answer_book({"cpf": "34442157898"})
    unknown = classify_field(
        "How many years of experience do you have with dimensional and medallion data modeling?*",
        book,
    )
    assert unknown.blocked is True


def test_free_form_question_answers_take_precedence():
    """O usuário resolve perguntas novas pelo profile.json, sem alterar código."""
    book = build_answer_book({
        "english_proficiency": "Advanced",
        "question_answers": {
            "How many years of experience do you have with dimensional and medallion data modeling?": "7-10",
            "What is your English proficiency level?": "Avançado",
        },
    })

    assert classify_field(
        "How many years of experience do you have with dimensional and medallion data modeling?*",
        book,
    ).value == "7-10"
    assert classify_field("What is your English proficiency level?", book).value == "Avançado"


def test_recurring_greenhouse_answers_are_consulted():
    book = build_answer_book({
        "greenhouse_recurring_answers": {
            "english_level": "Avançado",
            "spanish_level": "Básico",
            "work_authorization": "Yes",
        },
    })

    assert classify_field("Qual seu nível de fluência na língua inglesa?*", book).value == "Avançado"
    assert classify_field("Qual o seu nível de fluência na língua espanhola?*", book).value == "Básico"
    assert classify_field(
        "Are you authorized to work in the stated location of this role?*", book,
    ).value == "Yes"


def test_company_specific_questions_map_to_profile_defaults():
    book = build_answer_book({
        "worked_at_hiring_company": "Não",
        "referred_by_employee": "Não",
        "relative_at_hiring_company": "Não",
        "application_source": "LinkedIn",
    })

    assert classify_field("Você trabalha atualmente no Inter?*", book).value == "Não"
    assert classify_field("Você já trabalhou em algum momento no C6 Bank?*", book).value == "Não"
    assert classify_field("Are you a currently Group ABInBev | Ambev employee?*", book).value == "Não"
    assert classify_field("Você é uma pessoa indicada por algum CSixer?*", book).value == "Não"
    assert classify_field("Você possui grau de parentesco com algum de nossos CSixer?*", book).value == "Não"
    assert classify_field("How did you hear about us?*", book).value == "LinkedIn"


def test_relocation_question_is_not_answered_as_employment_history():
    """Padrão de vínculo empregatício não pode vazar para pergunta de mudança de cidade."""
    book = build_answer_book({"worked_at_hiring_company": "Não"})

    relocation = classify_field(
        "Do you currently live in, or plan to relocate to, the specified location "
        "to meet this in-office requirement?*",
        book,
    )
    assert relocation.blocked is True

    previous_employer = classify_field(
        "Do you currently, or have you previously, worked at Capital One "
        "or a company acquired by Capital One?*",
        book,
    )
    assert previous_employer.value == "Não"


def test_answers_already_present_in_the_profile_are_reachable():
    """Respostas existiam no perfil e mesmo assim bloqueavam por falta de mapeamento."""
    book = build_answer_book({
        "start_availability": "Imediata",
        "expected_monthly_gross_eur": "2223",
    })

    assert classify_field("What is your availability to start a new role?", book).value == "Imediata"
    assert classify_field(
        "What is your expected monthly gross wage in euros (€) for this position?", book,
    ).value == "2223"


def test_answer_may_offer_alternative_wordings():
    """"Prefiro não responder" muda de redação a cada formulário."""
    from candidatura_agent.adapters import match_choice

    alternatives = ["Prefiro não responder", "Não quero responder", "Prefer not to say"]
    assert match_choice(alternatives, ["Homem", "Mulher", "Não quero responder"]) == (2, "ok")
    assert match_choice(alternatives, ["Man", "Woman", "Prefer not to say"]) == (2, "ok")
    assert match_choice(alternatives, ["Homem", "Mulher"]) == (None, "missing")


def test_longer_pattern_wins_over_shorter_one():
    book = build_answer_book({
        "current_base_salary_answer": "BRL 12,000",
        "expected_base_salary_answer": "BRL 10,000",
    })
    assert classify_field("Informe seu salário atual/último:*", book).value == "BRL 12,000"
