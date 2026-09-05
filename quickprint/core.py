"""Pure layout and color conversion; shared by preview and print."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageCms, ImageOps

PAPERS = [('3R · 89 × 127 mm', 89, 127), ('4R · 102 × 152 mm', 102, 152),
          ('5R · 127 × 178 mm', 127, 178), ('6R · 152 × 203 mm', 152, 203),
          ('A6 · 105 × 148 mm', 105, 148), ('A5 · 148 × 210 mm', 148, 210),
          ('A4 · 210 × 297 mm', 210, 297), ('自定义尺寸', 89, 127)]
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))

@dataclass
class Layout:
    paper_w: float = 89
    paper_h: float = 127
    x: float = 0
    y: float = 0
    w: float = 89
    h: float = 127
    fill: bool = True
    zoom: float = 1
    pan_x: float = 0
    pan_y: float = 0

    def validate(self):
        vals = (self.paper_w, self.paper_h, self.x, self.y, self.w, self.h, self.zoom, self.pan_x, self.pan_y)
        import math
        if not all(math.isfinite(v) for v in vals):
            raise ValueError('尺寸必须是有限数值。')
        if not (20 <= self.paper_w <= 420 and 20 <= self.paper_h <= 594):
            raise ValueError('纸张宽度需在 20–420 mm，高度需在 20–594 mm。')
        if self.w < 5 or self.h < 5 or self.x < 0 or self.y < 0:
            raise ValueError('打印区域至少 5 × 5 mm，且不能超出纸张。')
        if self.x + self.w > self.paper_w + .001 or self.y + self.h > self.paper_h + .001:
            raise ValueError('打印区域超出纸张，请调整位置或大小。')
        if not .1 <= self.zoom <= 4:
            raise ValueError('缩放需在 10%–400%。')

    def photo_rect(self, iw, ih):
        self.validate()
        if iw <= 0 or ih <= 0:
            raise ValueError('照片尺寸无效。')
        scale = (max if self.fill else min)(self.w / iw, self.h / ih) * self.zoom
        w, h = iw * scale, ih * scale
        return (self.x + (self.w - w) / 2 + self.pan_x,
                self.y + (self.h - h) / 2 + self.pan_y, w, h)


def load_photo(path):
    """Read orientation, respect embedded source ICC, flatten alpha on white."""
    with Image.open(path) as raw:
        if raw.width * raw.height > 80_000_000:
            raise ValueError('照片超过 8000 万像素，请先缩小后再打开。')
        raw.load()
        data = raw.info.get('icc_profile')
        image = ImageOps.exif_transpose(raw)
        alpha = image.convert('RGBA').getchannel('A') if 'A' in image.getbands() or 'transparency' in image.info else None
        if image.mode not in ('RGB', 'CMYK', 'LAB', 'L'):
            image = image.convert('RGB')
        if data:
            try:
                image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(BytesIO(data)), SRGB, outputMode='RGB', renderingIntent=1)
            except Exception as exc:
                raise ValueError('无法读取或转换照片内嵌的颜色配置，请先在图像软件中转换为 sRGB。') from exc
        elif image.mode in ('CMYK', 'LAB'):
            raise ValueError('该照片没有可用的源 ICC，请先转换为带 sRGB 配置的 JPG。')
        else:
            image = image.convert('RGB')
        if alpha is not None:
            bg = Image.new('RGB', image.size, 'white')
            bg.paste(image, mask=alpha)
            image = bg
        image.info.clear()  # EXIF/location/filenames never enter output.
        return image, ('已转换内嵌配置为 sRGB' if data else '无内嵌配置，按 sRGB 处理')


def check_profile(path):
    profile = ImageCms.getOpenProfile(str(path))
    if profile.profile.xcolor_space.strip() != 'RGB':
        raise ValueError('此版本支持 RGB 输出 ICC；CMYK 配置暂不支持。')
    ImageCms.buildTransform(SRGB, profile, 'RGB', 'RGB', renderingIntent=1)
    return ImageCms.getProfileDescription(profile).strip()


def convert_output(image, profile_path=None, intent=1, bpc=False):
    if not profile_path:
        return image.copy()
    check_profile(profile_path)
    return ImageCms.profileToProfile(image, SRGB, str(profile_path), outputMode='RGB',
        renderingIntent=intent, flags=ImageCms.Flags.BLACKPOINTCOMPENSATION if bpc else 0)


def render_page(image, layout, dpi=300):
    """Rasterize exactly the same mm geometry used by the interactive canvas."""
    layout.validate()
    if not 72 <= dpi <= 600:
        raise ValueError('输出分辨率需在 72–600 dpi。')
    k = dpi / 25.4
    size = (round(layout.paper_w * k), round(layout.paper_h * k))
    if size[0] * size[1] > 40_000_000:
        raise ValueError('输出超过 4000 万像素，请降低分辨率或纸张尺寸。')
    page = Image.new('RGB', size, 'white')
    x, y, w, h = layout.photo_rect(*image.size)
    box = (round(layout.x*k), round(layout.y*k), round((layout.x+layout.w)*k), round((layout.y+layout.h)*k))
    # Transform just the bounded print region; huge zoom never allocates a huge image.
    region = image.transform((box[2]-box[0], box[3]-box[1]), Image.Transform.AFFINE,
        (image.width/(w*k), 0, (box[0]-x*k)*image.width/(w*k),
         0, image.height/(h*k), (box[1]-y*k)*image.height/(h*k)),
        resample=Image.Resampling.BICUBIC, fillcolor='white')
    page.paste(region, box[:2])
    return page
