"""Local start/stop controls without killing arbitrary processes or adding an HTTP endpoint."""

import argparse
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
import webbrowser
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config


class InstanceLock:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if not path.stat().st_size:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise

    def close(self):
        self.file.close()


def paths(port):
    folder = config.RUNTIME / "server-control"
    return (folder / f"{port}.lock", folder / f"{port}.json", folder / f"{port}.stop")


class StartHint(logging.Filter):
    def filter(self, record):
        for key in ("msg", "color_message"):
            value = getattr(record, key, None)
            if isinstance(value, str):
                setattr(record, key, value.replace(" (Press CTRL+C to quit)", ""))
        return True


def open_when_ready(server, url, done):
    """Launch only after Uvicorn has completed application startup."""
    while not done.wait(0.1):
        if server.should_exit:
            return
        if server.started:
            try:
                opened = webbrowser.open(url)
            except Exception:
                opened = False
            if opened:
                print("已请求浏览器打开项目页面。", flush=True)
            else:
                print(f"未能自动打开浏览器，请手动访问：{url}", flush=True)
            return


def serve(port, console=True, open_browser=True):
    import uvicorn

    lock_path, state_path, stop_path = paths(port)
    try:
        lock = InstanceLock(lock_path)
    except OSError:
        print("项目已经启动，无需重复运行。关闭时请双击“停止项目.bat”。", flush=True)
        return 1
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    done = threading.Event()
    try:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
            listener.listen(socket.SOMAXCONN)
        except OSError:
            print(
                f"端口 {port} 已被占用。请先关闭原来的服务窗口，再启动本项目。",
                flush=True,
            )
            return 1
        token = uuid4().hex
        stop_path.unlink(missing_ok=True)
        state_path.write_text(
            json.dumps({"instance": token, "pid": os.getpid(), "port": port}),
            encoding="utf-8",
        )
        server = uvicorn.Server(
            uvicorn.Config("app.main:app", host="127.0.0.1", port=port)
        )
        logging.getLogger("uvicorn.error").addFilter(StartHint())

        def request_stop():
            if not server.should_exit:
                print("正在停止服务；已有任务处理完成后退出。", flush=True)
                server.should_exit = True

        def watch_stop():
            while not done.wait(0.25):
                try:
                    if (
                        json.loads(stop_path.read_text(encoding="utf-8")).get(
                            "instance"
                        )
                        == token
                    ):
                        request_stop()
                        return
                except (OSError, ValueError, AttributeError):
                    pass

        def read_console():
            try:
                if sys.stdin.readline():
                    request_stop()
            except (OSError, ValueError):
                pass

        threading.Thread(target=watch_stop, daemon=True).start()
        if console:
            threading.Thread(target=read_console, daemon=True).start()
        url = f"http://127.0.0.1:{port}"
        if open_browser:
            threading.Thread(
                target=open_when_ready, args=(server, url, done), daemon=True
            ).start()
        print(f"项目地址：{url}", flush=True)
        print(
            "停止方式：在此窗口按 Enter，或双击项目目录中的“停止项目.bat”。", flush=True
        )
        server.run(sockets=[listener])
        # A local ASR thread may still be saving its completed transcript after HTTP shutdown.
        from app.recordings import POOL

        POOL.shutdown(wait=True)
        print("项目已停止。", flush=True)
        return 0
    finally:
        done.set()
        listener.close()
        state_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)
        lock.close()


def stop(port):
    lock_path, state_path, stop_path = paths(port)
    try:
        lock = InstanceLock(lock_path)
    except OSError:
        lock = None
    if lock:
        lock.close()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                print(
                    "此端口的服务不是通过run.bat启动，请先关闭原来的服务窗口，再使用run.bat启动。",
                    flush=True,
                )
                return 1
        except OSError:
            pass
        print("项目尚未启动，或已经停止。", flush=True)
        return 0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        token = state["instance"]
        if not isinstance(token, str) or len(token) != 32:
            raise ValueError("invalid instance")
        temporary = stop_path.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(json.dumps({"instance": token}), encoding="utf-8")
        temporary.replace(stop_path)
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "无法读取项目启动状态，请稍候重试；若使用旧启动方式，请先关闭原来的服务窗口。",
            flush=True,
        )
        return 1
    for _ in range(25):
        if not state_path.exists():
            print("项目已停止。", flush=True)
            return 0
        time.sleep(0.2)
    print("停止请求已发送，当前任务完成后会自动退出，无需再次操作。", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("run", "stop"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-console", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return (
        serve(args.port, not args.no_console, not args.no_browser)
        if args.action == "run"
        else stop(args.port)
    )


if __name__ == "__main__":
    raise SystemExit(main())
