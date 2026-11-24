import math
from pathlib import Path
import pymupdf as fitz
from PIL import Image


def save_preview(image, destination, quality=85):
    import uuid
    dest=Path(destination)
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_name(dest.name+'.'+uuid.uuid4().hex+'.part')
    try:
        image.save(temp,format='JPEG',quality=quality)
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)


def render(page, dpi=120, clip=None, max_pixels=60000000):
    rect = fitz.Rect(clip) if clip else page.rect
    if rect.is_empty or not math.isfinite(rect.width * rect.height):
        raise ValueError('Invalid page or crop bounds')
    scale = dpi / 72
    pixels = rect.width * rect.height * scale * scale
    if pixels > max_pixels:
        scale *= math.sqrt(max_pixels / pixels)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False, colorspace=fitz.csRGB, annots=True)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def preview(path: str, number: int, target: str, width=1400):
    with fitz.open(path) as doc:
        page = doc[number-1]
        im = render(page, min(150, 72 * width / page.rect.width), max_pixels=3000000)
        im.thumbnail((width, 2000))
        dest = Path(target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        save_preview(im,dest)
    return str(dest)


def inspect_pdf(path: str, password: str = ''):
    with fitz.open(path) as doc:
        if doc.needs_pass and not doc.authenticate(password):
            raise ValueError('This PDF requires a valid password.')
        if not doc.is_pdf or not len(doc) or len(doc) > 20000:
            raise ValueError('PDF must contain between 1 and 20,000 pages.')
        pages = []
        for p in doc:
            if not (1 < p.rect.width <= 20000 and 1 < p.rect.height <= 20000):
                raise ValueError(f'Page {p.number+1} has unsupported dimensions.')
            pages.append((p.rect.width, p.rect.height))
        if doc.is_encrypted or password:
            decrypted = path + '.unlocked'
            doc.save(decrypted, encryption=fitz.PDF_ENCRYPT_NONE)
        else:
            decrypted = None
    if decrypted:
        Path(decrypted).replace(path)
    return pages
