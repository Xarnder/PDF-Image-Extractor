import asyncio
import hashlib
import json
import logging
import os
import platform
import secrets
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse, unquote
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from app.core.config import DATA, ROOT, Settings, safe_name, check_disk
from app.database import store
from app.jobs.manager import manager
from app.jobs.worker import IsolatedWorker
from app.services import edits, exports
from app.extraction.ai_detector import model_status

TOKEN=secrets.token_urlsafe(32)
io_worker=IsolatedWorker()
io_lock=threading.Lock()
model_download={'status':'idle','error':None}


def io_call(module,name,args):
    config=store.settings()
    with io_lock:
        return io_worker.call(module,name,args,config.page_timeout,config.memory_mb)


@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.FileHandler(ROOT/'logs'/'app.log'),logging.StreamHandler()])
    store.init()
    # Only incomplete uploads and transient export files are removed automatically.
    for path in (DATA/'documents').glob('*.part'): path.unlink(missing_ok=True)
    manager.start()
    yield
    manager.close()
    exports.shutdown()
    io_worker.close()


app=FastAPI(title='PDF Image Extractor',lifespan=lifespan,docs_url=None,redoc_url=None)


@app.middleware('http')
async def local_security(request: Request,call_next):
    host=request.headers.get('host','')
    hostname=host.split(':')[0]
    if hostname not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'Localhost access only'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin!=f'http://{host}':
        return JSONResponse({'detail':'Cross-origin request denied'},status_code=403)
    if request.headers.get('sec-fetch-site')=='cross-site':
        return JSONResponse({'detail':'Cross-site request denied'},status_code=403)
    if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD'):
        if not secrets.compare_digest(request.headers.get('x-local-token',''),TOKEN):
            return JSONResponse({'detail':'Invalid local session token. Reload the application.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cross-Origin-Resource-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response


@app.exception_handler(ValueError)
async def value_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=400)


@app.exception_handler(KeyError)
async def missing_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=404)


@app.get('/api/health')
def health(): return {'ok':True,'version':'1.0.0'}


@app.get('/api/session')
def session():
    return {'token':TOKEN,'settings':store.settings().model_dump(),'models':[model_status()],
            'engines':['Native PDF','OpenCV'],'platform':platform.machine(),'worker_peak_mb':round(manager.peak_mb,1),
            'data_directory':str(DATA)}


@app.put('/api/settings')
def put_settings(config: Settings):
    if config.output_directory:
        path=Path(config.output_directory).expanduser()
        if not path.is_absolute() or '\x00' in str(path): raise ValueError('Output directory must be an absolute path.')
        # Export creates a unique child directory and never overwrites existing files.
        config.output_directory=str(path.resolve())
    store.save_settings(config)
    return config.model_dump()


@app.get('/api/jobs')
def list_jobs():
    with store.connection() as c: ids=[r[0] for r in c.execute('SELECT id FROM jobs ORDER BY created DESC')]
    return [store.job(i) for i in ids]


