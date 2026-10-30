from career.claim_check import check_claims, ClaimCheckResult, CLAIM_LABELS


def test_basic_labels():
    text = "I am an expert in Excel. We reduced costs by 30%."
    profile = ["Excel basic", "Reduced costs by 30% in 2023"]
    result = check_claims(text, profile)
    assert isinstance(result, ClaimCheckResult)
    assert len(result.claims) == 2
    labels = [c.label for c in result.claims]
    assert "inflated" in labels
    assert "supported" in labels
    assert set(CLAIM_LABELS) >= set(labels)


def test_json_output():
    result = check_claims("Hello world.", [])
    data = result.to_dict()
    assert "claims" in data
    assert result.to_json()


def test_no_facts():
    result = check_claims("We have 100000 users.", None)
    assert result.claims[0].label in ("invented", "unverifiable")
