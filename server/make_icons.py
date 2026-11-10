"""Build app-owned geometric icon assets; not AI image generation."""
from pathlib import Path
from PIL import Image
import io
import resvg_py

root = Path(__file__).resolve().parent.parent / "app"
svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<rect x="8" y="8" width="240" height="240" rx="52" fill="#3068dd"/>
<path d="M48 62 Q88 54 128 76 Q168 54 208 62 L208 188 Q166 181 128 202 Q88 181 48 188 Z" fill="white"/>
<path d="M128 77 L128 201" fill="none" stroke="#3068dd" stroke-width="6"/>
<path d="M67 149 L110 149 L89 102 Z" fill="none" stroke="#3068dd" stroke-width="5" stroke-linejoin="round"/>
<path d="M150 108 L189 108 M150 128 L185 128 M150 148 L178 148" stroke="#3068dd" stroke-width="5" stroke-linecap="round"/>
</svg>'''
image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, width=256, height=256)))
for density, size in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    target = root / "android" / "app" / "src" / "main" / "res" / f"mipmap-{density}" / "ic_launcher.png"
    image.resize((size, size), Image.Resampling.LANCZOS).save(target)
image.save(root / "windows" / "runner" / "resources" / "app_icon.ico",
           sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
