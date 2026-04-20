---
name: image-edit
description: Manipulate images: crop, resize, convert format, create thumbnails, optimize. Use when the user wants to transform an image file — e.g. "resize to 800px", "crop to 16:9", "convert to webp", "make a thumbnail", "optimize for web", or any image transformation before inserting into a project.
tools: Read, Bash, Glob
---

# Image Edit Skill

Manipulate images using ImageMagick and Python Pillow. Supports crop, resize, format conversion, thumbnail generation, and web optimization.

## How to use this skill

When the user provides an image path and a transformation request, execute the appropriate commands below. Always:
1. Read the image metadata first (dimensions, format, size)
2. Apply the requested transformations
3. Save the result (by default alongside the source, with a descriptive suffix or in the requested location)
4. Report the result: output path, new dimensions, new file size

---

## Step 1 — Inspect the source image

```bash
python3 - <<'EOF'
from PIL import Image
import os, sys

path = "IMAGE_PATH"
img = Image.open(path)
size_kb = os.path.getsize(path) / 1024
print(f"File   : {path}")
print(f"Format : {img.format}")
print(f"Mode   : {img.mode}")
print(f"Size   : {img.width} x {img.height} px")
print(f"Disk   : {size_kb:.1f} KB")
EOF
```

---

## Step 2 — Apply transformations

### Resize (keep aspect ratio)

```bash
python3 - <<'EOF'
from PIL import Image
import os

src  = "INPUT_PATH"
dst  = "OUTPUT_PATH"   # e.g. same dir with suffix _800w
width = 800            # target width in px

img = Image.open(src)
ratio = width / img.width
new_h = int(img.height * ratio)
img = img.resize((width, new_h), Image.LANCZOS)
img.save(dst)
print(f"Saved {dst}  ({img.width}x{img.height})")
EOF
```

### Resize to exact dimensions (may distort)

```bash
python3 - <<'EOF'
from PIL import Image
src = "INPUT_PATH"; dst = "OUTPUT_PATH"
img = Image.open(src).resize((WIDTH, HEIGHT), Image.LANCZOS)
img.save(dst)
print(f"Saved {dst}  ({img.width}x{img.height})")
EOF
```

### Resize and crop to fill exact dimensions (smart thumbnail)

```bash
python3 - <<'EOF'
from PIL import Image, ImageOps
src = "INPUT_PATH"; dst = "OUTPUT_PATH"
w, h = WIDTH, HEIGHT   # e.g. 400, 300
img = ImageOps.fit(Image.open(src), (w, h), Image.LANCZOS)
img.save(dst)
print(f"Saved {dst}  ({img.width}x{img.height})")
EOF
```

### Crop (box: left, top, right, bottom in pixels)

```bash
python3 - <<'EOF'
from PIL import Image
src = "INPUT_PATH"; dst = "OUTPUT_PATH"
box = (LEFT, TOP, RIGHT, BOTTOM)
img = Image.open(src).crop(box)
img.save(dst)
print(f"Saved {dst}  ({img.width}x{img.height})")
EOF
```

### Crop to aspect ratio (centered)

```bash
python3 - <<'EOF'
from PIL import Image
src = "INPUT_PATH"; dst = "OUTPUT_PATH"
ar_w, ar_h = 16, 9   # target aspect ratio

img = Image.open(src)
iw, ih = img.size
target_ratio = ar_w / ar_h
if iw / ih > target_ratio:          # image is too wide
    new_w = int(ih * target_ratio)
    left = (iw - new_w) // 2
    box = (left, 0, left + new_w, ih)
else:                                # image is too tall
    new_h = int(iw / target_ratio)
    top = (ih - new_h) // 2
    box = (0, top, iw, top + new_h)
img.crop(box).save(dst)
print(f"Saved {dst}  ({img.crop(box).width}x{img.crop(box).height})")
EOF
```

### Convert format

Supported formats: `JPEG`, `PNG`, `WEBP`, `GIF`, `BMP`, `TIFF`, `AVIF` (needs pillow-avif-plugin or Pillow≥9.2)

