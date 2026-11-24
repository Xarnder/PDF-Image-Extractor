import json
import math
import uuid
from app.database import store


def edit(job_id, changes, create=None):
    with store.connection() as c:
        before=[]
        after=[]
        for change in changes:
            row=c.execute('SELECT data FROM regions WHERE id=? AND job_id=?',(change['id'],job_id)).fetchone()
            if not row: raise ValueError('Photograph not found')
            region=json.loads(row[0])
            before.append(json.loads(row[0]))
            if change.get('revision') is not None and change['revision']!=region['revision']:
                raise ValueError('This crop changed in another window. Refresh before editing.')
            if 'bbox' in change:
                region['bbox']=validate_bbox(c,job_id,region['page'],change['bbox'])
                region['hashes']={}
                region['duplicate']=None
                source=region.get('source')
                if source:
                    from app.extraction.geometry import containment
                    if containment(region['bbox'],source['bbox'])<.999: source['safe']=False
                region['dimensions']=estimate_dimensions(region,store.raw_job(job_id))
            if 'status' in change:
                if change['status'] not in ('accepted','review','rejected'): raise ValueError('Invalid status')
                region['status']=change['status']
            region['manual']=True
            region['revision']+=1
            after.append(region)
        if create:
            page=create['page']
            bbox=validate_bbox(c,job_id,page,create['bbox'])
            ordinal=c.execute('SELECT coalesce(max(ordinal),0)+1 FROM regions WHERE job_id=? AND page=?',(job_id,page)).fetchone()[0]
            from app.extraction.geometry import containment,area
            sources=[]
            for row in c.execute('SELECT data FROM regions WHERE job_id=? AND page=?',(job_id,page)):
                candidate=json.loads(row[0]).get('source')
                if candidate and candidate.get('safe') and containment(bbox,candidate['bbox'])>.999:
                    sources.append(candidate)
            source=min(sources,key=lambda s:area(s['bbox'])) if sources else None
            region={'id':uuid.uuid4().hex,'job_id':job_id,'page':page,'ordinal':ordinal,'bbox':bbox,'original_bbox':bbox.copy(),
                    'status':'accepted','manual':True,'source':source,'method':'Manual crop','confidence':None,'classification':'User selected',
                    'reasons':[],'hashes':{},'duplicate':None,'revision':1}
            region['dimensions']=estimate_dimensions(region,store.raw_job(job_id))
            after.append(region)
        if not after: raise ValueError('No changes specified')
        c.execute('DELETE FROM history WHERE job_id=? AND undone=1',(job_id,))
        c.execute('INSERT INTO history(job_id,before_json,after_json) VALUES(?,?,?)',(job_id,json.dumps(before),json.dumps(after)))
        for region in after: store.put_region(c,region)
    return after


def validate_bbox(c,job_id,page,b):
    size=c.execute('SELECT width,height FROM pages WHERE job_id=? AND number=?',(job_id,page)).fetchone()
    if not size or len(b)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in b): raise ValueError('Invalid crop coordinates')
    if not (0<=b[0]<b[2]<=size[0]+.01 and 0<=b[1]<b[3]<=size[1]+.01 and b[2]-b[0]>=1 and b[3]-b[1]>=1):
        raise ValueError('Crop must fit inside the page and be at least one PDF point wide and high.')
    return [round(float(v),4) for v in b]


def estimate_dimensions(region,job):
    b=region['bbox']; source=region.get('source')
    dpi=json.loads(job['settings'])['dpi']/72
    if source and source.get('safe'):
        sb=source['bbox']
        a,bb,cc,d,_,_=source['transform']
        dx,dy=(source['width']/abs(a),source['height']/abs(d)) if abs(bb)<.001 else (source['height']/abs(cc),source['width']/abs(bb))
    else: dx=dy=dpi
    return [max(1,round((b[2]-b[0])*dx)),max(1,round((b[3]-b[1])*dy))]


def history(job_id,redo=False):
    with store.connection() as c:
        row=c.execute('SELECT * FROM history WHERE job_id=? AND undone=? ORDER BY id '+('ASC' if redo else 'DESC')+' LIMIT 1',(job_id,1 if redo else 0)).fetchone()
        if not row: return False
        previous=json.loads(row['before_json']); following=json.loads(row['after_json'])
        target=following if redo else previous
        ids={r['id'] for r in previous+following}
        for rid in ids: c.execute('DELETE FROM regions WHERE id=? AND job_id=?',(rid,job_id))
        for region in target: store.put_region(c,region)
        c.execute('UPDATE history SET undone=? WHERE id=?',(0 if redo else 1,row['id']))
    return True
