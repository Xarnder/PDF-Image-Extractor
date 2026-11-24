import sys
import os
import tempfile
import shutil
import atexit
from pathlib import Path
test_data=tempfile.mkdtemp(prefix='pdf-extractor-tests-')
os.environ['PDF_EXTRACTOR_DATA']=test_data
atexit.register(shutil.rmtree,test_data,ignore_errors=True)
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
