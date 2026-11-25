import io
import uuid
import time
import pytest
import pymupdf as fitz
from PIL import Image,ImageDraw
from app.core.config import Settings
from app.extraction.pipeline import process_page
from app.extraction.exporter import extract
from app.extraction.geometry import iou
from app.jobs.worker import IsolatedWorker
from tests.fixtures import photograph


def run(path,**settings):
    return process_page(str(path),uuid.uuid4().hex,1,Settings(**settings).model_dump())['regions']


@pytest.mark.parametrize('mode',['RGB','CMYK','L'])
def test_colour_spaces(tmp_path,mode):
    im=Image.open(io.BytesIO(photograph())).convert(mode);data=io.BytesIO();im.save(data,format='JPEG')
    doc=fitz.open();page=doc.new_page();page.insert_image([40,40,500,700],stream=data.getvalue())
    path=tmp_path/'color.pdf';doc.save(path);doc.close()
    regions=run(path,mode='native');assert len(regions)==1
    png,_,_,_=extract(str(path),regions[0],Settings(format='png').model_dump())
    assert Image.open(io.BytesIO(png)).mode in ('RGB','L','RGBA')


def test_rectangular_clip_preserves_visible_composition(tmp_path):
    doc=fitz.open();p=doc.new_page(width=600,height=800)
    original=photograph()
    p.insert_image([20,20,580,780],stream=original,keep_proportion=False)
    stream=p.get_contents()[0]
    doc.update_stream(stream,b'q\n100 100 200 400 re W n\n'+doc.xref_stream(stream)+b'\nQ')
    path=tmp_path/'clipped.pdf';doc.save(path);doc.close()
    regions=run(path,mode='native');assert len(regions)==1
    assert iou(regions[0]['bbox'],[100,300,300,700])>.999
    visible,_,dims,method=extract(str(path),regions[0],Settings().model_dump())
    assert 'source' in method and dims==[171,337]
    source,_,dims,_=extract(str(path),regions[0],Settings(format='original',preference='source').model_dump())
    assert source==original and dims==[480,640]


def test_full_page_and_decorative_graphic(tmp_path):
    doc=fitz.open();page=doc.new_page(width=600,height=800)
    graphic=Image.new('RGB',(250,250),'white');draw=ImageDraw.Draw(graphic)
    draw.rectangle((30,40,120,210),fill='#889999');draw.polygon([(125,40),(225,65),(220,220),(125,210)],fill='#667777')
    data=io.BytesIO();graphic.save(data,format='PNG')
    page.insert_image([20,20,250,250],stream=data.getvalue())
    page.insert_image([260,280,580,760],stream=photograph())
    page.insert_text((30,270),'Decorative book icon above, image below',fontsize=10)
    path=tmp_path/'graphics.pdf';doc.save(path);doc.close()
    regions=run(path)
    graphic_regions=[r for r in regions if r['bbox'][1]<250]
    assert graphic_regions and all(r['status']=='rejected' for r in graphic_regions)
    doc=fitz.open();page=doc.new_page(width=600,height=800);page.insert_image(page.rect,stream=photograph(),keep_proportion=False)
    path=tmp_path/'full.pdf';doc.save(path);doc.close()
    regions=run(path)
    assert len(regions)==1 and regions[0]['bbox']==[0,0,600,800]


def test_rotated_photograph_and_mirror(tmp_path):
    doc=fitz.open();p=doc.new_page(width=600,height=800)
    p.insert_image([50,50,550,400],stream=photograph(),rotate=90,keep_proportion=False)
    path=tmp_path/'rotated-image.pdf';doc.save(path);doc.close()
    r=run(path,mode='native')[0]
    data,_,dims,method=extract(str(path),r,Settings().model_dump())
    assert dims==[640,480] and 'source' in method
    with fitz.open(path) as doc:
        pix=doc[0].get_pixmap(clip=fitz.Rect(r['bbox']))
        ref=Image.frombytes('RGB',(pix.width,pix.height),pix.samples).resize((80,60))
    import numpy as np
    output=Image.open(io.BytesIO(data)).convert('RGB').resize((80,60))
    assert np.abs(np.asarray(ref,dtype=float)-np.asarray(output,dtype=float)).mean()<5


def test_worker_timeout_and_recovery():
    worker=IsolatedWorker()
    try:
        with pytest.raises(TimeoutError):worker.call('time','sleep',(5,),timeout=.1)
        assert worker.call('builtins','sum',([1,2,3],),timeout=10)==6
        with pytest.raises(InterruptedError):worker.call('time','sleep',(5,),cancelled=lambda:True)
    finally:worker.close()


def test_pixel_limit_rejects_oversized_source(tmp_path):
    doc=fitz.open();page=doc.new_page(width=600,height=800)
    page.insert_image(page.rect,stream=photograph(size=(1200,1200)),keep_proportion=False)
    path=tmp_path/'large.pdf';doc.save(path);doc.close()
    region=run(path,mode='native',max_pixels=1000000)[0]
    assert region['source']['safe'] is False
    with pytest.raises(ValueError,match='pixel limit'):
        extract(str(path),region,Settings(preference='source',max_pixels=1000000).model_dump())


def test_inline_image_and_alpha_duplicates(tmp_path):
    import numpy as np
    from app.extraction.duplicate_detector import hashes
    image=Image.open(io.BytesIO(photograph(size=(160,240)))).convert('RGB')
    doc=fitz.open();p=doc.new_page(width=600,height=800)
    xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
    stream=b'q\n300 0 0 450 50 100 cm\nBI /W 160 /H 240 /CS /RGB /BPC 8 /F /AHx ID\n'+image.tobytes().hex().encode()+b'>\nEI\nQ'
    doc.update_stream(xref,stream);p.set_contents(xref)
    path=tmp_path/'inline.pdf';doc.save(path);doc.close()
    regions=run(path,mode='native')
    assert len(regions)==1 and regions[0]['source']['xref']==0
    data,_,_,method=extract(str(path),regions[0],Settings().model_dump())
    Image.open(io.BytesIO(data)).verify();assert method=='page render'
    a=Image.new('RGBA',(20,20),(10,30,50,0));b=Image.new('RGBA',(20,20),(10,30,50,255))
    assert hashes(a)['pixel_hash']!=hashes(b)['pixel_hash']


def test_metadata_preservation_and_removal(tmp_path):
    image=Image.open(io.BytesIO(photograph()))
    exif=Image.Exif();exif[315]='Synthetic test author'
    data=io.BytesIO();image.save(data,format='JPEG',quality=95,exif=exif)
    doc=fitz.open();p=doc.new_page();p.insert_image([50,50,530,690],stream=data.getvalue())
    path=tmp_path/'metadata.pdf';doc.save(path);doc.close()
    region=run(path,mode='native')[0]
    for fmt in ('png','jpg'):
        stripped,_,_,_=extract(str(path),region,Settings(format=fmt,preserve_metadata=False).model_dump())
        assert not Image.open(io.BytesIO(stripped)).getexif()
        retained,_,_,_=extract(str(path),region,Settings(format=fmt,preserve_metadata=True).model_dump())
        assert Image.open(io.BytesIO(retained)).getexif()[315]=='Synthetic test author'
