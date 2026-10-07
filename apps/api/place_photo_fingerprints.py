"""Content identities for rehosted or resized public reference photographs."""
from functools import lru_cache
import hashlib
from io import BytesIO
import math
import statistics
from urllib.parse import urlsplit

from PIL import Image, ImageOps, ImageStat


def fingerprint_bytes(data):
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > 40_000_000:
            return {}
        image.draft('L', (32, 32))
        pixels = ImageOps.fit(ImageOps.exif_transpose(image).convert('L'), (32, 32))
        result = {'content_hash': hashlib.sha256(data).hexdigest()}
        if ImageStat.Stat(pixels).stddev[0] < 8:
            return result
        values = list(pixels.getdata())
        cosines = [[math.cos((2 * index + 1) * frequency * math.pi / 64) for index in range(32)]
                   for frequency in range(8)]
        rows = [[sum(values[y * 32 + x] * cosines[u][x] for x in range(32)) for u in range(8)]
                for y in range(32)]
        coefficients = [sum(rows[y][u] * cosines[v][y] for y in range(32))
                        for v in range(8) for u in range(8)]
        median = statistics.median(coefficients[1:])
        bits = sum((value > median) << index for index, value in enumerate(coefficients))
        result['perceptual_hash'] = f'{bits:016x}'
        return result


@lru_cache(maxsize=1024)
def image_fingerprint(url):
    from .place_photo_browser import _research
    helper = _research()
    try:
        host = urlsplit(url).hostname
        status, _, _, data = helper.Fetcher().fetch(url, 4 * 1024 * 1024, {host}, deadline_seconds=8)
        return fingerprint_bytes(data) if status == 200 else {}
    except (helper.ResearchError, OSError, ValueError, Image.DecompressionBombError):
        return {}
