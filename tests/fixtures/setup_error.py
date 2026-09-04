import pytest


@pytest.fixture
def broken_fixture():
    raise RuntimeError("fixture setup blew up")


def test_uses_broken_fixture(broken_fixture):
    assert True
