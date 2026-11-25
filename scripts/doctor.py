import importlib.metadata
import platform
import shutil
import sys
from pathlib import Path
from app.core.config import ROOT, DATA
from app.extraction.ai_detector import model_status
from app.extraction.content_analysis import status as content_analysis_status

print('PDF Image Extractor installation check')
print(f'Python: {platform.python_version()} | {platform.system()} {platform.release()} | {platform.machine()}')
assert sys.version_info[:2] == (3,12), 'This lockfile is validated with Python 3.12.'
for name in ('fastapi','uvicorn','PyMuPDF','opencv-python-headless','numpy','Pillow','ImageHash','psutil'):
    print(f'  {name}: {importlib.metadata.version(name)}')
import pymupdf, cv2, numpy, PIL
with pymupdf.open() as doc:
    doc.new_page()
    assert doc[0].get_pixmap().width > 0
print(f'PDF rendering and OpenCV: OK | {shutil.disk_usage(DATA).free / 1024**3:.1f} GB free')
print(f'Frontend: {"built" if (ROOT / "frontend/dist/index.html").exists() else "MISSING; run setup"}')
print(f'Data directory: {DATA}')
status=model_status()
print(f'Heron: {"available" if status["available"] else "not installed (optional)"}')
print(f'Content analysis: {content_analysis_status()["name"]} | offline face priority')
try:
    import torch
    print(f'MPS available: {torch.backends.mps.is_available()} | CUDA available: {torch.cuda.is_available()}')
except ImportError:
    print('PyTorch not installed. Heron and MPS/CUDA acceleration are unavailable; local content-analysis status is shown above.')
