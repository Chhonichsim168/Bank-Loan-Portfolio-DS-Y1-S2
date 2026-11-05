"""
launch.py - the one-click starter behind "START Credit Desk" (Windows / Mac).

What it does, in order:
  1. Checks the Python version (3.10 or newer).
  2. The first time only: makes a private package folder (.venv) inside this project and installs
     everything in requirements.txt into it. Nothing else on the computer is changed.
  3. Picks a free port, starts Credit Desk and opens it in the web browser.

You can also run it by hand:   python launch.py
Close the black window (or press Ctrl+C) to stop the app.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
NEEDED = ("streamlit", "pandas", "numpy", "sklearn", "scipy", "joblib", "plotly",
          "openpyxl", "reportlab", "cryptography", "matplotlib", "authlib", "httpx")
INSIDE_FLAG = "--inside-venv"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def stop(msg: str) -> None:
    say()
    say("PROBLEM: " + msg)
    sys.exit(1)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def missing_packages(python: str) -> list[str]:
    code = ("import importlib.util,sys;"
            f"print(','.join(m for m in {NEEDED!r} if importlib.util.find_spec(m) is None))")
    out = subprocess.run([python, "-c", code], capture_output=True, text=True)
    if out.returncode != 0:
        return list(NEEDED)
    return [m for m in out.stdout.strip().split(",") if m]


def install(python: str, extra: list[str] | None = None) -> None:
    say("Installing the packages Credit Desk needs (first time only, needs internet,")
    say("takes about 2-5 minutes)...")
    say()
    base = [python, "-m", "pip", "install", "--disable-pip-version-check"] + (extra or [])
    subprocess.run(base + ["--upgrade", "pip"], capture_output=True)
    if subprocess.run(base + ["-r", str(REQUIREMENTS)]).returncode != 0:
        stop("Installing packages failed. Check the internet connection and start again.\n"
             "(If it keeps failing, delete the .venv folder inside the project and start again.)")


def make_venv() -> bool:
    """Create .venv. Returns False when this Python cannot make one (some Linux builds)."""
    if venv_python().exists():
        ok = subprocess.run([str(venv_python()), "-c", "import sys"], capture_output=True).returncode == 0
        if ok:
            return True
        say("The private package folder (.venv) is broken (was the project moved?). Rebuilding it...")
        import shutil
        shutil.rmtree(VENV, ignore_errors=True)
    say("Preparing a private package folder for Credit Desk (first time only)...")
    return subprocess.run([sys.executable, "-m", "venv", str(VENV)]).returncode == 0 and venv_python().exists()


def free_port(start: int = 8501) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def open_browser_when_ready(port: int) -> None:
    url = f"http://localhost:{port}"
    for _ in range(240):                      # up to 2 minutes (first start trains the model)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                time.sleep(1.5)
                webbrowser.open(url)
                return
        time.sleep(0.5)


def google_sign_in_set_up() -> bool:
    secrets = ROOT / ".streamlit" / "secrets.toml"
    try:
        return "[auth.google]" in secrets.read_text(encoding="utf-8")
    except OSError:
        return False


ONLINE_FLAG = "--online"
SECRETS = ROOT / ".streamlit" / "secrets.toml"
LOCAL_REDIRECT = "http://localhost:8501/oauth2callback"


def _secret_value(key: str) -> str:
    import re
    try:
        m = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]*)"', SECRETS.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return m.group(1).strip() if m else ""


def _set_redirect(uri: str) -> None:
    """Google only accepts the address registered in Google Cloud Console, so the sign-in address
    is switched between this computer (localhost) and the public ngrok address."""
    import re
    try:
        text = SECRETS.read_text(encoding="utf-8")
    except OSError:
        return
    new = re.sub(r'^(\s*redirect_uri\s*=\s*)"[^"]*"', lambda m: f'{m.group(1)}"{uri}"', text, count=1, flags=re.M)
    if new != text:
        SECRETS.write_text(new, encoding="utf-8")


def start_ngrok(domain: str):
    """Start the ngrok tunnel to port 8501. Returns the process (or stops with instructions)."""
    import shutil
    exe = shutil.which("ngrok") or next((str(p) for p in (ROOT / "ngrok.exe", ROOT / "ngrok") if p.exists()), None)
    if not exe:
        stop("ngrok is not installed. Download it from https://ngrok.com/download, put ngrok.exe in this\n"
             "folder (next to app.py), run once:  ngrok config add-authtoken YOUR_TOKEN  and start again.\n"
             "See 'GO ONLINE WITH NGROK (Khmer).md'.")
    return subprocess.Popen([exe, "http", f"--url={domain}", "8501", "--log=stdout"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_app(python: str) -> None:
    online = ONLINE_FLAG in sys.argv
    port = free_port()
    url = f"http://localhost:{port}"
    tunnel = None
    if online:
        domain = _secret_value("CREDIT_DESK_PUBLIC_DOMAIN").replace("https://", "").strip("/")
        if not domain:
            stop('Put your ngrok address in .streamlit/secrets.toml first, for example:\n'
                 '  CREDIT_DESK_PUBLIC_DOMAIN = "credit-desk-g4.ngrok-free.app"')
        if port != 8501:
            stop("Port 8501 is busy - close the other Credit Desk window first, then start ONLINE again.")
        _set_redirect(f"https://{domain}/oauth2callback")
        tunnel = start_ngrok(domain)
        url = f"https://{domain}"
    elif _secret_value("redirect_uri").startswith("https://") and "ngrok" in _secret_value("redirect_uri"):
        _set_redirect(LOCAL_REDIRECT)              # back to this computer only
    if google_sign_in_set_up() and port != 8501:
        say()
        say("NOTE: port 8501 is busy (is Credit Desk already open in another window?).")
        say("      'Continue with Google' only works at http://localhost:8501 - close the other")
        say("      window and start again. Username and password sign-in work as usual.")
    if online:
        say()
        say("ONLINE: customers can open  " + url + "  on their phones.")
        say("        Keep this computer on and connected while they use it.")
    if google_sign_in_set_up() and port != 8501:
        say()
        say("NOTE: port 8501 is busy (is Credit Desk already open in another window?).")
        say("      'Continue with Google' only works at http://localhost:8501 - close the other")
        say("      window and start again. Username and password sign-in work as usual.")
    say()
    say("=" * 64)
    say("  Credit Desk is starting at  " + url)
    say("  Sign in:  admin / admin123    risk / risk123    officer / officer123")
    say("  The browser opens by itself. If it does not, copy the address above.")
    say("  KEEP THIS WINDOW OPEN while you use the app. Close it to stop.")
    say("=" * 64)
    say()
    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    try:
        subprocess.run([python, "-m", "streamlit", "run", str(ROOT / "app.py"),
                        "--server.port", str(port), "--server.address", "127.0.0.1",
                        "--server.headless", "true",
                        "--browser.gatherUsageStats", "false"], cwd=str(ROOT))
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel is not None:
            tunnel.terminate()
    say("Credit Desk stopped.")


def main() -> None:
    os.chdir(ROOT)
    if sys.version_info < (3, 10):
        stop(f"This computer has Python {sys.version.split()[0]}. Credit Desk needs Python 3.10 or newer.\n"
             "Install it from https://www.python.org/downloads/ and start again.")
    if not (ROOT / "app.py").exists() or not REQUIREMENTS.exists():
        stop("The project files are not complete. Download / extract the whole project folder again.")

    if INSIDE_FLAG in sys.argv or Path(sys.prefix).resolve() == VENV.resolve():
        python = sys.executable
    elif make_venv():
        python = str(venv_python())
    else:
        # This Python cannot make a private folder: install for the current user instead.
        say("(Could not make a private package folder; installing for this user instead.)")
        python = sys.executable
        if missing_packages(python):
            install(python, ["--user"])
        run_app(python)
        return

    if missing_packages(python):
        install(python)
        still = missing_packages(python)
        if still:
            stop("These packages are still missing after installing: " + ", ".join(still))
        say()
        say("All packages installed.")
    run_app(python)


if __name__ == "__main__":
    main()
