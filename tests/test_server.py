import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from app import config
from scripts import server


def test_enter_and_stop_command_close_only_the_managed_server(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    root = Path(__file__).resolve().parent.parent
    env = {
        **os.environ,
        "SDR_DATA_DIR": str(tmp_path),
        "SDR_ACCESS_TOKEN": "",
        "PYTHONUTF8": "1",
    }
    command = [sys.executable, "scripts/server.py", "--no-browser"]
    for use_enter in (False, True):
        process = subprocess.Popen(
            command + ["run", "--port", str(port)],
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            for _ in range(150):
                assert process.poll() is None, "Managed server exited during startup"
                try:
                    if (
                        httpx.get(
                            f"http://127.0.0.1:{port}/api/config", timeout=0.5
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                raise AssertionError("Managed server did not become ready")
            duplicate = subprocess.run(
                command + ["run", "--port", str(port)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            assert duplicate.returncode == 1
            assert httpx.get(f"http://127.0.0.1:{port}/api/config").status_code == 200
            if use_enter:
                process.stdin.write("\n")
                process.stdin.flush()
            else:
                stopped = subprocess.run(
                    command + ["stop", "--port", str(port)],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=15,
                )
                assert stopped.returncode == 0, stopped.stdout
            process.wait(timeout=15)
            stdout, stderr = process.communicate(timeout=5)
            assert process.returncode == 0, stderr
            assert "项目已停止" in stdout and "Enter" in stdout
            assert "Press CTRL+C to quit" not in stderr
            assert not (tmp_path / "server-control" / f"{port}.json").exists()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    stopped_again = subprocess.run(
        command + ["stop", "--port", str(port)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert stopped_again.returncode == 0


def test_stop_does_not_terminate_an_unmanaged_listener(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert server.stop(port) == 1
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


def test_browser_waits_for_startup_and_opens_custom_port_once(monkeypatch):
    state = SimpleNamespace(started=False, should_exit=False)
    done = threading.Event()
    opened = threading.Event()
    urls = []

    def launch(url):
        urls.append(url)
        opened.set()
        return True

    monkeypatch.setattr(server.webbrowser, "open", launch)
    worker = threading.Thread(
        target=server.open_when_ready,
        args=(state, "http://127.0.0.1:9876", done),
    )
    worker.start()
    try:
        assert not opened.wait(0.25)
        state.started = True
        assert opened.wait(2)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert urls == ["http://127.0.0.1:9876"]
    finally:
        done.set()
        worker.join(timeout=2)


def test_browser_does_not_open_when_startup_exits(monkeypatch):
    def unexpected_open(url):
        pytest.fail("Browser must not open after startup exits")

    monkeypatch.setattr(server.webbrowser, "open", unexpected_open)
    server.open_when_ready(
        SimpleNamespace(started=False, should_exit=True),
        "http://127.0.0.1:8765",
        threading.Event(),
    )


@pytest.mark.parametrize("raises", [False, True])
def test_browser_failure_keeps_manual_address(monkeypatch, capsys, raises):
    def unavailable(url):
        if raises:
            raise OSError("No desktop browser")
        return False

    monkeypatch.setattr(server.webbrowser, "open", unavailable)
    server.open_when_ready(
        SimpleNamespace(started=True, should_exit=False),
        "http://127.0.0.1:9876",
        threading.Event(),
    )
    assert "请手动访问：http://127.0.0.1:9876" in capsys.readouterr().out
