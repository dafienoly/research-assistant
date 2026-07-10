from factor_lab.vnext.review import AntifragileReviewEngine


def test_review_produces_auditable_training_sample():
    event = {name: 0.8 for name in AntifragileReviewEngine.DIMENSIONS}
    event["return"] = 0.02
    result = AntifragileReviewEngine().review(event, as_of="2026-07-10")
    assert result["decision"] in {"KEEP", "TUNE", "DOWNGRADE", "RETIRE", "ESCALATE", "WATCH"}
    assert result["structured_training_sample"]["outcome_return"] == 0.02
