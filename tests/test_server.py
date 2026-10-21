import json
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


# Exercise the actual launcher and HTTP listener without opening desktop tabs.
BROWSER_PROBE = r"""
import json
from pathlib import Path
import sys
import threading
import httpx
import uvicorn
from scripts import server

mode, port, marker = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
def browser(url):
    status = httpx.get(url, timeout=3).status_code
    marker.write_text(json.dumps({"url": url, "status": status}), encoding="utf-8")
    if mode == "blocked":
        threading.Event().wait()
    if mode == "raises":
        raise OSError("Browser association unavailable")
    return mode != "unavailable"
server.webbrowser.open = browser
if mode == "startup_failure":
    original_config = uvicorn.Config
    async def failed_app(scope, receive, send):
        await receive()
        await send({"type": "lifespan.startup.failed", "message": "test startup failure"})
    def config(*args, **kwargs):
        return original_config(failed_app, **kwargs)
    uvicorn.Config = config
arguments = ["server.py", "run", "--port", str(port)]
if mode == "disabled":
    arguments.append("--no-browser")
sys.argv = arguments
raise SystemExit(server.main())
"""


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "unavailable",
        "raises",
        "blocked",
        "disabled",
        "early_stop",
        "startup_failure",
    ],
)
def test_real_launcher_browser_lifecycle(tmp_path, mode):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    marker = tmp_path / "browser.json"
    process = subprocess.Popen(
        [sys.executable, "-c", BROWSER_PROBE, mode, str(port), str(marker)],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **os.environ,
            "SDR_DATA_DIR": str(tmp_path),
            "SDR_ACCESS_TOKEN": "",
            "PYTHONUTF8": "1",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        if mode not in ("early_stop", "startup_failure"):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                assert process.poll() is None, "Launcher exited before becoming ready"
                if mode == "disabled":
                    try:
                        if (
                            httpx.get(
                                f"http://127.0.0.1:{port}/", timeout=0.3
                            ).status_code
                            == 200
                        ):
                            break
                    except httpx.HTTPError:
                        pass
                elif marker.exists():
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("Launcher/browser did not become ready")
        stdout, stderr = process.communicate(
            input="" if mode == "startup_failure" else "\n", timeout=15
        )
        if mode == "startup_failure":
            assert process.returncode != 0, (stdout, stderr)
            assert "test startup failure" in stderr
        else:
            assert process.returncode == 0, (stdout, stderr)
            assert "项目已停止" in stdout
        if mode in ("disabled", "early_stop", "startup_failure"):
            assert not marker.exists(), (stdout, stderr)
        else:
            assert json.loads(marker.read_text(encoding="utf-8")) == {
                "url": f"http://127.0.0.1:{port}",
                "status": 200,
            }
        if mode in ("unavailable", "raises"):
            assert f"请手动访问：http://127.0.0.1:{port}" in stdout
            assert "Exception in thread" not in stderr
        assert not (tmp_path / "server-control" / f"{port}.json").exists()
        with socket.socket() as released:
            if os.name == "nt":
                released.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            released.bind(("127.0.0.1", port))
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_occupied_port_does_not_open_browser(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        marker = tmp_path / "browser.json"
        result = subprocess.run(
            [sys.executable, "-c", BROWSER_PROBE, "success", str(port), str(marker)],
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "SDR_DATA_DIR": str(tmp_path), "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        assert result.returncode == 1, result.stderr
        assert "已被占用" in result.stdout
        assert not marker.exists()
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
