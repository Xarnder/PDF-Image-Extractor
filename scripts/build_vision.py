"""Build the local macOS content-analysis helper without downloading dependencies."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build():
    if sys.platform != 'darwin':
        print('Apple Vision is macOS-only; using portable content checks.')
        return
    compiler = shutil.which('swiftc')
    if not compiler:
        print('Apple Vision helper not built: Swift compiler unavailable. Portable checks remain active.')
        return
    source = ROOT / 'native/vision.swift'
    binary = ROOT / '.runtime/vision-helper'
    marker = binary.with_suffix('.sha256')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if binary.exists() and marker.exists() and marker.read_text() == digest:
        print('Apple Vision helper is up to date.')
        return
    binary.parent.mkdir(exist_ok=True)
    temporary = binary.with_suffix('.part')
    try:
        subprocess.run([compiler, '-O', str(source), '-o', str(temporary)], check=True, timeout=180)
        temporary.replace(binary)
        marker.write_text(digest)
        print('Built Apple Vision: offline face, text and content analysis.')
    except (OSError, subprocess.SubprocessError) as exc:
        temporary.unlink(missing_ok=True)
        print(f'Apple Vision build unavailable; portable checks remain active: {exc}')


if __name__ == '__main__':
    build()
