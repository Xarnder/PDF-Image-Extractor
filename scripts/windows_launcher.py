"""Windows bootstrap and foreground server; safe to import in spawned PDF workers."""
import argparse
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import venv
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.windows-runtime.json'
ENV = ROOT / '.venv-windows'


def open_browser(url):
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        folder = os.environ.get(variable)
        if folder:
            chrome = Path(folder) / 'Google/Chrome/Application/chrome.exe'
            if chrome.is_file():
                try:
                    subprocess.Popen([str(chrome), url])
                    return
                except OSError:
                    pass
    webbrowser.open(url)


def bind_socket(ports=range(8765, 8866)):
    sock = socket.socket()
    try:
        for port in ports:
            try:
                sock.bind(('127.0.0.1', port))
                break
            except OSError:
                continue
        else:
            sock.bind(('127.0.0.1', 0))
        sock.listen(128)
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise


def existing_url():
    import psutil
    try:
        state = json.loads(STATE.read_text())
        process = psutil.Process(state['pid'])
        if process.create_time() != state['created'] or not process.is_running():
            return None
        if str(Path(__file__).resolve()) not in process.cmdline():
            return None
        port = int(state['port'])
        if 1 <= port <= 65535:
            return f'http://127.0.0.1:{port}'
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        pass
    return None


def bootstrap(no_browser):
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Python 3.12 is required for this dependency lockfile.')
    python = ENV / 'Scripts/python.exe'
    lockfile = ROOT / 'backend/requirements.lock'
    digest = hashlib.sha256(lockfile.read_bytes()).hexdigest()
    marker = ENV / '.requirements-sha256'
    if not python.is_file():
        if shutil.disk_usage(ROOT).free < 2 * 1024**3:
            raise RuntimeError('At least 2 GB of free space is required for setup.')
        print('Creating the local Windows Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
    if not marker.exists() or marker.read_text() != digest:
        print('Installing local dependencies. The first start needs internet access.', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(lockfile)], check=True)
        marker.write_text(digest)
    if not (ROOT / 'frontend/dist/index.html').is_file():
        node = shutil.which('node')
        npm = shutil.which('npm.cmd')
        if not node or not npm:
            raise RuntimeError('Install Node.js 22.12+ from https://nodejs.org and run this file again.')
        subprocess.run([node, '-e', 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a<22||(a===22&&b<12)?1:0)'], check=True)
        print('Building the interface...', flush=True)
        # Invoke the installed npm CLI through Node instead of shell-parsing paths.
        npm_cli = Path(npm).parent / 'node_modules/npm/bin/npm-cli.js'
        if not npm_cli.is_file():
            raise RuntimeError('Cannot locate npm-cli.js beside npm.cmd. Repair the Node.js installation.')
        for command in (['ci', '--legacy-peer-deps'], ['run', 'build']):
            subprocess.run([node, str(npm_cli), *command], cwd=ROOT / 'frontend', check=True)
    command = [str(python), str(Path(__file__).resolve()), '--serve']
    if no_browser:
        command.append('--no-browser')
    child = subprocess.Popen(command, cwd=ROOT)
    try:
        return child.wait()
    except KeyboardInterrupt:
        # Windows delivers console Ctrl+C to both processes. Let Uvicorn finish
        # its shutdown instead of subprocess.call killing it on interruption.
        try:
            return child.wait(timeout=35)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait()
            return 1


def serve(no_browser):
    import msvcrt
    import psutil
    import uvicorn
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / 'backend'))
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['DO_NOT_TRACK'] = '1'
    (ROOT / 'logs').mkdir(exist_ok=True)
    with (ROOT / 'logs/windows-launcher.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            for _ in range(25):
                url = existing_url()
                if url:
                    print(f'Already running: {url}')
                    if not no_browser:
                        open_browser(url)
                    return 0
                time.sleep(.2)
            raise RuntimeError('Another launcher is starting or stopping. Wait a moment and try again.')

        sock = bind_socket()
        port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        server = uvicorn.Server(uvicorn.Config('app.api.main:app', host='127.0.0.1', port=port,
                                             log_level='warning', timeout_graceful_shutdown=15))
        finished = threading.Event()

        def ready():
            while not finished.wait(.1):
                if server.started:
                    temporary = STATE.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'pid':os.getpid(), 'created':psutil.Process().create_time(), 'port':port}))
                    temporary.replace(STATE)
                    print(f'PDF Image Extractor: {url}\nKeep this window open. Press Ctrl+C to stop.', flush=True)
                    if not no_browser:
                        open_browser(url)
                    return

        watcher = threading.Thread(target=ready, daemon=True)
        watcher.start()
        try:
            # The socket stays in this process: no Unix-only pass_fds or fcntl.
            server.run(sockets=[sock])
            return 0 if server.started else 1
        finally:
            finished.set()
            watcher.join(2)
            sock.close()
            STATE.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        print('On macOS, double-click Start PDF Image Extractor.command or run ./start.sh.')
        return 1
    try:
        return serve(args.no_browser) if args.serve else bootstrap(args.no_browser)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Unable to start PDF Image Extractor: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
