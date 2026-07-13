from candidatura_agent.adapters import detect_ats, classify_field


def test_detects_supported_ats_domains():
    assert detect_ats("https://boards.greenhouse.io/acme/jobs/123") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/job") == "workday"
    assert detect_ats("https://portal.gupy.io/job/123") == "gupy"


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
