"""Single-file desktop entry point: private loopback service and native Flutter UI."""
import ctypes
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time


def run():
    profile = Path(os.environ.get("SHIJUAN_PROFILE", str(Path(os.environ["LOCALAPPDATA"]) / "ShijuanStudio")))
    profile.mkdir(parents=True, exist_ok=True)
    os.environ["SHIJUAN_PROFILE"] = str(profile)
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        os.environ["DATA_DIR"] = str(profile / "tasks")
    else:
        # Source mode keeps the existing service's task directory.
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).with_name(".env"))
        os.environ["DATA_DIR"] = str(Path(os.environ.get(
            "DATA_DIR", str(Path(__file__).with_name("data")))).resolve())
    os.environ["SERVICE_TOKEN"] = secrets.token_urlsafe(32)
    # Only one desktop process may write the persistent task store.
    from ctypes import wintypes
    ctypes.windll.kernel32.CreateMutexW.restype = wintypes.HANDLE
    ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ShijuanStudioDesktop")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, "试卷工作室已经打开，请在任务栏中切换到已有窗口。", "试卷工作室", 64)
        return
    import desktop_settings
    desktop_settings.load()
    import main
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    os.environ["SHIJUAN_SERVICE_URL"] = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(main.app, log_config=None, access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        if not thread.is_alive():
            raise RuntimeError("处理组件启动失败")
        time.sleep(.05)
    if not server.started:
        raise RuntimeError("处理组件启动超时")
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    desktop = (bundle / "desktop" if frozen else
               Path(__file__).resolve().parent.parent / "dist" / "windows")
    try:
        if "--smoke-test" in sys.argv:
            import httpx
            with httpx.Client(base_url=os.environ["SHIJUAN_SERVICE_URL"],
                              headers={"Authorization": "Bearer " + os.environ["SERVICE_TOKEN"]}) as client:
                assert client.get("/health").raise_for_status().json()["status"] == "ok"
                task = client.post("/demo", timeout=60).raise_for_status().json()
                assert task["status"] == "completed"
                document = client.get(f"/tasks/{task['id']}/files/exports/paper.docx").raise_for_status()
                import io
                import zipfile
                with zipfile.ZipFile(io.BytesIO(document.content)) as archive:
                    assert b"<m:oMath" in archive.read("word/document.xml")
                    assert any(name.startswith("word/media/") for name in archive.namelist())
                (profile / "smoke-test.txt").write_text(str(task), encoding="utf-8")
        else:
            environment = os.environ.copy()
            environment.pop("DEEPSEEK_API_KEY", None)
            subprocess.run([str(desktop / "shijuan_studio.exe")],
                           cwd=desktop, env=environment, check=True)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        if "--smoke-test" in sys.argv:
            import traceback
            (Path(os.environ["SHIJUAN_PROFILE"]) / "smoke-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            sys.exit(1)
        ctypes.windll.user32.MessageBoxW(None, f"启动未完成：{error}", "试卷工作室", 16)
