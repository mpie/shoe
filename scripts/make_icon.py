from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iconset", type=Path)
    parser.add_argument("--ico", type=Path)
    args = parser.parse_args()

    if args.iconset is not None:
        args.iconset.mkdir(parents=True, exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            _draw_icon(size).save(args.iconset / f"icon_{size}x{size}.png")
            _draw_icon(size * 2).save(args.iconset / f"icon_{size}x{size}@2x.png")

    if args.ico is not None:
        args.ico.parent.mkdir(parents=True, exist_ok=True)
        images = [_draw_icon(size) for size in (16, 32, 48, 64, 128, 256)]
        images[-1].save(args.ico, sizes=[(image.width, image.height) for image in images])


def _draw_icon(size: int) -> Image.Image:
    scale = size / 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    _rounded_rectangle(draw, [0, 0, size, size], radius=int(236 * scale), fill="#A294F9")
    draw.ellipse([int(30 * scale), int(20 * scale), int(770 * scale), int(760 * scale)], fill="#CDC1FF")
    draw.ellipse([int(420 * scale), int(310 * scale), int(1050 * scale), int(1050 * scale)], fill="#E5D9F2")

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shoe = _shoe_points(scale)
    shadow_draw.polygon([(x, y + int(44 * scale)) for x, y in shoe], fill=(31, 26, 46, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(22 * scale)))
    image.alpha_composite(shadow)

    draw = ImageDraw.Draw(image)
    draw.polygon(shoe, fill="#1f1a2e")
    draw.polygon(_shoe_highlight_points(scale), fill="#F5EFFF")
    draw.polygon(_sole_points(scale), fill="#CDC1FF")
    draw.polygon(_accent_points(scale), fill="#A294F9")

    for line in (
        ((360, 474), (492, 382)),
        ((432, 524), (560, 430)),
        ((520, 565), (644, 474)),
    ):
        draw.line(_scaled_line(line, scale), fill="#1f1a2e", width=max(2, int(28 * scale)))

    draw.ellipse(_scaled_box([294, 692, 350, 748], scale), fill="#1f1a2e")
    draw.ellipse(_scaled_box([724, 692, 780, 748], scale), fill="#1f1a2e")
    return image


def _shoe_points(scale: float) -> list[tuple[int, int]]:
    points = [
        (150, 628), (275, 622), (414, 575), (506, 512), (583, 397),
        (627, 337), (676, 354), (817, 506), (887, 558), (949, 566),
        (973, 596), (972, 696), (932, 734), (198, 734), (143, 690),
    ]
    return [(int(x * scale), int(y * scale)) for x, y in points]


def _shoe_highlight_points(scale: float) -> list[tuple[int, int]]:
    points = [
        (180, 640), (300, 634), (438, 586), (523, 528), (622, 386),
        (777, 545), (895, 592), (936, 606), (936, 668), (904, 694),
        (212, 694),
    ]
    return [(int(x * scale), int(y * scale)) for x, y in points]


def _sole_points(scale: float) -> list[tuple[int, int]]:
    points = [(216, 650), (832, 650), (882, 708), (220, 708), (166, 688)]
    return [(int(x * scale), int(y * scale)) for x, y in points]


def _accent_points(scale: float) -> list[tuple[int, int]]:
    points = [(638, 480), (690, 532), (510, 568), (466, 534)]
    return [(int(x * scale), int(y * scale)) for x, y in points]


def _scaled_line(points: tuple[tuple[int, int], tuple[int, int]], scale: float) -> list[tuple[int, int]]:
    return [(int(x * scale), int(y * scale)) for x, y in points]


def _scaled_box(points: list[int], scale: float) -> list[int]:
    return [int(point * scale) for point in points]


def _rounded_rectangle(draw: ImageDraw.ImageDraw, box: list[int], radius: int, fill: str) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


if __name__ == "__main__":
    main()
