import hashlib
import imagehash


def hashes(image, encoded=None):
    rgb = image.convert('RGB')
    pixels=image.convert('RGBA') if 'A' in image.getbands() else rgb
    size = f'{pixels.mode}:{pixels.width}x{pixels.height}:'.encode()
    return {'sha256': hashlib.sha256(encoded).hexdigest() if encoded else None,
            'pixel_hash': hashlib.sha256(size+pixels.tobytes()).hexdigest(),
            'phash': str(imagehash.phash(rgb))}


def relationship(a,b,distance=6):
    if a.get('sha256') and a.get('sha256') == b.get('sha256'):
        return 'identical source'
    if a.get('pixel_hash') and a.get('pixel_hash') == b.get('pixel_hash'):
        return 'identical pixels'
    if a.get('phash') and b.get('phash') and (int(a['phash'],16)^int(b['phash'],16)).bit_count() <= distance:
        return 'visually similar'
    return None
