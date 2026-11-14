from core.adapter_contract import default_recreate_db_args


def adapter_with_script(tmp_path, body):
    run = tmp_path / "run.sh"
    run.write_text("#!/bin/sh\n")
    run.chmod(0o755)
    if body is not None:
        script = tmp_path / "recreate-db.sh"
        script.write_text(body)
        script.chmod(0o755)
    return str(run)


def test_the_sibling_recreate_db_script_supplies_the_default_args(tmp_path):
    adapter = adapter_with_script(
        tmp_path,
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "print(json.dumps({'args': '--create-db ' + sys.argv[1]}))\n",
    )

    assert default_recreate_db_args(adapter, "/root") == "--create-db /root"


def test_no_default_when_the_script_is_missing_fails_or_declines(tmp_path):
    assert default_recreate_db_args(adapter_with_script(tmp_path, None), "/r") is None
    for body in (
        "#!/bin/sh\nexit 1\n",
        "#!/bin/sh\necho not-json\n",
        "#!/bin/sh\necho '{\"args\": null}'\n",
        "#!/bin/sh\necho '{\"args\": \"  \"}'\n",
        "#!/bin/sh\necho '{\"args\": 3}'\n",
        "#!/bin/sh\necho '[1]'\n",
    ):
        adapter = adapter_with_script(tmp_path, body)
        assert default_recreate_db_args(adapter, "/r") is None, body


def test_a_hanging_script_gives_no_default(tmp_path):
    adapter = adapter_with_script(tmp_path, "#!/bin/sh\nsleep 30\n")

    assert default_recreate_db_args(adapter, "/r", timeout_s=1) is None
