import io
import math
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from app.core.config import Settings
from app.extraction.native_pdf import source_image, oriented_source
from app.extraction.page_renderer import render
from app.extraction.geometry import containment


def extract(path, region, config):
    settings = Settings.model_validate(config)
    with fitz.open(path) as doc:
        page = doc[region['page']-1]
        b = list(region['bbox'])
        padding = settings.padding
        b = [max(0,b[0]-padding),max(0,b[1]-padding),min(page.rect.width,b[2]+padding),min(page.rect.height,b[3]+padding)]
        source = region.get('source')
        payload = None
        passthrough = False
        if source and source.get('xref') and settings.preference=='source' and not region.get('manual'):
            im,payload = source_image(doc,source,settings.max_pixels)
            method = 'original source'
            passthrough = not source.get('mask')
        elif source and source.get('safe') and settings.preference!='displayed' and containment(b,source['bbox'])>.9999:
            im,payload = oriented_source(doc,source,b,settings.max_pixels)
            method = 'source pixels'
            a,bb,c,d,_,_ = source['transform']
            passthrough = all(abs(x-y)<.01 for x,y in zip(b,source['bbox'])) and a>0 and d>0 and abs(bb)<.001 and abs(c)<.001 and not source.get('mask')
        else:
            dpi = settings.dpi
            # Do not render raster-only crops above their available source density.
            if source:
                sb=source['bbox']
                source_dpi = 72*max(source['width']/max(1,sb[2]-sb[0]),source['height']/max(1,sb[3]-sb[1]))
                dpi = min(dpi,source_dpi)
            im = render(page,dpi,clip=b,max_pixels=settings.max_pixels)
            method = 'page render'
        if settings.resolution=='dpi' and method!='page render':
            target = (max(1,round((b[2]-b[0])*settings.dpi/72)),max(1,round((b[3]-b[1])*settings.dpi/72)))
            if target[0]<im.width or target[1]<im.height:
                im.thumbnail(target,Image.Resampling.LANCZOS)
                passthrough=False
        colour_keys={'icc_profile','dpi','gamma','srgb','transparency','interlace','chromaticity','compression',
                     'jfif','jfif_version','jfif_unit','jfif_density','adobe','adobe_transform'}
        has_private_metadata = bool(im.getexif() or any(key not in colour_keys for key in im.info))
        if passthrough and payload and (settings.preserve_metadata or not has_private_metadata):
            ext=payload['ext']
            if settings.format=='original' or (settings.format=='jpg' and ext in ('jpg','jpeg')) or (settings.format=='png' and ext=='png'):
                return payload['image'],ext,list(im.size),method+' · encoded passthrough'
        fmt = 'jpg' if settings.format=='jpg' else 'png'
        options = {}
        if settings.preserve_metadata:
            for key in ('exif','icc_profile','xmp','comment'):
                if im.info.get(key): options[key]=im.info[key]
            if fmt=='png':
                from PIL.PngImagePlugin import PngInfo
                info=PngInfo()
                for key,value in im.info.items():
                    if isinstance(value,str) and key not in colour_keys:
                        info.add_text(key,value)
                options['pnginfo']=info
        elif im.info.get('icc_profile'):
            options['icc_profile']=im.info['icc_profile']  # Colour profile is needed for faithful appearance.
        if fmt=='jpg':
            if im.mode in ('RGBA','LA'):
                rgba=im.convert('RGBA')
                background=Image.new('RGB',im.size,settings.jpeg_background)
                background.paste(rgba,mask=rgba.getchannel('A'))
                im=background
            else: im=im.convert('RGB')
            options.update(quality=settings.jpeg_quality,subsampling=0)
        output=io.BytesIO()
        # PNG writers otherwise inherit EXIF/text from im.info even with no explicit
        # encoder metadata. ICC is deliberately retained through options above.
        im.info.clear()
        im.save(output,format='JPEG' if fmt=='jpg' else 'PNG',**options)
        return output.getvalue(),fmt,list(im.size),method


def export_one(path, region, config, destination):
    data,ext,dims,method=extract(path,region,config)
    dest=Path(destination).with_suffix('.'+ext)
    if dest.exists():
        raise ValueError('Output collision; existing file was not overwritten.')
    temp=dest.with_suffix(dest.suffix+'.part')
    with temp.open('xb') as file:
        file.write(data)
        file.flush()
        import os
        os.fsync(file.fileno())
    temp.replace(dest)
    return str(dest),dims,method
