from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def sanitize_image(source: Path, max_pixels: int = 1600) -> Path:
    """Verify the uploaded image, transpose it, and write an EXIF-free JPEG copy."""
    with Image.open(source) as candidate:
        candidate.verify()
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((max_pixels, max_pixels))
        output = source.with_name(f"{source.stem}-clean.jpg")
        image.save(output, format="JPEG", quality=88, optimize=True)
    return output
