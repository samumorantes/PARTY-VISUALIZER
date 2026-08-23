# -*- coding: utf-8 -*-
"""FIESTA launcher — garantiza que el server esté vivo y abre la app en Edge/Chrome."""
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:8888/"


def server_alive():
    try:
        with urllib.request.urlopen(URL + "api/sync", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    """Arranca server.py con pythonw (sin consola)."""
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    subprocess.Popen(
        [exe, os.path.join(HERE, "server.py")],
        cwd=HERE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def wait_server(seconds=8):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if server_alive():
            return True
        time.sleep(0.5)
    return False


def open_browser():
    """Edge en modo app (ventana propia); Chrome como respaldo."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for b in candidates:
        if os.path.exists(b):
            subprocess.Popen([b, "--start-maximized", "--app=" + URL])
            return
    import webbrowser
    webbrowser.open(URL)


def main():
    if not server_alive():
        start_server()
        wait_server()
    open_browser()


if __name__ == "__main__":
    main()
