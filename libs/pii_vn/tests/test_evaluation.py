from ben_pii_vn.evaluation import evaluate


def test_synthetic_pii_evaluation_has_500_samples_and_no_redaction_leakage():
    report = evaluate()
    assert report["samples"] == 500
    assert report["raw_pii_after_redact"] == []
    for metric in report["metrics"].values():
        assert metric["recall"] == 1.0