@app.post('/api/jobs')
async def upload(request: Request):
    check_disk(DATA)
    name=safe_name(unquote(request.headers.get('x-filename','document.pdf')))
    if not name.lower().endswith('.pdf'): raise ValueError('Select a PDF file.')
    job_id=uuid.uuid4().hex
    target=DATA/'documents'/f'{job_id}.pdf'
    partial=target.with_suffix('.part')
    size=0
    fingerprint=hashlib.sha256()
    config=store.settings()
    if request.headers.get('x-mode'):
        config=Settings.model_validate({**config.model_dump(),'mode':request.headers['x-mode']})
    try:
        with partial.open('xb') as file:
            os.chmod(partial,0o600)
            async for chunk in request.stream():
                size+=len(chunk)
                if size>4*1024**3: raise ValueError('PDF exceeds the 4 GB upload limit.')
                if size//(32*1024**2)!=(size-len(chunk))//(32*1024**2): check_disk(DATA)
                file.write(chunk)
                fingerprint.update(chunk)
        with partial.open('rb') as file:
            if b'%PDF-' not in file.read(1024): raise ValueError('File does not contain a PDF signature.')
        pages=await asyncio.to_thread(io_call,'app.extraction.page_renderer','inspect_pdf',(str(partial),unquote(request.headers.get('x-pdf-password',''))))
        partial.replace(target)
        with store.connection() as c:
            c.execute('INSERT INTO jobs(id,name,fingerprint,path,status,total,settings,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                      (job_id,name,fingerprint.hexdigest(),str(target),'ready',len(pages),config.model_dump_json(),time.time(),time.time()))
            c.executemany('INSERT INTO pages(job_id,number,width,height) VALUES(?,?,?,?)',[(job_id,i+1,*p) for i,p in enumerate(pages)])
        return store.job(job_id)
    except BaseException:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        Path(str(partial)+'.unlocked').unlink(missing_ok=True)
        raise


@app.get('/api/jobs/{job_id}')
def get_job(job_id:str): return store.job(job_id)


class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: str
    page: int | None = Field(None,ge=1)


@app.post('/api/jobs/{job_id}/action')
def job_action(job_id:str,body:Action):
    job=store.job(job_id)
    action=body.action
    if action in ('start','resume','retry','redetect'):
        with manager.lock:
            if job_id in manager.active:
                raise ValueError('The current page is finishing. Try again when the job is paused.')
            with store.connection() as c:
                if action=='retry': c.execute("UPDATE pages SET status='pending',error=NULL WHERE job_id=? AND status='failed'",(job_id,))
                if action=='redetect':
                    if not body.page or body.page>job['total']: raise ValueError('Select a valid page.')
                    c.execute("UPDATE pages SET status='pending',error=NULL WHERE job_id=? AND number=?",(job_id,body.page))
                c.execute("UPDATE jobs SET status='queued',stage='Waiting in queue',error=NULL WHERE id=?",(job_id,))
    elif action=='pause': store.update_job(job_id,status='paused',stage='Pausing after current page')
    elif action=='cancel': store.update_job(job_id,status='cancelled',stage='Cancelled · completed pages retained')
    else: raise ValueError('Unknown action')
    return store.job(job_id)


@app.delete('/api/jobs/{job_id}')
def delete_job(job_id:str):
    job=store.raw_job(job_id)
    with manager.lock:
        if job_id in manager.active: raise ValueError('Pause this job and wait for the current page before removing it.')
        with store.connection() as c:
            if c.execute("SELECT 1 FROM exports WHERE job_id=? AND status IN ('running','queued')",(job_id,)).fetchone(): raise ValueError('Wait for export to finish.')
            c.execute('DELETE FROM exports WHERE job_id=?',(job_id,))
            c.execute('DELETE FROM jobs WHERE id=?',(job_id,))
        Path(job['path']).unlink(missing_ok=True)
        shutil.rmtree(DATA/'cache'/job_id,ignore_errors=True)
    return {'ok':True}


@app.get('/api/jobs/{job_id}/events')
async def events(job_id:str,request:Request):
    store.job(job_id)
    async def stream():
        previous=None
        while not await request.is_disconnected():
            data=json.dumps(store.job(job_id))
            if data!=previous:
                yield f'data: {data}\n\n'
                previous=data
            else: yield ': heartbeat\n\n'
            await asyncio.sleep(.75)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})


@app.get('/api/jobs/{job_id}/pages')
def pages(job_id:str):
    store.raw_job(job_id)
    with store.connection() as c:
        rows=c.execute('''SELECT p.*,count(r.id) AS photographs,
                       sum(CASE WHEN r.status='review' THEN 1 ELSE 0 END) AS review
                       FROM pages p LEFT JOIN regions r ON r.job_id=p.job_id AND r.page=p.number
                       WHERE p.job_id=? GROUP BY p.number ORDER BY p.number''',(job_id,)).fetchall()
    return [dict(r) for r in rows]


@app.get('/api/jobs/{job_id}/pages/{number}/preview')
async def page_preview(job_id:str,number:int,thumb:bool=False):
    job=store.raw_job(job_id)
    if not 1<=number<=job['total']: raise HTTPException(404)
    target=DATA/'cache'/job_id/f'{"thumb" if thumb else "page"}-{number}.jpg'
    if not target.exists():
        await asyncio.to_thread(io_call,'app.extraction.page_renderer','preview',(job['path'],number,str(target),180 if thumb else 1400))
    return FileResponse(target,media_type='image/jpeg')


