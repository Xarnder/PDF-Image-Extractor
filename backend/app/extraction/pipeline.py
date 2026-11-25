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
from app.extraction.photo_classifier import assess
from app.extraction.content_analysis import analyze
from app.extraction.layout_evidence import text_boxes, text_coverage, separate_photographs, protect_native, preserves_faces
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
        pdf_text = text_boxes(page)
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
            children = [d for d in children if text_coverage(d.bbox,pdf_text)<.40]
            separate = separate_photographs(im,n,children,sx,sy) if settings.mode!='native' else []
            width,height=n.bbox[2]-n.bbox[0],n.bbox[3]-n.bbox[1]
            if max(width/height,height/width)>4 and area(n.bbox)<area(list(page.rect))*.15:
                # A banner's illustration and text can look like two framed pictures.
                # Keep its shared source intact so content validation sees the context.
                separate=[]
            if separate and settings.face_priority:
                parent_crop=im.crop([round(n.bbox[0]/sx),round(n.bbox[1]/sy),round(n.bbox[2]/sx),round(n.bbox[3]/sy)])
                parent_evidence,_,notes=analyze([parent_crop],settings.content_analysis and settings.mode in ('balanced','maximum'))
                warnings += notes
                if not preserves_faces(n.bbox,separate,parent_evidence[0].get('faces',[])):
                    separate=[]
                    n.reasons.append('Face priority: ambiguous split would cut or omit a face; original photograph retained')
            covers_page = area(n.bbox)/area(list(page.rect))>.80
            if separate:
                # Assign the composite source to children only after validating the placement.
                n.source['safe'] = verify_visible(doc,page,n,im,settings)
                for child in separate:
                    child.source = dict(n.source)
                    child.method += ' · source crop'
                # Do not leave an additional contour spanning the whole flattened page.
                visual = [d for d in visual if d in separate or containment(d.bbox,n.bbox)<.94]
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
        visual = protect_native(keep,visual,pdf_text)
        detections = fuse(keep, visual)
        crops=[]
        for d in detections:
            probe=im.crop([round(d.bbox[0]/sx),round(d.bbox[1]/sy),round(d.bbox[2]/sx),round(d.bbox[3]/sy)])
            if d.source:
                try:
                    probe,_=oriented_source(doc,d.source,d.bbox,settings.max_pixels)
                except (ValueError,RuntimeError,OSError,ZeroDivisionError): pass
            if probe.mode in ('RGBA','LA'):
                rgba=probe.convert('RGBA');probe=Image.new('RGB',rgba.size,'white');probe.paste(rgba,mask=rgba.getchannel('A'))
            probe.thumbnail((1100,1100))
            crops.append(probe)
        evidence,content_engine,content_warnings = analyze(crops,settings.content_analysis and settings.mode in ('balanced','maximum'))
        if content_engine:
            engines.append(content_engine)
        warnings += content_warnings
        regions = []
        for i,d in enumerate(detections):
            d.bbox = intersect(d.bbox,list(page.rect))
            if area(d.bbox)<1:
                continue
            box = [round(d.bbox[0]/sx),round(d.bbox[1]/sy),round(d.bbox[2]/sx),round(d.bbox[3]/sy)]
            crop = im.crop(box)
            label,certainty,reasons,decision = assess(crops[i],evidence[i],native=bool(d.source),
                                                     pdf_text=text_coverage(d.bbox,pdf_text),face_priority=settings.face_priority)
            if area(d.bbox)>area(list(page.rect))*.8 and not evidence[i].get('faces'):
                inset=[n for n in native if n is not d and containment(n.bbox,d.bbox)>.95 and area(n.bbox)<area(d.bbox)*.75]
                if inset and sum(area(n.bbox) for n in inset)>area(d.bbox)*.18 and text_coverage(d.bbox,pdf_text)>.05:
                    label,decision='Page background / composite','rejected'
                    reasons.append('Text-heavy page background behind separate image placements')
            d.reasons += reasons
            native_safe = bool(d.source and d.source['safe'])
            status = 'accepted' if native_safe and certainty>=.85 and not any('Page-sized' in r or 'disagree' in r for r in d.reasons) else 'review'
            if decision:
                status = decision
            raw = None
            if native_safe:
                try:
                    crop,payload = oriented_source(doc,d.source,d.bbox,settings.max_pixels)
                    if all(abs(a-b)<.1 for a,b in zip(d.bbox,d.source['bbox'])):
                        raw = payload['image']
                except Exception as exc:
                    d.source['safe'] = False
                    d.reasons.append(f'Source crop unavailable: {exc}')
                    if status!='rejected': status='review'
            rid = uuid.uuid4().hex
            dims = list(crop.size)
            fingerprint = hashes(crop,raw)
            crop.thumbnail((320,320))
            save_preview(crop.convert('RGB'),cache/f'{rid}.jpg')
            regions.append({'id':rid,'job_id':job_id,'page':number,'ordinal':i+1,'bbox':d.bbox,'original_bbox':d.bbox.copy(),
                            'status':status,'manual':False,'source':d.source,'dimensions':dims,'method':d.method,
                            'confidence':round(d.confidence,3),'classification':label,'reasons':d.reasons,
                            'faces':[[d.bbox[0]+b[0]*(d.bbox[2]-d.bbox[0]),d.bbox[1]+b[1]*(d.bbox[3]-d.bbox[1]),
                                      d.bbox[0]+b[2]*(d.bbox[2]-d.bbox[0]),d.bbox[1]+b[3]*(d.bbox[3]-d.bbox[1])] for b in evidence[i].get('faces',[])],
                            'content_analysis':{'backend':evidence[i].get('backend'),'labels':evidence[i].get('labels',[])[:8]},
                            'hashes':fingerprint,'duplicate':None,'revision':0})
    return {'regions':regions,'seconds':time.monotonic()-started,'device':device,'warnings':warnings,'engines':engines}
