"""앱/설치 프로그램 아이콘 — 직접 그린 피카츄 얼굴 픽셀 아트 (게임 스프라이트를 쓰지 않는다)."""
from __future__ import annotations

from PIL import Image, ImageDraw

YELLOW = (255, 214, 51, 255)
SHADE = (235, 178, 30, 255)
LINE = (70, 45, 20, 255)
BLACK = (30, 30, 30, 255)
RED = (230, 70, 50, 255)
WHITE = (255, 255, 255, 255)


def pikachu_face(size: int = 256) -> Image.Image:
    base = 64
    im = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # 귀 (바깥선 → 노랑 → 검은 귀 끝)
    for ear in ([(14, 30), (5, 2), (25, 22)], [(50, 30), (59, 2), (39, 22)]):
        d.polygon(ear, fill=YELLOW, outline=LINE)
    d.polygon([(5, 2), (8, 12), (12, 9)], fill=BLACK)
    d.polygon([(59, 2), (56, 12), (52, 9)], fill=BLACK)
    # 얼굴
    d.ellipse((8, 18, 56, 60), fill=YELLOW)
    d.chord((10, 40, 54, 59), 20, 160, fill=SHADE)
    d.ellipse((8, 18, 56, 60), outline=LINE, width=2)
    # 눈 + 하이라이트
    for cx in (23, 41):
        d.ellipse((cx - 4, 31, cx + 4, 39), fill=BLACK)
        d.ellipse((cx - 2, 32, cx + 1, 35), fill=WHITE)
    # 볼
    for cx in (15, 49):
        d.ellipse((cx - 5, 41, cx + 5, 49), fill=RED)
    # 코, 입
    d.rectangle((31, 40, 33, 41), fill=BLACK)
    d.line([(28, 45), (30, 47), (32, 45), (34, 47), (36, 45)], fill=LINE, width=1)
    return im.resize((size, size), Image.NEAREST)


def save_ico(path) -> None:
    img = pikachu_face(256)
    img.save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128),
                          (256, 256)])


if __name__ == "__main__":
    pikachu_face(256).save("pikachu_preview.png")
