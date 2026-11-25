import io
import uuid
from unittest.mock import patch
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw
from app.core.config import Settings
from app.extraction.content_analysis import analyze
from app.extraction.geometry import Detection
from app.extraction.layout_evidence import preserves_faces, text_coverage
from app.extraction.photo_classifier import assess
from app.extraction.pipeline import process_page
from tests.fixtures import photograph


def studio_page(path):
    # One low-contrast photographic background, with disjoint foreground masses.
    # A foreground detector must not reinterpret those masses as separate photos.
    rng=np.random.default_rng(42)
    pixels=np.clip(205+rng.normal(0,1,(800,600,3)),0,255).astype('uint8')
    im=Image.fromarray(pixels);draw=ImageDraw.Draw(im)
    draw.ellipse((250,80,360,225),fill='#a27964')
    draw.polygon([(225,285),(385,285),(345,750),(200,750)],fill='#3a2838')
    stream=io.BytesIO();im.save(stream,format='PNG')
    with fitz.open() as doc:
        page=doc.new_page(width=600,height=800)
        page.insert_image(page.rect,stream=stream.getvalue())
        page.insert_text((360,500),'A caption beside the model',fontsize=10)
        doc.save(path)


def test_balanced_does_not_split_full_page_foreground(tmp_path):
    path=tmp_path/'studio.pdf';studio_page(path)
    for mode in ('balanced','maximum'):
        result=process_page(str(path),uuid.uuid4().hex,1,Settings(mode=mode,content_analysis=False).model_dump())
        assert len(result['regions'])==1
        assert result['regions'][0]['bbox']==[0,0,600,800]


def test_face_priority_keeps_uncertain_image_without_face_crop():
    image=Image.new('RGB',(300,500),'#dddddd')
    evidence={'faces':[[.3,.1,.7,.35]],'labels':[],'texts':[],'backend':'OpenCV'}
    label,_,reasons,decision=assess(image,evidence,native=True,face_priority=True)
    assert decision=='review' and 'face' in label
    assert any('complete face, body and background' in r for r in reasons)


def test_proposed_split_cannot_cut_or_drop_a_face():
    parent=[0,0,600,800]
    face=[[.4,.1,.6,.3]]
    assert not preserves_faces(parent,[Detection([0,0,300,800],.9,'CV'),Detection([310,0,600,800],.9,'CV')],face)
    assert not preserves_faces(parent,[Detection([0,300,600,800],.9,'CV')],face)
    assert preserves_faces(parent,[Detection([100,40,500,760],.9,'CV')],face)


def test_printed_faces_do_not_turn_book_mockup_into_photo():
    im=Image.open(io.BytesIO(photograph()))
    evidence={'faces':[[.3,.2,.4,.3],[.6,.4,.7,.5]],
              'labels':[{'label':'document','score':.31},{'label':'book','score':.27}], 'texts':[], 'backend':'Apple Vision'}
    label,_,_,decision=assess(im,evidence,native=True,face_priority=True)
    assert label=='Book / printed layout' and decision=='rejected'


def test_text_and_logos_are_rejected_but_captioned_portrait_survives():
    im=Image.open(io.BytesIO(photograph()))
    evidence={'faces':[],'labels':[],'texts':[{'box':[.05,.1,.95,.7],'characters':30}], 'backend':'Apple Vision'}
    assert assess(im,evidence)[3]=='rejected'
    evidence['faces']=[[.2,.1,.4,.4]]
    evidence['texts']=[{'box':[.6,.8,.95,.9],'characters':20}]
    assert assess(im,evidence,native=True)[3]!='rejected'


def test_no_face_is_not_a_reason_to_reject_a_photo():
    im=Image.open(io.BytesIO(photograph()))
    assert assess(im,{'faces':[],'labels':[],'texts':[]},native=True)[3]!='rejected'


def test_semantic_helper_failure_falls_back_locally():
    image=Image.new('RGB',(80,100),'white')
    with patch('app.extraction.content_analysis.status',return_value={'available':True}),patch('app.extraction.content_analysis.subprocess.run',side_effect=OSError('Unavailable')):
        result,engine,warnings=analyze([image])
    assert len(result)==1 and engine=='OpenCV face checks' and warnings


def test_overlapping_text_boxes_do_not_inflate_coverage():
    assert text_coverage([0,0,100,100],[[0,0,50,100],[0,0,50,100]])==.5


def test_banner_is_not_split_into_an_icon_and_text(tmp_path):
    # Two high-contrast rectangular components are insufficient to split a banner.
    image=Image.new('RGB',(1080,180),'white')
    draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,170,179),fill='#883344')
    draw.rectangle((190,0,1079,179),fill='#555555')
    stream=io.BytesIO();image.save(stream,format='PNG')
    doc=fitz.open();page=doc.new_page(width=600,height=800)
    page.insert_image(fitz.Rect(30,30,570,120),stream=stream.getvalue())
    path=tmp_path/'banner.pdf';doc.save(path);doc.close()
    candidates=[Detection([50,50,192,200],.9,'OpenCV'),Detection([208,50,950,200],.9,'OpenCV')]
    with patch('app.extraction.pipeline.OpenCVDetector.detect',return_value=candidates),patch('app.extraction.pipeline.separate_photographs',return_value=candidates):
        result=process_page(str(path),'banner-safety',1,Settings(mode='balanced',content_analysis=False).model_dump())
    assert len(result['regions'])==1
    assert result['regions'][0]['bbox']==[30,30,570,120]
    assert result['regions'][0]['status']=='rejected'


def test_inline_graphic_is_not_classified_using_the_photo_behind_it(tmp_path):
    doc=fitz.open();page=doc.new_page(width=600,height=800)
    page.insert_image(page.rect,stream=photograph(size=(600,800)))
    # Empty off-page inline graphic with part of its placement over a real photo.
    image=Image.new('L',(500,100),0)
    xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
    stream=b'q\n500 0 0 100 -400 50 cm\nBI /W 500 /H 100 /CS /G /BPC 8 /F /AHx ID\n'+image.tobytes().hex().encode()+b'>\nEI\nQ'
    doc.update_stream(xref,stream)
    existing=page.get_contents();doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{n} 0 R' for n in [xref,*existing])+']')
    path=tmp_path/'inline-graphic.pdf';doc.save(path);doc.close()
    result=process_page(str(path),uuid.uuid4().hex,1,Settings(mode='balanced',content_analysis=False).model_dump())
    inline=next(r for r in result['regions'] if r['source'] and r['source']['xref']==0)
    assert inline['status']=='rejected'
    assert any(r['status']!='rejected' and r['source'] and r['source']['xref'] for r in result['regions'])
