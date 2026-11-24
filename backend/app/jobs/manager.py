import json
import logging
import threading
import time
from app.database import store
from app.core.config import Settings
from app.extraction.geometry import iou
from app.extraction.duplicate_detector import relationship
from app.jobs.worker import IsolatedWorker

log=logging.getLogger('extractor')


class JobManager:
    def __init__(self):
        self.stop_event=threading.Event()
        self.threads=[]
        self.active=set()
        self.lock=threading.Lock()
        self.peak_mb=0

    def start(self):
        for slot in range(4):
            thread=threading.Thread(target=self.loop,args=(slot,),daemon=True,name=f'job-{slot}')
            thread.start()
            self.threads.append(thread)

    def claim(self):
        with self.lock, store.connection() as c:
            row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row: return None
            c.execute("UPDATE jobs SET status='running',stage='Preparing page analysis' WHERE id=?",(row['id'],))
            self.active.add(row['id'])
            return dict(row)

    def loop(self,slot):
        worker=IsolatedWorker()
        try:
            while not self.stop_event.is_set():
                if slot>=store.settings().workers:
                    self.stop_event.wait(.5)
                    continue
                job=self.claim()
                if not job:
                    self.stop_event.wait(.4)
                    continue
                try:
                    self.run(job,worker)
                except Exception as exc:
                    log.exception('job_error',extra={'job_id':job['id']})
                    store.update_job(job['id'],status='paused',error=str(exc),stage='Paused after error')
                finally:
                    with self.lock: self.active.discard(job['id'])
        finally:
            worker.close()

    def run(self,job,worker):
        job_id=job['id']
        config=Settings.model_validate_json(job['settings'])
        known=store.regions(job_id)
        for number in range(1,job['total']+1):
            state=store.raw_job(job_id)
            if self.stop_event.is_set() or state['status']!='running':
                return
            with store.connection() as c:
                page=c.execute('SELECT * FROM pages WHERE job_id=? AND number=?',(job_id,number)).fetchone()
                if page['status'] in ('done','failed'): continue
                c.execute("UPDATE pages SET status='running',error=NULL WHERE job_id=? AND number=?",(job_id,number))
            store.update_job(job_id,stage=f'Analysing page {number} of {job["total"]}')
            began=time.monotonic()
            try:
                result=worker.call('app.extraction.pipeline','process_page',(job['path'],job_id,number,config.model_dump()),
                                   config.page_timeout,config.memory_mb,
                                   lambda:self.stop_event.is_set() or store.raw_job(job_id)['status']=='cancelled')
                with store.connection() as c:
                    manual=[json.loads(r[0]) for r in c.execute('SELECT data FROM regions WHERE job_id=? AND page=? AND manual=1',(job_id,number))]
                    c.execute('DELETE FROM regions WHERE job_id=? AND page=? AND manual=0',(job_id,number))
                    known=[r for r in known if r['page']!=number or r.get('manual')]
                    for region in result['regions']:
                        if any(iou(region['bbox'],m['bbox'])>.65 for m in manual): continue
                        for prior in known:
                            kind=relationship(region['hashes'],prior.get('hashes',{}),config.duplicate_distance)
                            if kind:
                                region['duplicate']={'id':prior['id'],'page':prior['page'],'kind':kind}
                                if kind!='visually similar': break
                        store.put_region(c,region)
                        known.append(region)
                    c.execute("UPDATE pages SET status='done',seconds=?,error=NULL WHERE job_id=? AND number=?",(result['seconds'],job_id,number))
                warnings=list(dict.fromkeys(json.loads(state['warnings'])+result['warnings']))
                store.update_job(job_id,device=result['device'],warnings=json.dumps(warnings),engines=json.dumps(result['engines']),error=None)
                log.info(json.dumps({'event':'page_complete','job_id':job_id,'page':number,'regions':len(result['regions']),'seconds':round(result['seconds'],3)}))
            except InterruptedError:
                with store.connection() as c:
                    c.execute("UPDATE pages SET status='pending' WHERE job_id=? AND number=?",(job_id,number))
                return
            except Exception as exc:
                with store.connection() as c:
                    c.execute("UPDATE pages SET status='failed',error=? WHERE job_id=? AND number=?",(str(exc),job_id,number))
                log.warning(json.dumps({'event':'page_failed','job_id':job_id,'page':number,'error':str(exc)}))
            finally:
                self.peak_mb=max(self.peak_mb,worker.peak_mb)
                with store.connection() as c:
                    c.execute('UPDATE jobs SET elapsed=elapsed+?,updated=? WHERE id=?',(time.monotonic()-began,time.time(),job_id))
        summary=store.job(job_id)
        if store.raw_job(job_id)['status']=='running':
            store.update_job(job_id,status='completed',stage='Completed with page errors' if summary['failed'] else 'Processing complete')
            if config.automatic_export:
                from app.services.exports import start_export
                try:
                    start_export(job_id,{'statuses':['accepted'],'format':config.format})
                except ValueError as exc:
                    notices=store.job(job_id)['warnings']+[f'Automatic export could not start: {exc}']
                    store.update_job(job_id,warnings=json.dumps(notices))

    def close(self):
        self.stop_event.set()
        for thread in self.threads: thread.join(5)
        with store.connection() as c:
            c.execute("UPDATE jobs SET status='paused',stage='Ready to resume' WHERE status IN ('running','queued')")
            c.execute("UPDATE pages SET status='pending' WHERE status='running'")


manager=JobManager()
