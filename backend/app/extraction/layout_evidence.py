"""Keep native photographs intact unless independent rectangular boundaries are clear."""
import cv2
import numpy as np
import pymupdf as fitz
from app.extraction.geometry import area, containment, iou, intersect


def text_boxes(page):
    blocks = page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']
    return [list(fitz.Rect(line['bbox']) * page.rotation_matrix)
            for block in blocks if block['type'] == 0 for line in block['lines']]


def text_coverage(bbox, boxes):
    # Union area prevents overlapping text spans from inflating the evidence.
    intersections = [intersect(bbox, b) for b in boxes if area(intersect(bbox, b)) > 0]
    if not intersections:
        return 0.0
    xs = sorted({x for b in intersections for x in (b[0], b[2])})
    total = 0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((b[1], b[3]) for b in intersections if b[0] < right and b[2] > left)
        end = -float('inf')
        for low, high in spans:
            total += max(0, high-max(low, end))*(right-left)
            end = max(end, high)
    return min(1.0, total/max(1e-9, area(bbox)))


def edge_support(image, bbox):
    """Fraction of each straight side supported by a persistent colour boundary."""
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32)
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    support = []
    for axis, coordinate, begin, end in ((0,x0,y0,y1),(0,x1,y0,y1),(1,y0,x0,x1),(1,y1,x0,x1)):
        limit = w if axis == 0 else h
        other = h if axis == 0 else w
        if coordinate <= 1 or coordinate >= limit-1:
            support.append(1.0)
            continue
        inset = max(2, (end-begin)//20)
        start, stop = max(0,begin+inset), min(other,end-inset)
        best = 0
        if stop > start:
            for offset in range(-3,4):
                at = coordinate+offset
                if at < 2 or at >= limit-2:
                    continue
                if axis == 0:
                    a = rgb[start:stop,at-2:at].mean(axis=1)
                    b = rgb[start:stop,at:at+2].mean(axis=1)
                else:
                    a = rgb[at-2:at,start:stop].mean(axis=0)
                    b = rgb[at:at+2,start:stop].mean(axis=0)
                best = max(best, float((np.max(np.abs(a-b),axis=1)>14).mean()))
        support.append(best)
    return support


def separate_photographs(image, parent, children, sx, sy):
    bounded = []
    for child in children:
        b = child.bbox
        edges = edge_support(image, [b[0]/sx,b[1]/sy,b[2]/sx,b[3]/sy])
        if sum(value >= .60 for value in edges) >= 3 and min(edges) >= .22:
            bounded.append(child)
    if len(bounded) < 2 or sum(area(d.bbox) for d in bounded) < area(parent.bbox)*.30:
        return []
    if any(iou(a.bbox,b.bbox)>.08 for i,a in enumerate(bounded) for b in bounded[i+1:]):
        return []
    return bounded


def preserves_faces(parent_bbox, children, faces):
    for face in faces:
        b = [parent_bbox[0]+face[0]*(parent_bbox[2]-parent_bbox[0]),
             parent_bbox[1]+face[1]*(parent_bbox[3]-parent_bbox[1]),
             parent_bbox[0]+face[2]*(parent_bbox[2]-parent_bbox[0]),
             parent_bbox[1]+face[3]*(parent_bbox[3]-parent_bbox[1])]
        if not any(containment(b,child.bbox)>=.98 for child in children):
            return False
    return True


def protect_native(native, visual, boxes):
    result = []
    for proposal in visual:
        if text_coverage(proposal.bbox, boxes) > .40:
            continue
        # Foreground fragments and enclosing page decorations are not new photos.
        if any(containment(proposal.bbox,n.bbox)>.94 for n in native):
            continue
        if any(containment(n.bbox,proposal.bbox)>.90 and area(proposal.bbox)>area(n.bbox)*1.12 for n in native):
            continue
        result.append(proposal)
    return result
