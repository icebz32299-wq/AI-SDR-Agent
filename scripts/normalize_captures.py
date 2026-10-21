"""Normalize screenshot encoding without changing pixels or layout."""

from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent.parent
paths = list((root / "runtime" / "demo" / "frames").rglob("*.png")) + list(
    (root / "docs" / "screenshots").glob("*.png")
)
count = 0
for path in paths:
    if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        with Image.open(path) as im:
            image = im.convert("RGB")
        image.save(path, format="PNG")
        count += 1
print("Normalized screenshot encodings:", count)
