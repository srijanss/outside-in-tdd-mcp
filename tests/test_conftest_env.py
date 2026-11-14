import os


def test_no_tdd_env_var_is_visible_inside_a_test():
    leaked = sorted(name for name in os.environ if name.startswith("TDD_"))
    assert leaked == []


def test_a_test_can_still_set_its_own_tdd_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("TDD_FEATURES_PATH", str(tmp_path / "f.json"))
    assert os.environ["TDD_FEATURES_PATH"] == str(tmp_path / "f.json")
