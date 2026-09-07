def test_deliberately_fails_with_a_long_message():
    padding = "x" * 600
    reason = "".join(["REAL", "_", "REASON", "_", "AT", "_", "THE", "_", "END"])
    assert False, padding + reason
