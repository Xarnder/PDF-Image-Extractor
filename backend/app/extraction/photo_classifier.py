import cv2
import numpy as np
from PIL import Image


def classify(image: Image.Image):
    """Conservative, explainable heuristic, not a semantic AI probability."""
    thumb = image.convert('RGB').copy()
    thumb.thumbnail((192, 192))
    rgb = np.asarray(thumb)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    p = hist[hist > 0] / gray.size
    entropy = float(-(p * np.log2(p)).sum())
    unique = len(np.unique((rgb // 8).reshape(-1, 3), axis=0))
    edges = float((cv2.Canny(gray, 70, 180) > 0).mean())
    if entropy < 2.2 or unique < 35:
        return 'Graphic / low-detail region', 0.35, ['Low visual complexity; inspect before accepting']
    if entropy > 5.0 and unique > 180 and edges < 0.36:
        return 'Likely photograph', 0.88, []
    return 'Uncertain photograph', 0.64, ['Photograph classification is uncertain']
