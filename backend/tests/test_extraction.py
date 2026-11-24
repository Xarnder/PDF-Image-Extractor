import io
import uuid
import pytest
import pymupdf as fitz
from PIL import Image
from app.core.config import Settings
from app.extraction.pipeline import process_page
from app.extraction.exporter import extract,export_one
from app.extraction.geometry import iou
from app.extraction.page_renderer import inspect_pdf
from tests.fixtures import make_pdf,photograph


@pytest.mark.parametrize('flat,bg,gutter',[(False,'white',6),(True,'white',6),(True,'white',2),(True,'#222222',6),(True,'#9b8970',6)])
def test_layouts(tmp_path,flat,bg,gutter):
    path=tmp_path/'layout.pdf'
    expected,_=make_pdf(path,flattened=flat,background=bg,gutter=gutter)
    result=process_page(str(path),uuid.uuid4().hex,1,Settings().model_dump())
    regions=result['regions']
    assert len(regions)==3,[(r['bbox'],r['method']) for r in regions]
    for bbox in expected[0]: assert max(iou(bbox,r['bbox']) for r in regions)>.97


def test_native_original_bytes_and_dimensions(tmp_path):
    path=tmp_path/'native.pdf'; _,images=make_pdf(path)
    regions=process_page(str(path),uuid.uuid4().hex,1,Settings(mode='native').model_dump())['regions']
    assert len(regions)==3
    data,ext,dims,method=extract(str(path),regions[0],Settings(format='original').model_dump())
    assert dims==[480,640]
    assert data==images[0]
    assert 'passthrough' in method


@pytest.mark.parametrize('rotation',[90,180,270])
def test_rotated_page(tmp_path,rotation):
    path=tmp_path/'rotated.pdf'; expected,_=make_pdf(path,rotation=rotation)
    regions=process_page(str(path),uuid.uuid4().hex,1,Settings(mode='native').model_dump())['regions']
    assert len(regions)==3
    for b in expected[0]: assert max(iou(b,r['bbox']) for r in regions)>.999
    data,_,dims,_=extract(str(path),regions[0],Settings().model_dump())
    assert Image.open(io.BytesIO(data)).size==tuple(dims)


def test_white_photo_background_not_trimmed(tmp_path):
    path=tmp_path/'white.pdf'; expected,_=make_pdf(path,white=True)
    regions=process_page(str(path),uuid.uuid4().hex,1,Settings().model_dump())['regions']
    assert len(regions)==3
    for b in expected[0]: assert max(iou(b,r['bbox']) for r in regions)>.999


def test_empty_and_corrupt(tmp_path):
    path=tmp_path/'empty.pdf'; make_pdf(path,empty=True)
    assert not process_page(str(path),uuid.uuid4().hex,1,Settings().model_dump())['regions']
    path.write_bytes(b'%PDF-1.7 corrupt')
    with pytest.raises(Exception): inspect_pdf(str(path))


def test_encryption(tmp_path):
    path=tmp_path/'plain.pdf'; make_pdf(path)
    locked=tmp_path/'encrypted.pdf'
    with fitz.open(path) as doc: doc.save(locked,encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='secret')
    with pytest.raises(ValueError,match='password'): inspect_pdf(str(locked))
    assert len(inspect_pdf(str(locked),'secret'))==1
    with fitz.open(locked) as doc: assert not doc.needs_pass


def test_crop_export_and_collision(tmp_path):
    path=tmp_path/'crop.pdf'; make_pdf(path)
    r=process_page(str(path),uuid.uuid4().hex,1,Settings().model_dump())['regions'][0]
    r['bbox'][2]=(r['bbox'][0]+r['bbox'][2])/2; r['manual']=True
    for fmt in ['png','jpg']:
        data,ext,dims,method=extract(str(path),r,Settings(format=fmt).model_dump())
        assert dims==[240,640]
        assert Image.open(io.BytesIO(data)).format==('PNG' if fmt=='png' else 'JPEG')
    config=Settings().model_dump()
    export_one(str(path),r,config,str(tmp_path/'output'))
    with pytest.raises(ValueError,match='collision'): export_one(str(path),r,config,str(tmp_path/'output'))


def test_mask_rotation_reuse_and_clipping(tmp_path):
    im=Image.open(io.BytesIO(photograph())).convert('RGBA'); im.putalpha(180)
    buf=io.BytesIO(); im.save(buf,format='PNG')
    doc=fitz.open(); page=doc.new_page(width=600,height=800)
    xref=page.insert_image([30,30,250,350],stream=buf.getvalue())
    page.insert_image([320,30,570,350],xref=xref,rotate=90)
    # A cropbox clips an independently embedded JPEG.
    page.insert_image([30,400,570,780],stream=photograph(4),keep_proportion=False)
    page.set_cropbox(fitz.Rect(0,0,600,720))
    path=tmp_path/'special.pdf'; doc.save(path); doc.close()
    regions=process_page(str(path),uuid.uuid4().hex,1,Settings(mode='native').model_dump())['regions']
    assert len(regions)==3
    assert regions[0]['source']['mask']
    for r in regions:
        data,_,_,_=extract(str(path),r,Settings().model_dump())
        Image.open(io.BytesIO(data)).verify()
    assert max(r['bbox'][3] for r in regions)<=720
