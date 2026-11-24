"""Every placement has its own transform, in rotated, displayed PDF points."""
import io
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageChops
from app.extraction.geometry import Detection, area, intersect


def placements(page, settings):
    result = []
    for info in page.get_image_info(xrefs=True):
        matrix = fitz.Matrix(info['transform']) * page.rotation_matrix
        bbox = list(fitz.Rect(info['bbox']) * page.rotation_matrix)
        visible = intersect(bbox, list(page.rect))
        if area(visible) <= 0:
            continue
        if min(info['width'], info['height']) < settings.min_dimension or area(visible) / area(list(page.rect)) < settings.min_area:
            continue
        source = {'xref': info['xref'], 'width': info['width'], 'height': info['height'], 'transform': list(matrix), 'bbox': bbox,
                  'mask': bool(info.get('has-mask', False)), 'encoding': None, 'safe': False}
        # get_image_info doesn't expose soft mask xrefs in all supported versions.
        if info['xref']:
            for item in page.get_images(full=True):
                if item[0] == info['xref']:
                    source['smask'] = item[1]
                    source['mask'] = bool(item[1]) or source['mask']
                    break
        result.append(Detection(visible, 0.91, 'Native PDF', source))
    return result


def source_image(doc, source, max_pixels):
    if source['width'] * source['height'] > max_pixels:
        raise ValueError('Embedded image exceeds the configured pixel limit.')
    xref = source['xref']
    if not xref:
        raise ValueError('Inline image requires page rendering.')
    payload = doc.extract_image(xref)
    if not payload:
        raise ValueError('Image encoding cannot be decoded.')
    im = Image.open(io.BytesIO(payload['image']))
    im.load()
    if source.get('smask'):
        pix = fitz.Pixmap(doc, xref)
        if pix.colorspace and pix.colorspace.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        mask = fitz.Pixmap(doc, source['smask'])
        pix = fitz.Pixmap(pix, mask)
        im = Image.frombytes('RGBA', (pix.width, pix.height), pix.samples)
    if im.mode not in ('RGB', 'RGBA', 'L', 'LA'):
        if im.info.get('icc_profile'):
            try:
                from PIL import ImageCms
                im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile'])), ImageCms.createProfile('sRGB'), outputMode='RGB')
            except Exception:
                im = im.convert('RGB')
        else:
            im = im.convert('RGB')
    return im, payload


def oriented_source(doc, source, bbox, max_pixels):
    """Orthogonal placements only. Arbitrary affine/clipped paths use MuPDF."""
    matrix = fitz.Matrix(source['transform'])
    a, b, c, d, e, f = matrix
    eps = 1e-4
    orthogonal = (abs(b) < eps and abs(c) < eps) or (abs(a) < eps and abs(d) < eps)
    if not orthogonal or abs(a*d-b*c) < eps:
        raise ValueError('Non-orthogonal placement requires rendering.')
    im, payload = source_image(doc, source, max_pixels)
    # PIL affine maps output pixels back to input pixels, including mirrors and rotations.
    inverse = ~matrix
    if abs(b) < eps:
        density_x, density_y = im.width / abs(a), im.height / abs(d)
    else:
        density_x, density_y = im.height / abs(c), im.width / abs(b)
    width = max(1, round((bbox[2]-bbox[0]) * density_x))
    height = max(1, round((bbox[3]-bbox[1]) * density_y))
    if width * height > max_pixels:
        raise ValueError('Crop exceeds pixel limit.')
    aa, bb, cc, dd, ee, ff = inverse
    coefficients = (aa * im.width / density_x, cc * im.width / density_y,
                    (aa*bbox[0]+cc*bbox[1]+ee)*im.width,
                    bb * im.height / density_x, dd * im.height / density_y,
                    (bb*bbox[0]+dd*bbox[1]+ff)*im.height)
    out = im.transform((width, height), Image.Transform.AFFINE, coefficients, Image.Resampling.BICUBIC)
    return out, payload


def verify_visible(doc, page, candidate, rendered, settings):
    """Only use source pixels if they agree with the page's actual painted appearance.

    PDF clipping paths, occluding graphics, and masks otherwise require rendering.
    This comparison is conservative; it is not proof about sub-preview-pixel marks.
    """
    source = candidate.source
    if not source or not source['xref'] or source['mask']:
        return False
    try:
        crop, payload = oriented_source(doc, source, candidate.bbox, settings.max_pixels)
        source['encoding'] = payload['ext']
        sx, sy = rendered.width / page.rect.width, rendered.height / page.rect.height
        b = candidate.bbox
        target = rendered.crop((round(b[0]*sx), round(b[1]*sy), round(b[2]*sx), round(b[3]*sy))).convert('RGB')
        target.thumbnail((256, 256))
        probe = crop.convert('RGB').resize(target.size, Image.Resampling.LANCZOS)
        diff = np.abs(np.asarray(probe, dtype=np.int16)-np.asarray(target, dtype=np.int16))
        return bool(diff.mean() < 7 and np.quantile(diff, 0.98) < 35)
    except (ValueError, RuntimeError, OSError, ZeroDivisionError):
        return False
