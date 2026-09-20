from scripts.diagnose_macro_repeatability import diagnose


def test_repeatability_diagnostic_reports_distribution_and_shape():
    artifact = {"record_id": "r", "verdict": "BLOCK", "results": {"repeatability": {
        "XOM": {"rate_sensitivity": {"n": 5, "mean": 4.2, "stdev": 0.45,
                                        "values": [4, 4, 4, 5, 4], "range": 1}},
        "DSGX": {"geopolitical_risk": {"n": 5, "mean": 4.0, "stdev": 1.0,
                                         "values": [2, 4, 2, 5, 3], "range": 3}},
    }}}
    result = diagnose(artifact)
    assert result["range_distribution"] == {"1": 1, "3+": 1}
    assert result["range_le_1_count"] == 1
    assert result["cells"][0]["mode_fraction"] == 0.8
    assert result["cells"][1]["entropy_bits"] > result["cells"][0]["entropy_bits"]
