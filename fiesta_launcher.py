# -*- coding: utf-8 -*-
"""FIESTA launcher — abre el visualizador en ventana app de Chrome."""
import os
import subprocess
import sys
import webbrowser

URL = "http://localhost:8888/"
CHROMES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
EDGES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

def main():
    for browser in CHROMES + EDGES:
        if os.path.exists(browser):
            subprocess.Popen([browser, "--start-maximized", "--app=" + URL])
            return
    webbrowser.open(URL)   # navegador por defecto

if __name__ == "__main__":
    main()
    sys.exit(0)
