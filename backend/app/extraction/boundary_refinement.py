import numpy as np
from app.extraction.geometry import Detection


def refine(detection: Detection, image, strength: float):
    if detection.source or strength == 0:
        return detection
    # Snap only to a strong colour discontinuity within a small neighbourhood.
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32)
    h,w = rgb.shape[:2]
    b = list(detection.bbox)
    radius = max(1, round(1 + 3*strength))
    for index in range(4):
        axis = index % 2
        current = round(b[index])
        candidates = []
        for pos in range(current-radius,current+radius+1):
            if axis == 0 and 1 <= pos < w:
                lo,hi = max(0,round(b[1])), min(h,round(b[3]))
                values = np.abs(rgb[lo:hi,pos]-rgb[lo:hi,pos-1]).mean(axis=1)
            elif axis == 1 and 1 <= pos < h:
                lo,hi = max(0,round(b[0])), min(w,round(b[2]))
                values = np.abs(rgb[pos,lo:hi]-rgb[pos-1,lo:hi]).mean(axis=1)
            else:
                continue
            if len(values) and (values > 20).mean() > .8:
                candidates.append((float(values.mean()),pos))
        if candidates:
            b[index] = float(max(candidates)[1])
    detection.bbox = b
    return detection
