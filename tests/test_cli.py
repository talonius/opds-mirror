import logging
import subprocess
import sys

import pytest

from opds_mirror import cli
from opds_mirror.lock import AlreadyRunning, RunLock


@pytest.fixture(autouse=True)
def reset_logging():
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in before:
            root.removeHandler(handler)
            handler.close()


def write_config(tmp_path, base, extra=""):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'output_dir = "out"\n{extra}\n[[servers]]\nurl = "{base}/calibre/opds"\n')
    return cfg


def test_sync_quiet_with_log_file(opds_server, tmp_path, capsys):
    base, _ = opds_server
    cfg = write_config(tmp_path, base, 'log_file = "logs/mirror.log"')
    assert cli.main(["-q", "-c", str(cfg), "sync"]) == 0
    assert capsys.readouterr().err == ""  # quiet: nothing for cron to email
    log_text = (tmp_path / "logs" / "mirror.log").read_text()
    assert "downloaded" in log_text and "done:" in log_text
    assert (tmp_path / "out" / "Ann Other" / "CON_" / "CON_.mobi").exists()


def test_failures_give_exit_code_1(opds_server, tmp_path):
    base, _ = opds_server
    cfg = tmp_path / "config.toml"
    cfg.write_text('output_dir = "out"\ntimeout = 2\n[[servers]]\nurl = "http://127.0.0.1:1/opds"\n')
    import opds_mirror.http as http

    original = http.Client.__init__
    http.Client.__init__ = lambda self, *a, **k: original(self, *a, **{**k, "retries": 0})
    try:
        assert cli.main(["-q", "-c", str(cfg), "sync"]) == 1
    finally:
        http.Client.__init__ = original


def test_missing_config_exit_code_2(tmp_path, capsys):
    assert cli.main(["-c", str(tmp_path / "nope.toml"), "sync"]) == 2
    assert "config file not found" in capsys.readouterr().err


def test_second_run_exits_quietly_while_first_holds_lock(opds_server, tmp_path):
    base, handler = opds_server
    cfg = write_config(tmp_path, base)
    with RunLock(tmp_path / "out" / ".opds-mirror" / "lock"):
        assert cli.main(["-q", "-c", str(cfg), "sync"]) == 0
    assert handler.hits == []  # it didn't touch the server


def test_lock_is_exclusive_across_processes(tmp_path):
    lock_path = tmp_path / "lock"
    with RunLock(lock_path):
        code = (
            "import sys; from pathlib import Path; from opds_mirror.lock import RunLock, AlreadyRunning\n"
            "try:\n with RunLock(Path(sys.argv[1])): sys.exit(0)\n"
            "except AlreadyRunning: sys.exit(7)\n"
        )
        result = subprocess.run([sys.executable, "-c", code, str(lock_path)])
        assert result.returncode == 7
    with RunLock(lock_path):  # released, so it can be taken again
        pass


def test_lock_released_after_exception(tmp_path):
    lock_path = tmp_path / "lock"
    with pytest.raises(ZeroDivisionError):
        with RunLock(lock_path):
            1 / 0
    with RunLock(lock_path):
        with pytest.raises(AlreadyRunning):
            with RunLock(lock_path):
                pass
