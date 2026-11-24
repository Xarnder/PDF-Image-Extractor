import io
import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.api.main import app
from app.database import store
from app.core.config import Settings,check_disk
from app.extraction.ai_detector import choose_device,detect_optional,HeronDetector
from app.extraction.duplicate_detector import hashes,relationship
from app.services import edits
from tests.fixtures import make_pdf


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        token=c.get('/api/session').json()['token']
        c.headers['x-local-token']=token
        yield c


def upload_job(client,tmp_path,pages=1):
    path=tmp_path/(uuid.uuid4().hex+'.pdf'); make_pdf(path,pages=pages,flattened='mixed')
    r=client.post('/api/jobs',content=path.read_bytes(),headers={'x-filename':'test.pdf'})
    assert r.status_code==200,r.text
    return r.json()


def wait_job(client,jid,status='completed'):
    deadline=time.time()+30
    while time.time()<deadline:
        job=client.get('/api/jobs/'+jid).json()
        if job['status']==status:return job
        time.sleep(.1)
    raise AssertionError(job)


def test_local_security(client):
    assert client.get('/api/session',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/session',headers={'Host':'evil.example'}).status_code==403
    assert client.get('/api/session',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.put('/api/settings',json=Settings().model_dump(),headers={'x-local-token':'wrong'}).status_code==403
    assert client.post('/api/jobs',content=b'not a pdf',headers={'x-filename':'fake.pdf'}).status_code==400


def test_processing_edits_history_and_export(client,tmp_path):
    job=upload_job(client,tmp_path,3); jid=job['id']
    assert client.post(f'/api/jobs/{jid}/action',json={'action':'start'}).status_code==200
    done=wait_job(client,jid)
    assert done['processed']==3 and done['failed']==0 and done['photographs']==9
    items=client.get(f'/api/jobs/{jid}/regions').json()['items']
    r=items[0]; original=r['bbox']; changed=[original[0]+2,*original[1:]]
    response=client.post(f'/api/jobs/{jid}/edits',json={'changes':[{'id':r['id'],'bbox':changed,'revision':0,'status':'rejected'}]})
    assert response.status_code==200,response.text
    assert response.json()[0]['manual']
    assert client.post(f'/api/jobs/{jid}/edits',json={'changes':[{'id':r['id'],'bbox':[0,0,900,900]}]}).status_code==400
    assert client.post(f'/api/jobs/{jid}/edits',json={'changes':[{'id':r['id'],'bbox':changed,'revision':0}]}).status_code==400
    assert client.post(f'/api/jobs/{jid}/history',json={'redo':False}).json()['changed']
    assert store.regions(jid)[0]['bbox']==original
    assert client.post(f'/api/jobs/{jid}/history',json={'redo':True}).json()['changed']
    assert store.regions(jid)[0]['bbox']==changed
    new=client.post(f'/api/jobs/{jid}/edits',json={'create':{'page':1,'bbox':[original[0],original[1],(original[0]+original[2])/2,original[3]]}})
    assert new.status_code==200
    assert new.json()[0]['source']['safe']
    assert new.json()[0]['dimensions']==[240,640]
    client.post(f'/api/jobs/{jid}/history',json={'redo':False})
    client.post(f'/api/jobs/{jid}/action',json={'action':'redetect','page':1})
    wait_job(client,jid)
    kept=next(x for x in store.regions(jid) if x['id']==r['id'])
    assert kept['bbox']==changed and kept['status']=='rejected'
    export=client.post(f'/api/jobs/{jid}/exports',json={'format':'png','statuses':['accepted','review','rejected']}).json()
    for _ in range(200):
        state=client.get(f'/api/exports/{export["id"]}').json()
        if state['status'] not in ('running','queued'):break
        time.sleep(.1)
    assert state['status']=='completed',state
    folder=Path(state['path']); manifest=json.loads((folder/'metadata.json').read_text())
    assert len(manifest['images'])==9
    for image in manifest['images']:
        with Image.open(folder/image['output_filename']) as im: im.verify()
    assert client.get(f'/api/exports/{export["id"]}/download').status_code==200
    assert client.get(f'/api/jobs/{jid}/pages/1/preview').status_code==200


def test_pause_resume_failure_retry(client,tmp_path):
    job=upload_job(client,tmp_path,8); jid=job['id']
    client.post(f'/api/jobs/{jid}/action',json={'action':'start'})
    time.sleep(.3)
    client.post(f'/api/jobs/{jid}/action',json={'action':'pause'})
    from app.jobs.manager import manager
    for _ in range(100):
        if jid not in manager.active: break
        time.sleep(.1)
    assert client.get(f'/api/jobs/{jid}').json()['status']=='paused'
    client.post(f'/api/jobs/{jid}/action',json={'action':'resume'})
    done=wait_job(client,jid)
    assert done['processed']==8
    with store.connection() as c:
        c.execute("UPDATE pages SET status='failed',error='Injected failure' WHERE job_id=? AND number=4",(jid,))
    assert client.post(f'/api/jobs/{jid}/action',json={'action':'retry'}).status_code==200
    assert wait_job(client,jid)['failed']==0


def test_interruption_checkpoint_recovery(client,tmp_path):
    job=upload_job(client,tmp_path,2); jid=job['id']
    with store.connection() as c:
        c.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
        c.execute("UPDATE pages SET status='running' WHERE job_id=? AND number=1",(jid,))
    store.init()
    assert store.job(jid)['status']=='paused'
    assert client.get(f'/api/jobs/{jid}/pages').json()[0]['status']=='pending'
    client.post(f'/api/jobs/{jid}/action',json={'action':'resume'})
    assert wait_job(client,jid)['processed']==2


def test_duplicates_and_disk():
    a=Image.new('RGB',(100,100),'red'); b=a.copy()
    assert relationship(hashes(a,b'abc'),hashes(b,b'abc'))=='identical source'
    assert relationship(hashes(a),hashes(b))=='identical pixels'
    with patch('shutil.disk_usage',return_value=type('Space',(),{'free':100})()):
        with pytest.raises(ValueError,match='disk'): check_disk(Path('.'))


def test_optional_ai_failure_and_cpu_fallback():
    torch=type('Torch',(),{'backends':type('Backends',(),{'mps':type('MPS',(),{'is_available':staticmethod(lambda:False)})()}),'cuda':type('CUDA',(),{'is_available':staticmethod(lambda:False)})()})()
    assert choose_device(torch,'mps')=='cpu'
    assert choose_device(torch,'cuda')=='cpu'
    with patch('app.extraction.ai_detector.model_status',return_value={'available':True}),patch.object(HeronDetector,'__init__',side_effect=RuntimeError('broken model')):
        boxes,device,warnings=detect_optional(Image.new('RGB',(100,100)),Settings(ai_enabled=True))
    assert boxes==[] and device=='CPU' and 'failed' in warnings[0]
