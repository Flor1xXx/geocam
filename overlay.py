"""Рисование надписи на фото + сохранение в системную галерею Android."""
from PIL import Image, ImageDraw, ImageFont, ImageOps
from kivy.resources import resource_find
from kivy.utils import platform


def render_overlay(src, dst, text):
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w, h = img.size
    fs = max(16, w // 34)
    font = ImageFont.truetype(resource_find("data/fonts/Roboto-Regular.ttf"), fs)
    draw = ImageDraw.Draw(img)
    pad = fs // 2
    max_w = w - 2 * pad

    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            test = (cur + " " + word).strip()
            if draw.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        lines.append(cur)

    lh = int(fs * 1.25)
    bar_h = lh * len(lines) + 2 * pad
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle([0, h - bar_h, w, h], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    draw = ImageDraw.Draw(img)
    y = h - bar_h + pad
    for ln in lines:
        draw.text((pad, y), ln, font=font, fill=(255, 255, 255))
        y += lh
    img.save(dst, "JPEG", quality=92)


def make_thumb(src, dst, size=256):
    img = Image.open(src)
    img.thumbnail((size, size))
    img.save(dst, "JPEG", quality=80)


def _resolver():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity.getContentResolver()


def save_to_gallery(path, name, uri_str=None):
    """Кладёт файл в Pictures/GeoCam через MediaStore. Если uri_str есть — перезаписывает."""
    if platform != "android":
        return None
    from jnius import autoclass
    Uri = autoclass("android.net.Uri")
    ContentValues = autoclass("android.content.ContentValues")
    Media = autoclass("android.provider.MediaStore$Images$Media")
    resolver = _resolver()
    with open(path, "rb") as f:
        data = f.read()

    stream = uri = None
    if uri_str:
        try:
            uri = Uri.parse(uri_str)
            stream = resolver.openOutputStream(uri, "wt")
        except Exception:
            uri = stream = None
    if stream is None:
        v = ContentValues()
        v.put("_display_name", name)
        v.put("mime_type", "image/jpeg")
        v.put("relative_path", "Pictures/GeoCam")
        uri = resolver.insert(Media.EXTERNAL_CONTENT_URI, v)
        stream = resolver.openOutputStream(uri)
    stream.write(data)
    stream.flush()
    stream.close()
    return uri.toString()


def delete_from_gallery(uri_str):
    if platform != "android" or not uri_str:
        return
    try:
        from jnius import autoclass
        _resolver().delete(autoclass("android.net.Uri").parse(uri_str), None, None)
    except Exception:
        pass
