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


def assess(image, evidence, *, native=False, pdf_text=0, face_priority=True):
    """Content evidence can reject graphics; faces break uncertainty, not known book layouts.

    A face is never a crop target by itself. The caller keeps the enclosing photographic
    boundary, including the body/background. No-face photographs remain eligible.
    """
    label, certainty, reasons = classify(image)
    labels = {x['label']:float(x['score']) for x in evidence.get('labels',[])}
    faces = evidence.get('faces',[])
    face_area = max(((b[2]-b[0])*(b[3]-b[1]) for b in faces), default=0)
    texts = evidence.get('texts',[])
    text_area = min(1, sum((t['box'][2]-t['box'][0])*(t['box'][3]-t['box'][1]) for t in texts))
    document = labels.get('document',0)
    printed = max(labels.get('book',0), labels.get('magazine',0), labels.get('printed_page',0))
    graphic = max(labels.get('illustrations',0),labels.get('diagram',0),labels.get('chart',0))
    ratio = max(image.width/max(1,image.height),image.height/max(1,image.width))
    rejection = None
    if (printed >= .14 and document >= .15) or (labels.get('book',0)>=.10 and document>=.10 and face_area<.02):
        rejection = ('Book / printed layout', 'Printed page or book mockup; faces inside a printed layout are not separate photographs')
    elif document >= .20 and labels.get('screenshot',0)>=.16 and len(texts)>=5 and face_area<.02:
        rejection = ('Document / promotional graphic', 'Dense printed text and document-layout evidence')
    elif document>=.075 and labels.get('screenshot',0)>=.07 and len(texts)>=8 and not faces:
        rejection = ('Document / promotional graphic', 'Repeated printed text with document-layout evidence and no subject face')
    elif (document>=.45 and texts and face_area<.02) or (pdf_text>.55 and not faces) or (text_area>.25 and not faces):
        rejection = ('Text / logo', 'Text or logo occupies the detected region')
    elif graphic>=.35 or labels.get('painting',0)>=.20 or (graphic>=.15 and not faces and graphic>labels.get('people',0)):
        rejection = ('Illustration / artwork', 'Illustration or painting evidence; retained as rejected for manual recovery')
    elif ratio>4 and (text_area>.04 or len(texts)>=2 or label=='Graphic / low-detail region'):
        rejection = ('Text / banner', 'Elongated text or graphic banner')
    elif label=='Graphic / low-detail region' and not faces:
        rejection = ('Graphic / logo', 'Low visual complexity without photographic or face evidence')
    elif not native and pdf_text>.35 and not faces:
        rejection = ('Text / logo', 'Detected rectangle agrees with PDF text rather than an image placement')
    if rejection:
        return rejection[0], certainty, [rejection[1]], 'rejected'
    if faces and face_priority:
        reasons.append('Face priority: preserve the enclosing photograph, including the complete face, body and background')
        if certainty<.85:
            return 'Photograph candidate with face', certainty, reasons, 'review'
    if evidence.get('backend')!='Apple Vision' and text_area>.05:
        reasons.append('Semantic content analysis unavailable; inspect printed content')
    return label, certainty, reasons, None
