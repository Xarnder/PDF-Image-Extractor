"""Local face/text/content evidence; an unavailable optional helper never blocks extraction."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import cv2
import numpy as np
from PIL import Image
from app.core.config import ROOT

HELPER = ROOT / '.runtime/vision-helper'
_cascade = None


def status():
    available = sys.platform == 'darwin' and HELPER.is_file() and os.access(HELPER, os.X_OK)
    return {'available': available, 'name': 'Apple Vision' if available else 'OpenCV content checks',
            'description': 'Offline faces, text and image classification' if available else 'Portable face and graphic checks; semantic classifier unavailable'}


def portable_evidence(image):
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    thumb = image.convert('RGB').copy()
    thumb.thumbnail((800, 800))
    gray = cv2.cvtColor(np.asarray(thumb), cv2.COLOR_RGB2GRAY)
    faces = []
    if min(thumb.size) >= 32 and not _cascade.empty():
        for x, y, w, h in _cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24)):
            faces.append([x/thumb.width, y/thumb.height, (x+w)/thumb.width, (y+h)/thumb.height])
    return {'faces': faces, 'labels': [], 'texts': [], 'backend': 'OpenCV'}


def analyze(images, enabled=True):
    if not images:
        return [], None, []
    if enabled and status()['available']:
        payload = []
        for image in images:
            thumb = image.convert('RGB').copy()
            thumb.thumbnail((1100, 1100))
            data = io.BytesIO()
            thumb.save(data, format='JPEG', quality=94)
            payload.append({'image': base64.b64encode(data.getvalue()).decode('ascii')})
        try:
            result = subprocess.run([str(HELPER)], input=json.dumps(payload).encode(), capture_output=True,
                                    timeout=min(90, 15 + 4*len(images)), check=True)
            evidence = json.loads(result.stdout)
            if len(evidence) != len(images) or any('error' in e for e in evidence):
                raise ValueError('Incomplete Vision content analysis')
            return [{**e, 'backend': 'Apple Vision'} for e in evidence], 'Apple Vision', []
        except (OSError, ValueError, subprocess.SubprocessError):
            return [portable_evidence(im) for im in images], 'OpenCV face checks', ['Apple Vision unavailable for this page; portable content checks used.']
    return [portable_evidence(im) for im in images], 'OpenCV face checks', []