@app.get('/api/jobs/{job_id}/regions')
def get_regions(job_id:str,page:int | None=None,status:str | None=None,offset:int=0,limit:int=60,sort:str='page'):
    items=store.regions(job_id,page)
    if status and status!='all': items=[r for r in items if r['status']==status]
    if sort=='resolution': items.sort(key=lambda r:r['dimensions'][0]*r['dimensions'][1],reverse=True)
    if sort=='confidence': items.sort(key=lambda r:r['confidence'] or 0)
    limit=min(500,max(1,limit)); offset=max(0,offset)
    return {'items':items[offset:offset+limit],'total':len(items)}


@app.post('/api/jobs/{job_id}/edits')
def edit_regions(job_id:str,body:dict):
    return edits.edit(job_id,body.get('changes',[]),body.get('create'))


@app.post('/api/jobs/{job_id}/history')
def undo_redo(job_id:str,body:dict): return {'changed':edits.history(job_id,body.get('redo',False))}


def find_region(job_id,rid):
    with store.connection() as c:
        row=c.execute('SELECT data FROM regions WHERE job_id=? AND id=?',(job_id,rid)).fetchone()
    if not row: raise HTTPException(404)
    return json.loads(row[0])


@app.get('/api/jobs/{job_id}/regions/{rid}/image')
async def region_image(job_id:str,rid:str,thumb:bool=False,format:str='png',preference:str='auto',download:bool=False):
    job=store.raw_job(job_id)
    region=find_region(job_id,rid)
    target=DATA/'cache'/job_id/f'{rid}.jpg'
    if thumb and region['revision']==0 and target.exists(): return FileResponse(target,media_type='image/jpeg')
    config=Settings.model_validate_json(job['settings']).model_dump()
    config.update(format=format,preference=preference,padding=0)
    data,ext,dims,method=await asyncio.to_thread(io_call,'app.extraction.exporter','extract',(job['path'],region,config))
    if thumb:
        import io
        from PIL import Image
        im=Image.open(io.BytesIO(data)); im.thumbnail((320,320)); out=io.BytesIO(); im.convert('RGB').save(out,format='JPEG',quality=85)
        data=out.getvalue(); ext='jpg'
    headers={'Content-Disposition':f'attachment; filename="page_{region["page"]:03d}_image_{region["ordinal"]:03d}.{ext}"'} if download else {}
    return Response(data,media_type='image/jpeg' if ext in ('jpg','jpeg') else f'image/{ext}',headers=headers)


@app.post('/api/jobs/{job_id}/exports')
def begin_export(job_id:str,body:dict): return exports.start_export(job_id,body)


@app.get('/api/exports/{export_id}')
def export_status(export_id:str):
    with store.connection() as c: row=c.execute('SELECT * FROM exports WHERE id=?',(export_id,)).fetchone()
    if not row: raise HTTPException(404)
    return dict(row)


@app.get('/api/exports/{export_id}/download')
def download_export(export_id:str):
    value=export_status(export_id)
    if value['status']!='completed': raise ValueError('Export is not complete.')
    return FileResponse(DATA/'exports'/f'{export_id}.zip',filename='extracted_images.zip',media_type='application/zip')


@app.get('/api/models')
def models(): return {'models':[model_status()],'download':model_download}


@app.post('/api/models/heron/download')
def download_model():
    if not model_status()['dependencies']: raise ValueError(model_status()['error'])
    if model_download['status']=='downloading': return model_download
    model_download.update(status='downloading',error=None)
    def run():
        try:
            from huggingface_hub import snapshot_download, model_info
            from app.extraction.ai_detector import MODEL_PATH
            revision=model_info('docling-project/docling-layout-heron').sha
            snapshot_download('docling-project/docling-layout-heron',revision=revision,local_dir=MODEL_PATH,
                              allow_patterns=['config.json','preprocessor_config.json','model.safetensors','README.md','LICENSE*'])
            (MODEL_PATH/'REVISION').write_text(revision)
            model_download['status']='completed'
        except Exception as exc: model_download.update(status='failed',error=str(exc))
    threading.Thread(target=run,daemon=True).start()
    return model_download


dist=ROOT/'frontend'/'dist'
if dist.exists():
    app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
