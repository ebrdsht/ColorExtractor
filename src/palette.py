"""Palette utilities: extract and sort palettes from images."""
from PIL import Image
import colorsys
import numpy as np
from collections import Counter


def rgb_to_hex(rgb):
    return '#{:02X}{:02X}{:02X}'.format(*rgb)


def hex_to_rgb(hexstr):
    hexstr = hexstr.strip().lstrip('#')
    return tuple(int(hexstr[i:i+2], 16) for i in (0,2,4))


def relative_luminance(rgb):
    r, g, b = [c/255 for c in rgb]
    return 0.2126*r + 0.7152*g + 0.0722*b


class Palette:
    """Represents a palette: list of dicts with keys: rgb, hex, count, enabled"""

    def __init__(self):
        self.colors = []  # list of {'rgb':(r,g,b), 'hex':str, 'count':int, 'enabled':bool}

    MAX_QUANT_DIM = 800  # max dimension (width or height) used when quantizing for performance

    def from_image_quant(self, img: Image.Image, n: int, max_dim: int = MAX_QUANT_DIM):
        """Use Pillow's adaptive palette to find `n` colors.

        Improvements:
        - Ignores fully transparent pixels when building the quantization sample.
        - Resizes large images to `max_dim` on the longest edge to keep quantization fast.
        """
        if n <= 0:
            self.colors = []
            return
        # ensure RGBA working copy
        working = img.convert('RGBA')
        w, h = working.size
        # optionally resize to keep quantization fast
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            sample = working.resize(new_size, Image.LANCZOS)
        else:
            sample = working
        arr = np.array(sample)
        alpha = arr[:, :, 3]
        mask = alpha > 0
        # collect only non-transparent pixels
        rgb_pixels = arr[:, :, :3][mask]
        if rgb_pixels.size == 0:
            self.colors = []
            return
        # create a 1-pixel tall image of non-transparent pixels so quantization ignores transparency
        rgb_pixels = np.asarray(rgb_pixels, dtype=np.uint8).reshape(-1, 3)
        tmp = Image.fromarray(rgb_pixels.reshape(1, len(rgb_pixels), 3), mode='RGB')
        q = tmp.convert('P', palette=Image.ADAPTIVE, colors=n)
        palette = q.getpalette() or []  # flat R,G,B list
        counts = q.getcolors(maxcolors=65536) or []
        mapping = []
        for count, idx in counts:
            r = palette[idx*3]
            g = palette[idx*3+1]
            b = palette[idx*3+2]
            mapping.append({'rgb':(r, g, b), 'hex':rgb_to_hex((r, g, b)), 'count':int(count), 'enabled':True})
        # sort by count desc
        mapping.sort(key=lambda x: x['count'], reverse=True)
        self.colors = mapping

    # heuristics for 'max' mode
    MAX_SAMPLE_DIM = 1200
    FULL_SCAN_PIXEL_LIMIT = 6_000_000
    UNIQUE_THRESHOLD = 2048
    UNIQUE_RATIO_THRESHOLD = 0.05

    def estimate_unique_stats(self, img: Image.Image, max_sample_dim: int = None):
        """Estimate unique color statistics from a sampled image.

        Returns (sample_unique_count, sample_pixels_count, total_pixels).
        """
        if max_sample_dim is None:
            max_sample_dim = self.MAX_SAMPLE_DIM
        im = img.convert('RGBA')
        w, h = im.size
        arr_full = np.array(im)
        alpha = arr_full[:, :, 3]
        mask = alpha > 0
        total_pixels = int(mask.sum())
        if total_pixels == 0:
            return 0, 0, 0
        # sample if large
        if max(w, h) > max_sample_dim:
            scale = max_sample_dim / max(w, h)
            sample_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            sample = im.resize(sample_size, Image.LANCZOS)
            arr_sample = np.array(sample)
            mask_s = arr_sample[:, :, 3] > 0
            rgb_sample = arr_sample[:, :, :3][mask_s]
        else:
            rgb_sample = arr_full[:, :, :3][mask]
        if rgb_sample.size == 0:
            return 0, 0, total_pixels
        sample_pixels = rgb_sample.reshape(-1, 3)
        vals_sample = np.unique(sample_pixels, axis=0)
        return int(len(vals_sample)), int(len(sample_pixels)), int(total_pixels)

    def from_image_max(self, img: Image.Image, *, force_full_scan: bool = False, max_sample_dim: int = None, full_scan_pixel_limit: int = None, unique_threshold: int = None, unique_ratio_threshold: float = None, max_unique_error: int = None):
        """Return every unique color in the image (ignores fully transparent pixels).

        Parameters can override internal thresholds. If `force_full_scan` is True we'll attempt an exact
        full-resolution unique/color count even if the sample heuristics would normally avoid it.
        If `max_unique_error` is provided and the exact full-resolution unique set exceeds it, a
        ValueError will be raised to prevent creating a huge palette.
        """
        # resolve thresholds
        if max_sample_dim is None:
            max_sample_dim = self.MAX_SAMPLE_DIM
        if full_scan_pixel_limit is None:
            full_scan_pixel_limit = self.FULL_SCAN_PIXEL_LIMIT
        if unique_threshold is None:
            unique_threshold = self.UNIQUE_THRESHOLD
        if unique_ratio_threshold is None:
            unique_ratio_threshold = self.UNIQUE_RATIO_THRESHOLD

        im = img.convert('RGBA')
        w, h = im.size
        arr_full = np.array(im)
        # mask non-transparent
        alpha = arr_full[:, :, 3]
        mask = alpha > 0
        total_pixels = int(mask.sum())
        if total_pixels == 0:
            self.colors = []
            return
        # If image is very large, build a sampled image for estimation
        if max(w, h) > max_sample_dim:
            scale = max_sample_dim / max(w, h)
            sample_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            sample = im.resize(sample_size, Image.LANCZOS)
            arr_sample = np.array(sample)
            mask_s = arr_sample[:, :, 3] > 0
            rgb_sample = arr_sample[:, :, :3][mask_s]
        else:
            rgb_sample = arr_full[:, :, :3][mask]
        if rgb_sample.size == 0:
            self.colors = []
            return
        # sample statistics
        sample_pixels = rgb_sample.reshape(-1, 3)
        vals_sample = np.unique(sample_pixels, axis=0)
        sample_unique_count = len(vals_sample)
        sample_unique_ratio = sample_unique_count / len(sample_pixels)
        # Decide whether to attempt a full-resolution unique count
        do_full_scan = False
        if force_full_scan:
            do_full_scan = True
        elif (sample_unique_count <= unique_threshold or sample_unique_ratio <= unique_ratio_threshold) and total_pixels <= full_scan_pixel_limit:
            do_full_scan = True
        if do_full_scan:
            # compute exact unique colors/counts from the full-resolution pixels
            pixels = arr_full[:, :, :3][mask].reshape(-1, 3)
            vals, counts = np.unique(pixels, axis=0, return_counts=True)
            if max_unique_error is not None and len(vals) > max_unique_error:
                raise ValueError('There are too many colors to display!')
            mapping = []
            for v, c in zip(vals, counts):
                rgb = tuple(int(x) for x in v)
                mapping.append({'rgb': rgb, 'hex': rgb_to_hex(rgb), 'count': int(c), 'enabled': True})
            mapping.sort(key=lambda x: x['count'], reverse=True)
            self.colors = mapping
            return
        # Fallback: compute unique on the sampled image only (fast approximate)
        pixels = sample_pixels
        vals, counts = np.unique(pixels, axis=0, return_counts=True)
        mapping = []
        for v, c in zip(vals, counts):
            rgb = tuple(int(x) for x in v)
            mapping.append({'rgb': rgb, 'hex': rgb_to_hex(rgb), 'count': int(c), 'enabled': True})
        mapping.sort(key=lambda x: x['count'], reverse=True)
        self.colors = mapping

    def sort(self, mode='frequency', disabled_to_top=False):
        def hsv(rgb):
            r,g,b = [x/255 for x in rgb]
            return colorsys.rgb_to_hsv(r,g,b)
        if mode == 'frequency':
            key = lambda c: (-c['count'],)
        elif mode == 'hue':
            key = lambda c: (hsv(c['rgb'])[0],)
        elif mode == 'saturation':
            key = lambda c: (hsv(c['rgb'])[1],)
        elif mode == 'value':
            key = lambda c: (hsv(c['rgb'])[2],)
        elif mode == 'luminance':
            key = lambda c: (relative_luminance(c['rgb']),)
        elif mode == 'hex':
            key = lambda c: (c['hex'],)
        else:
            key = lambda c: (0,)
        # stable sort: we'll separate enabled/disabled if needed
        if disabled_to_top:
            # disabled first, then sort each partition
            disabled = [c for c in self.colors if not c.get('enabled', True)]
            enabled = [c for c in self.colors if c.get('enabled', True)]
            disabled.sort(key=key)
            enabled.sort(key=key)
            self.colors = disabled + enabled
        else:
            self.colors.sort(key=key)

    def toggle_enabled(self, index: int):
        if 0 <= index < len(self.colors):
            self.colors[index]['enabled'] = not self.colors[index].get('enabled', True)

    def add_color(self, rgb):
        hexc = rgb_to_hex(rgb)
        self.colors.append({'rgb':rgb, 'hex':hexc, 'count':0, 'enabled':True})

    def remove_color(self, index):
        if 0 <= index < len(self.colors):
            self.colors.pop(index)

    def hex_list(self, enabled_only=True):
        vals = [c['hex'] for c in self.colors if (c['enabled'] or not enabled_only)]
        return vals
