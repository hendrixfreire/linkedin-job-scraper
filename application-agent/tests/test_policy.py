from candidatura_agent.policy import assess_job, decide_submission


PROFILE = {
    "target_titles": ["data engineer", "analytics engineer", "bi manager", "data analytics manager"],
    "preferred_skills": ["python", "sql", "bigquery", "gcp", "lakehouse", "analytics"],
    "blocked_title_terms": ["junior", "júnior", "intern", "trainee"],
    "allowed_locations": ["brazil", "brasil", "são paulo", "sao paulo"],
    "min_fit_score": 70,
    "daily_target_min": 10,
}


def test_assess_job_explains_strong_match():
    result = assess_job({
        "title": "Senior Analytics Engineer",
        "location": "Brazil",
        "description": "Python SQL BigQuery GCP lakehouse",
        "heuristic_score": 5,
    }, PROFILE)
    assert result.score >= 70
    assert result.eligible is True
    assert result.reasons


def test_existing_scraper_score_is_preserved_when_description_is_sparse():
    result = assess_job({
        "title": "Staff Data Engineer", "location": "Brazil",
        "description": "", "fit_score": 100,
    }, PROFILE)
    assert result.eligible is True
    assert result.score >= 70


def test_assess_job_hard_rejects_junior():
    result = assess_job({"title": "Junior Data Engineer", "location": "Brazil", "description": "Python SQL"}, PROFILE)
    assert result.eligible is False
    assert "senioridade" in result.blockers


def test_feedback_can_tune_but_not_override_hard_filter():
    result = assess_job(
        {"title": "Junior Data Engineer", "location": "Brazil", "description": "Python SQL"},
        PROFILE,
        learned_weights={"data engineer": 50},
    )
    assert result.eligible is False


def test_submission_requires_all_guards():
    allowed = decide_submission(
        fit_score=85, min_fit_score=70, auto_submit=True,
        ats="greenhouse", allowed_ats={"greenhouse", "lever"}, blockers=[]
    )
    blocked = decide_submission(
        fit_score=85, min_fit_score=70, auto_submit=True,
        ats="greenhouse", allowed_ats={"greenhouse"}, blockers=["salary"]
    )
    assert allowed.action == "submit"
    assert blocked.action == "pause"