```bash
python3 - <<'EOF'
from PIL import Image
src = "INPUT_PATH"; dst = "OUTPUT_PATH"   # change extension to target format
fmt = "WEBP"    # or JPEG, PNG, etc.

img = Image.open(src)
# JPEG/WEBP need RGB (no alpha)
if fmt in ("JPEG",) and img.mode in ("RGBA", "P"):
    img = img.convert("RGB")
img.save(dst, format=fmt, quality=85)    # quality for lossy formats
print(f"Saved {dst}")
EOF
```

### Generate thumbnail (max box, preserves aspect ratio)

```bash
python3 - <<'EOF'
from PIL import Image
import os

src  = "INPUT_PATH"
dst  = "OUTPUT_PATH"    # e.g. image_thumb.jpg
size = (300, 300)       # max bounding box

img = Image.open(src).copy()
img.thumbnail(size, Image.LANCZOS)
# Convert if saving as JPEG
if dst.lower().endswith((".jpg", ".jpeg")) and img.mode in ("RGBA", "P"):
    img = img.convert("RGB")
img.save(dst)
print(f"Saved {dst}  ({img.width}x{img.height})")
EOF
```

### Optimize for web (lossy, strip metadata)

```bash
python3 - <<'EOF'
from PIL import Image
import os

src = "INPUT_PATH"; dst = "OUTPUT_PATH"
img = Image.open(src)

# Downscale if wider than 1920
if img.width > 1920:
    ratio = 1920 / img.width
    img = img.resize((1920, int(img.height * ratio)), Image.LANCZOS)

# Convert to RGB for JPEG output
if img.mode in ("RGBA", "P"):
    img = img.convert("RGB")

img.save(dst, format="JPEG", quality=82, optimize=True)
before = os.path.getsize(src) / 1024
after  = os.path.getsize(dst) / 1024
print(f"Saved {dst}  ({img.width}x{img.height})  {before:.0f}KB → {after:.0f}KB")
EOF
```

### Batch resize all images in a folder

```bash
python3 - <<'EOF'
from PIL import Image
from pathlib import Path

src_dir  = Path("SOURCE_DIR")
dst_dir  = Path("OUTPUT_DIR")
max_width = 1200
dst_dir.mkdir(parents=True, exist_ok=True)

exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
for f in src_dir.iterdir():
    if f.suffix.lower() in exts:
        img = Image.open(f)
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
        out = dst_dir / f.name
        img.save(out)
        print(f"  {f.name} → {img.width}x{img.height}")
print("Done.")
EOF
```

---

## Decision guide

| User request | Recipe to use |
|---|---|
| "resize to Xpx wide" | Resize (keep aspect ratio) |
| "resize to WxH" | Resize exact or Smart thumbnail |
| "crop to 16:9 / 4:3 / square" | Crop to aspect ratio |
| "crop region (x,y,w,h)" | Crop (box) |
| "convert to webp / jpg / png" | Convert format |
| "make a thumbnail" | Generate thumbnail |
| "optimize for web / reduce size" | Optimize for web |
| "process all images in folder" | Batch resize |

---

## Output naming convention

When no explicit output path is given, use these defaults:

| Operation | Suffix example |
|---|---|
| Resize to width | `photo_800w.jpg` |
| Thumbnail | `photo_thumb.jpg` |
| Format conversion | `photo.webp` |
| Crop | `photo_crop.jpg` |
| Web optimized | `photo_web.jpg` |
| Batch | `thumbnails/photo.jpg` |

Place outputs in the same directory as the source unless the user specifies otherwise or the project has a conventional assets folder (e.g. `public/images/`, `assets/`, `static/`).

---

## Notes

- Always use `Image.LANCZOS` (Pillow ≥ 10) for high-quality downscaling; fall back to `Image.ANTIALIAS` on older Pillow.
- JPEG does not support transparency; convert RGBA/P → RGB before saving as JPEG.
- For AVIF support, check `pillow-avif-plugin` is installed; otherwise use WEBP as a modern alternative.
- ImageMagick (`magick` / `convert`) is available as a fallback for exotic formats or complex compositing.
