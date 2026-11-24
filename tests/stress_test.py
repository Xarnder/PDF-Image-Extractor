"""End-to-end 174-page benchmark, using the same HTTP API as Chrome.

Runs in tests/generated/stress-data, deliberately restarts the server, resumes,
exports all detections, and validates every image and the measured boxes.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx
import psutil
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'backend'))
from tests.fixtures import make_stress_pdf
from app.extraction.geometry import iou


def main():
    generated=ROOT/'tests/generated';generated.mkdir(parents=True,exist_ok=True)
    path=generated/'synthetic-174.pdf'
    expected=make_stress_pdf(path)
    (generated/'expected.json').write_text(json.dumps(expected))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'PYTHONPATH':str(ROOT/'backend'),'PDF_EXTRACTOR_DATA':str(generated/'stress-data')}
    log=(generated/'stress-server.log').open('w')
    server=None
    client=httpx.Client(base_url=base,timeout=180)
    peak=0;latencies=[];interrupted=False
    def start():
        p=subprocess.Popen([sys.executable,'-m','uvicorn','app.api.main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        for _ in range(150):
            if p.poll() is not None: raise RuntimeError('Test server failed. See stress-server.log')
            try:
                if client.get('/api/health').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        client.headers['X-Local-Token']=client.get('/api/session').json()['token']
        return p
    try:
        server=start()
        with path.open('rb') as f:
            r=client.post('/api/jobs',content=iter(lambda:f.read(1024*1024),b''),headers={'X-Filename':'Synthetic 174-page benchmark.pdf','X-Mode':'balanced'})
        r.raise_for_status();job=r.json();jid=job['id']
        started=time.perf_counter()
        client.post(f'/api/jobs/{jid}/action',json={'action':'start'}).raise_for_status()
        while True:
            t=time.perf_counter();health=client.get('/api/health');latencies.append((time.perf_counter()-t)*1000);health.raise_for_status()
            procs=[psutil.Process(server.pid),*psutil.Process(server.pid).children(recursive=True)]
            peak=max(peak,sum(p.memory_info().rss for p in procs if p.is_running())/1024**2)
            job=client.get(f'/api/jobs/{jid}').json()
            if not interrupted and job['processed']>=12:
                checkpoint=job['processed']
                os.killpg(server.pid,signal.SIGKILL);server.wait()
                server=start();resumed=client.get(f'/api/jobs/{jid}').json()
                assert resumed['status']=='paused' and resumed['processed']>=checkpoint
                client.post(f'/api/jobs/{jid}/action',json={'action':'resume'}).raise_for_status()
                interrupted=True
                print(f'Restarted after {checkpoint} pages; checkpoint preserved.',flush=True)
            if job['status']=='completed':break
            if time.perf_counter()-started>600:raise TimeoutError('Stress job exceeded ten minutes')
            time.sleep(.2)
        process_wall=time.perf_counter()-started
        detections=[]
        for offset in range(0,job['photographs'],500):detections+=client.get(f'/api/jobs/{jid}/regions?offset={offset}&limit=500').json()['items']
        matched=0;ious=[];edges=[];false=0
        for number,boxes in enumerate(expected,1):
            actual=[r for r in detections if r['page']==number]
            available=actual.copy()
            for box in boxes:
                ranked=sorted(available,key=lambda r:iou(box,r['bbox']),reverse=True)
                if ranked and iou(box,ranked[0]['bbox'])>.9:
                    r=ranked[0];available.remove(r);matched+=1;ious.append(iou(box,r['bbox']));edges.append(max(abs(a-b) for a,b in zip(box,r['bbox'])))
            false+=len(available)
        export_start=time.perf_counter()
        er=client.post(f'/api/jobs/{jid}/exports',json={'format':'png','statuses':['accepted','review','rejected']});er.raise_for_status();eid=er.json()['id']
        while True:
            state=client.get(f'/api/exports/{eid}').json()
            if state['status'] not in ('running','queued'):break
            if time.perf_counter()-export_start>600:raise TimeoutError('Export timed out')
            time.sleep(.3)
        assert state['status']=='completed',state
        folder=Path(state['path']);manifest=json.loads((folder/'metadata.json').read_text())
        for image in manifest['images']:
            with Image.open(folder/image['output_filename']) as im: im.verify()
        expected_total=sum(map(len,expected))
        report={'fixture':'Synthetic textured images, seven layouts, alternate embedded and flattened pages; white/dark/coloured paper; page rotations; no real-document claims',
                'pages':174,'processed':job['processed'],'failed_pages':job['failed'],'expected_regions':expected_total,'detected_regions':len(detections),'matched_regions':matched,
                'missed_regions':expected_total-matched,'false_positives':false,'precision':matched/max(1,len(detections)),'recall':matched/expected_total,
                'mean_iou':sum(ious)/max(1,len(ious)),'max_edge_error_pdf_points':max(edges,default=0),'processing_seconds':process_wall,
                'pipeline_seconds':job['elapsed'],'pages_per_second':174/process_wall,'peak_server_and_worker_rss_mb':peak,
                'health_latency_p95_ms':sorted(latencies)[int(len(latencies)*.95)],'health_latency_max_ms':max(latencies),
                'restart_resume_verified':interrupted,'exported_valid_images':len(manifest['images']),'export_seconds':time.perf_counter()-export_start,
                'job_id':jid,'export_directory':folder.relative_to(ROOT).as_posix()}
        (ROOT/'docs/benchmark.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2),flush=True)
        assert job['processed']==174 and job['failed']==0
        assert matched==expected_total and false==0
        assert max(edges)<2.0
    finally:
        if server and server.poll() is None:
            server.terminate()
            try:server.wait(30)
            except subprocess.TimeoutExpired:os.killpg(server.pid,signal.SIGKILL)
        client.close();log.close()


if __name__=='__main__':main()
