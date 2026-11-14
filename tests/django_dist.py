"""A fake pytest-django distribution for tests that run a real pytest."""

from pathlib import Path


def django_dist(root: Path) -> Path:
    """Put on PYTHONPATH, a real pytest registers it as the pytest-django
    plugin: the module plus dist-info with its pytest11 entry point."""
    (root / "pytest_django").mkdir(parents=True)
    (root / "pytest_django" / "__init__.py").write_text("")
    info = root / "pytest_django-4.9.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pytest-django\nVersion: 4.9.0\n"
    )
    (info / "entry_points.txt").write_text("[pytest11]\ndjango = pytest_django\n")
    return root
