"""Deterministic synthetic photographic textures, not real-document accuracy evidence."""
import io
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import pymupdf as fitz


def photograph(seed=1,size=(480,640),white=False):
    rng=np.random.default_rng(seed)
    w,h=size
    yy,xx=np.mgrid[:h,:w]
    colors=np.stack([(xx/w*90+60+seed*13)%230,(yy/h*110+55+seed*9)%230,((xx+yy)/(w+h)*90+50+seed*19)%230],axis=-1)
    colors=np.clip(colors+rng.normal(0,18,(h,w,3)),0,255).astype('uint8')
    im=Image.fromarray(colors)
    draw=ImageDraw.Draw(im)
    draw.ellipse((w*.25,h*.12,w*.72,h*.49),fill=(160,115,83))
    draw.polygon([(w*.28,h*.42),(w*.7,h*.42),(w*.83,h*.9),(w*.12,h*.9)],fill=(30+seed*5,55,70))
    if white:
        padded=Image.new('RGB',size,'white'); im.thumbnail((int(w*.7),int(h*.85))); padded.paste(im,((w-im.width)//2,(h-im.height)//2)); im=padded
    data=io.BytesIO(); im.save(data,format='JPEG',quality=95,subsampling=0)
    return data.getvalue()


LAYOUT=[[30,40,292,760],[298,40,570,397],[298,403,570,760]]


def make_pdf(path,pages=1,flattened=False,gutter=6,background='white',rotation=0,white=False,empty=False):
    doc=fitz.open(); expected=[]
    images=[photograph(i+1,white=white) for i in range(3)]
    rects=[[30,40,300-gutter/2,760],[300+gutter/2,40,570,400-gutter/2],[300+gutter/2,400+gutter/2,570,760]]
    for number in range(pages):
        page=doc.new_page(width=600,height=800)
        flat=(flattened if isinstance(flattened,bool) else number%2==1)
        if not empty:
            if flat:
                canvas=Image.new('RGB',(1200,1600),background)
                for data,b in zip(images,rects):
                    crop=Image.open(io.BytesIO(data)).resize((round((b[2]-b[0])*2),round((b[3]-b[1])*2)))
                    canvas.paste(crop,(round(b[0]*2),round(b[1]*2)))
                stream=io.BytesIO(); canvas.save(stream,format='PNG')
                page.insert_image(page.rect,stream=stream.getvalue())
            else:
                for data,b in zip(images,rects): page.insert_image(b,stream=data,keep_proportion=False)
            if number%3==0: page.insert_text((30,25),'SYNTHETIC LAYOUT FIXTURE',fontsize=10)
        page.set_rotation(rotation)
        expected.append([list(fitz.Rect(b)*page.rotation_matrix) for b in rects] if not empty else [])
    doc.save(path); doc.close()
    return expected,images


def make_stress_pdf(path,pages=174):
    layouts=[
      [[30,40,297,760],[303,40,570,397],[303,403,570,760]],
      [[30,40,570,390],[30,396,297,760],[303,396,570,760]],
      [[30,40,207,760],[211,40,388,760],[392,40,570,760]],
      [[30,40,570,277],[30,281,570,518],[30,522,570,760]],
      [[30,40,297,397],[303,40,570,397],[30,403,297,760],[303,403,570,760]],
      [[0,0,600,800]],
      [],
    ]
    doc=fitz.open(); expected=[]
    assets=[photograph(i+1) for i in range(6)]
    for index in range(pages):
        page=doc.new_page(width=600,height=800)
        boxes=layouts[index%len(layouts)]
        if index%2 and boxes:
            bg=['#ffffff','#282828','#a6a095'][index%3]
            canvas=Image.new('RGB',(1200,1600),bg)
            for i,b in enumerate(boxes):
                photo=Image.open(io.BytesIO(assets[(i+index)%len(assets)]))
                photo=photo.resize((round((b[2]-b[0])*2),round((b[3]-b[1])*2)))
                canvas.paste(photo,(round(b[0]*2),round(b[1]*2)))
            stream=io.BytesIO();canvas.save(stream,format='PNG')
            page.insert_image(page.rect,stream=stream.getvalue())
        else:
            for i,b in enumerate(boxes): page.insert_image(b,stream=assets[(i+index)%len(assets)],keep_proportion=False)
        if boxes and len(boxes)>1: page.insert_text((30,25),f'Synthetic test page {index+1}',fontsize=10)
        rotation=90 if index%11==0 else 0
        page.set_rotation(rotation)
        expected.append([list(fitz.Rect(b)*page.rotation_matrix) for b in boxes])
    doc.save(path);doc.close()
    return expected
