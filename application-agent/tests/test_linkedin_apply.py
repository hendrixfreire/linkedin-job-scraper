from candidatura_agent.linkedin_apply import select_offsite_apply_url


def test_selects_only_external_apply_action():
    anchors = [
        {"href": "https://www.linkedin.com/company/example", "text": "Company"},
        {"href": "https://tracker.example/privacy", "text": "Privacy"},
        {"href": "https://jobs.example.test/apply/42", "text": "Apply now"},
    ]

    assert select_offsite_apply_url(anchors) == "https://jobs.example.test/apply/42"


def test_accepts_data_url_payload_and_rejects_non_https():
    anchors = [
        {"url": "http://jobs.example.test/1", "text": "Apply"},
        {"url": "https://jobs.example.test/2", "text": "Aplicar"},
    ]

    assert select_offsite_apply_url(anchors) == "https://jobs.example.test/2"
