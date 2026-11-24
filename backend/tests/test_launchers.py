import importlib.util
import json
import socket
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('windows_launcher', ROOT / 'scripts/windows_launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_windows_socket_falls_back_when_port_is_busy():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        with launcher.bind_socket([port]) as chosen:
            assert chosen.getsockname()[0] == '127.0.0.1'
            assert chosen.getsockname()[1] != port


def test_windows_existing_instance_rejects_reused_pid(tmp_path, monkeypatch):
    import psutil
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'pid':123, 'created':1.0, 'port':8765}))
    monkeypatch.setattr(launcher, 'STATE', state)
    process = SimpleNamespace(create_time=lambda:2.0, is_running=lambda:True,
                              cmdline=lambda:[str(Path(launcher.__file__).resolve()), '--serve'])
    monkeypatch.setattr(psutil, 'Process', lambda pid:process)
    assert launcher.existing_url() is None
    process.create_time = lambda:1.0
    assert launcher.existing_url() == 'http://127.0.0.1:8765'
    process.cmdline = lambda:['unrelated.py']
    assert launcher.existing_url() is None


def test_windows_browser_falls_back_when_chrome_cannot_launch(tmp_path, monkeypatch):
    chrome = tmp_path / 'Google/Chrome/Application/chrome.exe'
    chrome.parent.mkdir(parents=True)
    chrome.touch()
    monkeypatch.setenv('PROGRAMFILES', str(tmp_path))
    monkeypatch.delenv('PROGRAMFILES(X86)', raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    def unavailable(*args, **kwargs):
        raise OSError('Cannot start browser')
    monkeypatch.setattr(launcher.subprocess, 'Popen', unavailable)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, 'open', opened.append)
    launcher.open_browser('http://127.0.0.1:8765')
    assert opened == ['http://127.0.0.1:8765']
