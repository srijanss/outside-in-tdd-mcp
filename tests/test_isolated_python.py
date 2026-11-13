import os
import subprocess
import sysconfig

from tests.isolated_python import isolated_python


def test_the_isolated_python_does_not_see_this_runs_site_packages(tmp_path):
    python = isolated_python(tmp_path / "venv")

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    sys_path = subprocess.run(
        [str(python), "-c", "import sys; print('\\n'.join(sys.path))"],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.splitlines()

    assert python == tmp_path / "venv" / "bin" / "python"
    assert sysconfig.get_path("purelib") not in sys_path
