from candidatura_agent.adapters import detect_ats, classify_field


def test_detects_supported_ats_domains():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/job") == "workday"
    assert detect_ats("https://portal.gupy.io/job/123") == "gupy"
    assert detect_ats("https://dadoteca.factorialhr.com.br/job_posting/123") == "factorial"


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


def test_approved_ifood_greenhouse_questions_map_to_explicit_profile_answers():
    assert classify_field("Nome* Nome first_name").key == "first_name"
    assert classify_field("Sobrenome* Sobrenome last_name").key == "last_name"
    assert classify_field("Empresa Atual / Última Empresa*").key == "last_employer"
    assert classify_field("Cargo Atual / Último Cargo*").key == "last_job_title"
    assert classify_field("Quais são os seus pronomes?*").key == "pronouns"
    assert classify_field("Você já trabalhou no iFood?*").key == "worked_at_ifood"
    assert classify_field("Com qual gênero você se identifica?*").key == "gender_identity"
    assert classify_field("Qual é sua cor ou raça?*").key == "race_ethnicity"
    assert classify_field("Se você é uma pessoa com deficiência, nos informe qual é sua deficiência:*").key == "disability_details"
    assert classify_field("Você é uma pessoa com deficiência?*").key == "person_with_disability"
    assert classify_field("Você aceita o Aviso de Diversidade – D&I?*").key == "demographic_consent_answer"
    assert classify_field("País*").key == "greenhouse_phone_country"
    assert classify_field("Localização (Cidade)*").key == "greenhouse_location"
    assert classify_field("Qual é a sua pretensão salarial?*").key == "greenhouse_salary_expectation"
    assert classify_field("Name Type here...").key == "full_name"
    assert classify_field("What is your availability to start a new role?").key == "availability_to_start"
    assert classify_field("What is your expected monthly gross wage in euros (€)?").key == "expected_monthly_gross_eur"
    assert classify_field("Qual sua pretensão salarial PJ?").key == "pj_salary_expectation"
    assert classify_field("Qual a sua disponibilidade (em dias) para iniciar?").key == "start_availability_days"
    assert classify_field("Atualmente você está atuando em algum projeto?").key == "current_project_contract_type"
    assert classify_field("Possui certificações? Quais?").key == "certifications"
    assert classify_field("Nome * first_name").key == "first_name"
    assert classify_field("Sobrenome * last_name").key == "last_name"
    assert classify_field("URL pessoal *").key == "linkedin"
