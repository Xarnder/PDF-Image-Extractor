import time
import uuid
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from app.core.config import Settings, DATA, check_disk
from app.extraction.native_pdf import placements, verify_visible, oriented_source
from app.extraction.page_renderer import render, save_preview
from app.extraction.opencv_detector import OpenCVDetector
from app.extraction.boundary_refinement import refine
from app.extraction.detection_fusion import fuse
from app.extraction.photo_classifier import classify
from app.extraction.duplicate_detector import hashes
from app.extraction.geometry import area, containment, intersect
from app.extraction.ai_detector import detect_optional, model_status


def process_page(path, job_id, number, config):
    started = time.monotonic()
    settings = Settings.model_validate(config)
    check_disk(DATA)
    cache = DATA / 'cache' / job_id
    cache.mkdir(parents=True, exist_ok=True)
    with fitz.open(path) as doc:
        page = doc[number-1]
        im = render(page, 180 if settings.mode == 'maximum' else 120, max_pixels=min(settings.max_pixels,12000000))
        small = im.copy()
        small.thumbnail((1400,2000))
        save_preview(small,cache / f'page-{number}.jpg')
        small.thumbnail((180,240))
        save_preview(small,cache / f'thumb-{number}.jpg',quality=80)
        sx,sy = page.rect.width/im.width,page.rect.height/im.height
        native = placements(page, settings)
        visual = []
        device, warnings = 'CPU', []
        engines=['Native PDF']
        if settings.mode != 'native':
            engines.append('OpenCV')
            detector = OpenCVDetector()
            visual = detector.detect(im,settings)
            if settings.mode == 'maximum':
                half = im.resize((im.width//2,im.height//2),Image.Resampling.LANCZOS)
                for d in detector.detect(half,settings):
                    d.bbox = [d.bbox[0]*im.width/half.width,d.bbox[1]*im.height/half.height,d.bbox[2]*im.width/half.width,d.bbox[3]*im.height/half.height]
                    d.method = 'OpenCV multiscale'
                    visual.append(d)
            ai,device,warnings = detect_optional(im,settings)
            if settings.ai_enabled and settings.mode in ('balanced','maximum') and model_status()['available'] and not any('Heron failed' in w for w in warnings):
                engines.append('Heron')
            visual += ai
            visual = fuse([], visual)
            for d in visual:
                refine(d,im,settings.refinement)
                d.bbox = [d.bbox[0]*sx,d.bbox[1]*sy,d.bbox[2]*sx,d.bbox[3]*sy]
        keep = []
        clips=[p for p in page.get_drawings(extended=True) if p.get('type')=='clip' and len(p.get('items',[]))==1 and p['items'][0][0]=='re']
        for n in native:
            children = [d for d in visual if containment(d.bbox,n.bbox)>.96 and area(d.bbox) < area(n.bbox)*.86]
            composite = len(children)>=2 and sum(area(d.bbox) for d in children)>area(n.bbox)*.3
            covers_page = area(n.bbox)/area(list(page.rect))>.80
            if settings.mode != 'native' and (composite or (covers_page and children)):
                # Assign the composite source to children only after validating the placement.
                n.source['safe'] = verify_visible(doc,page,n,im,settings)
                for child in children:
                    child.source = dict(n.source)
                    child.method += ' · source crop'
                continue
            n.source['safe'] = verify_visible(doc,page,n,im,settings)
            # A single rectangular clip on a single source can be associated without
            # guessing at nested graphics-state scopes. More complex clips render.
            if not n.source['safe'] and len(native)==1 and len(clips)==1:
                clip=list(fitz.Rect(clips[0]['scissor'])*page.rotation_matrix)
                clipped=intersect(n.bbox,clip)
                if area(clipped)>1 and area(clipped)<area(n.bbox)*.98:
                    previous=n.bbox
                    n.bbox=clipped
                    if verify_visible(doc,page,n,im,settings):
                        n.source['safe']=True
                        n.method+=' · rectangular clip'
                        covers_page=False
                    else:
                        n.bbox=previous
            if covers_page:
                n.reasons.append('Page-sized source; confirm this is one photograph')
            if not n.source['safe']:
                n.reasons.append('Clipping, transparency, or transform requires page rendering')
            keep.append(n)
        detections = fuse(keep, visual)
        regions = []
        for i,d in enumerate(detections):
            d.bbox = intersect(d.bbox,list(page.rect))
            if area(d.bbox)<1:
                continue
            box = [round(d.bbox[0]/sx),round(d.bbox[1]/sy),round(d.bbox[2]/sx),round(d.bbox[3]/sy)]
            crop = im.crop(box)
            label,certainty,reasons = classify(crop)
            d.reasons += reasons
            native_safe = bool(d.source and d.source['safe'])
            status = 'accepted' if native_safe and certainty>=.85 and not any('Page-sized' in r or 'disagree' in r for r in d.reasons) else 'review'
            raw = None
            if native_safe:
                try:
                    crop,payload = oriented_source(doc,d.source,d.bbox,settings.max_pixels)
                    if all(abs(a-b)<.1 for a,b in zip(d.bbox,d.source['bbox'])):
                        raw = payload['image']
                except Exception as exc:
                    d.source['safe'] = False
                    d.reasons.append(f'Source crop unavailable: {exc}')
                    status='review'
            rid = uuid.uuid4().hex
            dims = list(crop.size)
            fingerprint = hashes(crop,raw)
            crop.thumbnail((320,320))
            save_preview(crop.convert('RGB'),cache/f'{rid}.jpg')
            regions.append({'id':rid,'job_id':job_id,'page':number,'ordinal':i+1,'bbox':d.bbox,'original_bbox':d.bbox.copy(),
                            'status':status,'manual':False,'source':d.source,'dimensions':dims,'method':d.method,
                            'confidence':round(d.confidence,3),'classification':label,'reasons':d.reasons,
                            'hashes':fingerprint,'duplicate':None,'revision':0})
    return {'regions':regions,'seconds':time.monotonic()-started,'device':device,'warnings':warnings,'engines':engines}
