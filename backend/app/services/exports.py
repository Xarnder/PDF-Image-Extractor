import json
import threading
import time
import uuid
import zipfile
import queue
from pathlib import Path
from app.core.config import DATA, Settings, check_disk, safe_name
from app.database import store
from app.jobs.worker import IsolatedWorker

_lock=threading.Lock()
_active=set()
_queue=queue.Queue(maxsize=32)
_thread=None
_stop=threading.Event()


def export_loop():
    while not _stop.is_set():
        try: task=_queue.get(timeout=.2)
        except queue.Empty: continue
        try: run_export(*task)
        finally: _queue.task_done()


def shutdown():
    _stop.set()
    if _thread: _thread.join(5)
    while True:
        try:
            task=_queue.get_nowait()
            with _lock: _active.discard(task[1]['id'])
            _queue.task_done()
        except queue.Empty: break
    with store.connection() as c:
        c.execute("UPDATE exports SET status='failed',error='Application stopped; retry export to a new folder' WHERE status IN ('running','queued')")


def start_export(job_id, options):
    global _thread
    job=store.raw_job(job_id)
    config=Settings.model_validate_json(job['settings']).model_dump()
    for key in ('format','jpeg_quality','preference','dpi','resolution','padding','preserve_metadata','jpeg_background'):
        if key in options: config[key]=options[key]
    config=Settings.model_validate(config)
    regions=store.regions(job_id)
    ids=options.get('ids',[])
    statuses=options.get('statuses',['accepted'])
    start,end=options.get('page_from',1),options.get('page_to',job['total'])
    selected=[r for r in regions if r['status'] in statuses and start<=r['page']<=end and (not ids or r['id'] in ids)]
    if not selected: raise ValueError('No photographs match this export selection.')
    export_id=uuid.uuid4().hex
    with _lock:
        if job_id in _active: raise ValueError('An export for this document is already running.')
        if _queue.full(): raise ValueError('The export queue is full. Wait for an export to finish.')
        with store.connection() as c:
            c.execute('INSERT INTO exports(id,job_id,status,total,created) VALUES(?,?,?,?,?)',(export_id,job_id,'queued',len(selected),time.time()))
        _active.add(job_id)
        _queue.put_nowait((export_id,job,selected,config,options))
        if not _thread or not _thread.is_alive():
            _stop.clear()
            _thread=threading.Thread(target=export_loop,daemon=True,name='export-queue')
            _thread.start()
    return {'id':export_id,'total':len(selected),'status':'queued'}


def run_export(export_id,job,regions,config,options):
    worker=IsolatedWorker()
    try:
        with store.connection() as c: c.execute("UPDATE exports SET status='running' WHERE id=?",(export_id,))
        # The root is a saved local user preference. HTTP export requests cannot pick arbitrary paths.
        root=Path(store.settings().output_directory).expanduser() if store.settings().output_directory else DATA/'exports'
        if not root.is_absolute(): raise ValueError('Output directory must be an absolute local path.')
        root=root.resolve()
        root.mkdir(parents=True,exist_ok=True)
        check_disk(root)
        folder=root/(safe_name(Path(job['name']).stem)+'_'+time.strftime('%Y%m%d_%H%M%S')+'_'+export_id[:8])
        folder.mkdir(mode=0o700)
        with store.connection() as c: c.execute('UPDATE exports SET path=? WHERE id=?',(str(folder),export_id))
        manifest=[]
        skipped=[]
        hashes=set()
        used_names=set()
        for i,region in enumerate(regions):
            if _stop.is_set(): raise InterruptedError('Export interrupted by shutdown; completed image files are retained.')
            exact=region.get('hashes',{}).get('pixel_hash')
            if config.skip_exact_duplicates and exact and exact in hashes:
                skipped.append(region['id'])
            else:
                if exact: hashes.add(exact)
                check_disk(root,64*1024*1024)
                naming=options.get('naming','page')
                name=f'page_{region["page"]:03d}_image_{region["ordinal"]:03d}'
                if naming=='sequential': name=f'image_{i+1:05d}'
                if naming=='source': name=f'xref_{(region.get("source") or {}).get("xref",0)}_{i+1:05d}'
                if naming=='document': name=safe_name(Path(job['name']).stem)+'_'+name
                if options.get('prefix'): name=safe_name(options['prefix'])+'_'+name
                if name in used_names: name+='_'+region['id'][:8]
                used_names.add(name)
                target=folder/('needs_review' if region['status']=='review' else 'rejected' if region['status']=='rejected' else '')
                target.mkdir(exist_ok=True)
                output,dims,method=worker.call('app.extraction.exporter','export_one',(job['path'],region,config.model_dump(),str(target/name)),config.page_timeout,config.memory_mb,cancelled=_stop.is_set)
                manifest.append({**region,'output_filename':str(Path(output).relative_to(folder)),'output_dimensions':dims,'extraction_method':method})
            with store.connection() as c: c.execute('UPDATE exports SET completed=? WHERE id=?',(i+1,export_id))
        metadata={'source_pdf':job['name'],'fingerprint':job['fingerprint'],'settings':config.model_dump(),'images':manifest}
        report={'exported':len(manifest),'skipped_exact_duplicates':skipped,'job':store.job(job['id']),'failed_pages':[]}
        with store.connection() as c:
            report['failed_pages']=[dict(r) for r in c.execute("SELECT number,error FROM pages WHERE job_id=? AND status='failed'",(job['id'],))]
        for name,content in (('metadata.json',metadata),('extraction_report.json',report)):
            temp=folder/(name+'.part')
            temp.write_text(json.dumps(content,indent=2))
            temp.replace(folder/name)
        archive=DATA/'exports'/f'{export_id}.zip'
        with zipfile.ZipFile(archive.with_suffix('.part'),'w',zipfile.ZIP_STORED,allowZip64=True) as z:
            for path in folder.rglob('*'):
                if _stop.is_set(): raise InterruptedError('ZIP creation interrupted; image folder is retained.')
                if path.is_file(): z.write(path,path.relative_to(folder))
        archive.with_suffix('.part').replace(archive)
        with store.connection() as c: c.execute("UPDATE exports SET status='completed' WHERE id=?",(export_id,))
    except Exception as exc:
        with store.connection() as c: c.execute("UPDATE exports SET status='failed',error=? WHERE id=?",(str(exc),export_id))
    finally:
        worker.close()
        with _lock: _active.discard(job['id'])
