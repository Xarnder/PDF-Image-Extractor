"""Background-adaptive segmentation with constrained recursive gutter splitting."""
import cv2
import numpy as np
from PIL import Image
from app.extraction.geometry import Detection, area, iou, containment


def runs(values):
    padded = np.r_[False, values, False].astype(np.int8)
    changes = np.diff(padded)
    return list(zip(np.where(changes == 1)[0], np.where(changes == -1)[0]))


class OpenCVDetector:
    name = 'OpenCV'

    def detect(self, image: Image.Image, settings):
        rgb = np.asarray(image.convert('RGB'))
        h, w = rgb.shape[:2]
        # Border median plus frequent near-border colours handles dark and coloured paper.
        strip = max(2, min(w, h)//100)
        border = np.concatenate((rgb[:strip].reshape(-1,3), rgb[-strip:].reshape(-1,3), rgb[:,:strip].reshape(-1,3), rgb[:,-strip:].reshape(-1,3)))
        bg = np.median(border, axis=0)
        noise = np.median(np.max(np.abs(border.astype(float)-bg), axis=1))
        tolerance = min(48, 12 + noise * 1.5 + settings.sensitivity * 16)
        distance = np.max(np.abs(rgb.astype(np.float32)-bg), axis=2)
        foreground = (distance > tolerance).astype(np.uint8)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        # Background texture may be colourful but low-contrast; combine local texture evidence.
        blur = cv2.GaussianBlur(gray.astype(np.float32), (0,0), 2)
        texture = cv2.GaussianBlur((gray.astype(np.float32)-blur)**2, (0,0), 3)
        minimum = max(12, min(w,h)//45)
        min_area = w*h*settings.min_area
        result = []

        def recurse(box, depth=0):
            x0,y0,x1,y1 = box
            if x1-x0 < minimum or y1-y0 < minimum or area(box) < min_area:
                return
            patch = foreground[y0:y1,x0:x1]
            active_y = np.where(patch.mean(axis=1) > 0.018)[0]
            active_x = np.where(patch.mean(axis=0) > 0.018)[0]
            if not len(active_x) or not len(active_y):
                return
            # Trim document background, not the inside of a native photographic boundary.
            x0,x1 = x0+int(active_x[0]), x0+int(active_x[-1])+1
            y0,y1 = y0+int(active_y[0]), y0+int(active_y[-1])+1
            patch = foreground[y0:y1,x0:x1]
            if min(patch.shape) < minimum or area([x0,y0,x1,y1]) < min_area:
                return
            splits = []
            if depth < 8:
                for axis in (0,1):
                    projection = patch.mean(axis=axis)
                    # A gutter must span virtually the entire current rectangle and be uniform.
                    threshold = 0.008 + settings.gutter_sensitivity * 0.025
                    for start,end in runs(projection < threshold):
                        if start < 3 or len(projection)-end < 3:
                            continue
                        if end-start < max(1, round(min(w,h)/1800)):
                            continue
                        # Avoid splitting a white sky/white studio background unless both regions
                        # have substantial content on either side of the separator.
                        left = patch[:,:start] if axis==0 else patch[:start,:]
                        right = patch[:,end:] if axis==0 else patch[end:,:]
                        if min(left.mean(),right.mean()) > .025 and max(left.mean(),right.mean()) > .24:
                            splits.append((end-start, axis, start, end))
                if splits:
                    _,axis,start,end = max(splits)
                    if axis==0:
                        recurse([x0,y0,x0+start,y1], depth+1)
                        recurse([x0+end,y0,x1,y1], depth+1)
                    else:
                        recurse([x0,y0,x1,y0+start], depth+1)
                        recurse([x0,y0+end,x1,y1], depth+1)
                    return
            fill = float(patch.mean())
            textured = float((texture[y0:y1,x0:x1] > 12).mean())
            if fill < .17 or textured < .015:
                return
            confidence = min(.86, .53 + fill*.22 + min(.11,textured*.2))
            result.append(Detection([float(x0),float(y0),float(x1),float(y1)], confidence, 'OpenCV', reasons=['Raster boundary; inspect white photographic backgrounds']))

        recurse([0,0,w,h])
        # Contours provide separate proposals on irregular layouts where projection cannot split.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
        closed = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel)
        contours,_ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        proposals = []
        for contour in contours:
            x,y,cw,ch = cv2.boundingRect(contour)
            if min(cw,ch) < minimum or cw*ch < min_area:
                continue
            rectangularity = cv2.contourArea(contour) / (cw*ch)
            if rectangularity > .72 and float((texture[y:y+ch,x:x+cw] > 12).mean()) > .015:
                proposals.append(Detection([x,y,x+cw,y+ch], .71, 'OpenCV contour', reasons=['Raster boundary requires review']))
        for p in proposals:
            children=[d for d in result if containment(d.bbox,p.bbox)>.96 and area(d.bbox)<area(p.bbox)*.9]
            if len(children)>=2 and sum(area(d.bbox) for d in children)>area(p.bbox)*.5:
                continue
            if not any(iou(p.bbox,d.bbox)>.65 or containment(p.bbox,d.bbox)>.95 for d in result):
                result.append(p)
        return result
