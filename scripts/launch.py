import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.runtime.json'
parser=argparse.ArgumentParser()
parser.add_argument('--stop',action='store_true')
parser.add_argument('--no-browser',action='store_true')
parser.add_argument('--background',action='store_true')
args=parser.parse_args()


def running():
    if STATE.exists():
        try:
            import psutil
            data=json.loads(STATE.read_text())
            proc=psutil.Process(data['pid'])
            if 'app.api.main:app' in proc.cmdline() and Path(proc.cwd()).resolve()==ROOT:
                return data
        except (ValueError,OSError,KeyError,psutil.Error): pass
    return None


def open_browser(url):
    if sys.platform=='darwin':
        if subprocess.run(['open','-a','Google Chrome',url],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0: return
    webbrowser.open(url)


existing=running()
if args.stop:
    if existing:
        import psutil
        print('Stopping PDF Image Extractor. Completed pages are saved.')
        try:
            process=psutil.Process(existing['pid'])
            process.terminate()
            process.wait(timeout=30)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            raise SystemExit('Shutdown is still in progress. Read logs/launcher.log before restarting.')
        # The launcher releases its lock and removes the runtime file after reaping
        # the child. Wait for that cleanup so an immediate restart is reliable.
        for _ in range(100):
            if not STATE.exists(): break
            try:
                if json.loads(STATE.read_text()).get('pid')!=existing['pid']: break
            except (OSError,ValueError): break
            time.sleep(.05)
        print('PDF Image Extractor stopped.')
    else: print('PDF Image Extractor is not running.')
    sys.exit(0)
if existing:
    print(f'Already running: {existing["url"]}')
    if not args.no_browser: open_browser(existing['url'])
    sys.exit(0)
if args.background:
    (ROOT/'logs').mkdir(exist_ok=True)
    with (ROOT/'logs'/'launcher.log').open('a') as log:
        command=[sys.executable,str(Path(__file__).resolve())]
        if args.no_browser: command.append('--no-browser')
        proc=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
    for _ in range(100):
        if proc.poll() is not None: raise SystemExit('Startup failed. Read logs/launcher.log.')
        state=running()
        if state:
            try:
                with urllib.request.urlopen(state['url']+'/api/health',timeout=1) as response:
                    if response.status==200: print(state['url']);sys.exit(0)
            except Exception: pass
        time.sleep(.2)
    raise SystemExit('Server did not become ready. Read logs/launcher.log.')

lock=(ROOT/'logs'/'launcher.lock').open('w')
try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError: raise SystemExit('Another launcher is starting. Please wait.')
sock=socket.socket()
for port in range(8765,8866):
    try:
        sock.bind(('127.0.0.1',port));break
    except OSError: continue
else: sock.bind(('127.0.0.1',0))
sock.listen(128)
sock.set_inheritable(True)
port=sock.getsockname()[1]
url=f'http://127.0.0.1:{port}'
env={**os.environ,'PYTHONPATH':str(ROOT/'backend'),'HF_HUB_DISABLE_TELEMETRY':'1','DO_NOT_TRACK':'1'}
server=subprocess.Popen([sys.executable,'-m','uvicorn','app.api.main:app','--host','127.0.0.1','--fd',str(sock.fileno()),'--log-level','warning','--timeout-graceful-shutdown','15'],cwd=ROOT,env=env,pass_fds=(sock.fileno(),))
sock.close()
STATE.write_text(json.dumps({'pid':server.pid,'launcher_pid':os.getpid(),'url':url}))
def stop(signum,frame):
    if server.poll() is None: server.terminate()
signal.signal(signal.SIGINT,stop)
signal.signal(signal.SIGTERM,stop)
try:
    for _ in range(150):
        if server.poll() is not None: raise RuntimeError('Server exited during startup.')
        try:
            with urllib.request.urlopen(url+'/api/health',timeout=1) as response:
                if response.status==200: break
        except Exception: time.sleep(.2)
    else: raise RuntimeError('Server startup timed out.')
    print(f'PDF Image Extractor: {url}\nPress Ctrl+C or run ./stop.sh to stop.',flush=True)
    if not args.no_browser: open_browser(url)
    server.wait()
finally:
    if server.poll() is None:
        server.terminate()
        try: server.wait(20)
        except subprocess.TimeoutExpired: server.kill();server.wait()
    STATE.unlink(missing_ok=True)
