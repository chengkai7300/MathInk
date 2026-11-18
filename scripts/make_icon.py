"""Generate assets/mathink.ico from code (multi-size Windows icon)."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "mathink.ico"


def draw(size: int) -> Image.Image:
    scale = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = max(2, int(14 * scale))
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=(79, 70, 229, 255))
    pts = [(x * scale, y * scale) for x, y in [(42, 12), (33, 17), (30, 27), (32, 38), (28, 48), (18, 52)]]
    d.line(pts, fill="white", width=max(1, int(5 * scale)), joint="curve")
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
