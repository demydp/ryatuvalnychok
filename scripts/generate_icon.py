"""
Разовый генератор dashboard.ico для ярлыка на рабочем столе — без внешних зависимостей
(Pillow не установлен, тянуть его в venv ради одной иконки не стали). Рисует простой
скруглённый квадрат в акцентном цвете дашборда (#bd94eb) с белым значком "график" —
и пакует несколько размеров (16/32/48/256) в один .ico вручную по формату ICO/BMP.
Запускается один раз при подготовке ярлыка, самому приложению не нужен.
"""
import struct

BG = (0xBD, 0x94, 0xEB, 255)  # #bd94eb — фирменный акцент дашборда
BG_DARK = (0x9D, 0x6F, 0xD9, 255)
FG = (255, 255, 255, 255)


def rounded_mask(x, y, size, radius):
    """True, если пиксель (x, y) внутри скруглённого квадрата size x size."""
    cx = min(max(x, radius), size - 1 - radius)
    cy = min(max(y, radius), size - 1 - radius)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius + 1


def draw(size):
    """RGBA-пиксели size x size: скруглённый фон + 3 бара по возрастанию (типичный
    значок "дашборд/аналитика")."""
    radius = max(2, size // 5)
    pixels = [[(0, 0, 0, 0)] * size for _ in range(size)]

    for y in range(size):
        for x in range(size):
            if rounded_mask(x, y, size, radius):
                # лёгкий диагональный градиент для объёма
                t = (x + y) / (2 * size)
                r = round(BG[0] + (BG_DARK[0] - BG[0]) * t)
                g = round(BG[1] + (BG_DARK[1] - BG[1]) * t)
                b = round(BG[2] + (BG_DARK[2] - BG[2]) * t)
                pixels[y][x] = (r, g, b, 255)

    # три бара возрастающей высоты внутри квадрата — простой значок графика
    margin = max(2, round(size * 0.22))
    gap = max(1, round(size * 0.06))
    bar_w = max(1, (size - 2 * margin - 2 * gap) // 3)
    heights = [round(size * 0.28), round(size * 0.45), round(size * 0.62)]
    base_y = size - margin

    x0 = margin
    for i, h in enumerate(heights):
        bx0 = x0 + i * (bar_w + gap)
        bx1 = min(bx0 + bar_w, size - margin)
        by0 = base_y - h
        for y in range(max(0, by0), base_y):
            for x in range(bx0, bx1):
                if 0 <= x < size and 0 <= y < size:
                    pixels[y][x] = FG
    return pixels


def bmp_bytes(pixels, size):
    """BITMAPINFOHEADER + 32bpp BGRA пиксели (снизу вверх) + пустая AND-маска."""
    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight (XOR + AND маска)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression (BI_RGB)
        size * size * 4,  # biSizeImage
        0, 0,        # biXPelsPerMeter, biYPelsPerMeter
        0, 0,        # biClrUsed, biClrImportant
    )
    body = bytearray()
    for y in range(size - 1, -1, -1):  # снизу вверх
        for x in range(size):
            r, g, b, a = pixels[y][x]
            body += bytes((b, g, r, a))
    and_mask_row_bytes = ((size + 31) // 32) * 4
    and_mask = bytes(and_mask_row_bytes * size)  # все нули = непрозрачность из альфы
    return header + bytes(body) + and_mask


def build_ico(path, sizes=(16, 32, 48, 256)):
    images = [(s, bmp_bytes(draw(s), s)) for s in sizes]

    entries = bytearray()
    data = bytearray()
    offset = 6 + 16 * len(images)
    for s, img in images:
        w = s if s < 256 else 0
        h = s if s < 256 else 0
        entries += struct.pack(
            "<BBBBHHII", w, h, 0, 0, 1, 32, len(img), offset
        )
        data += img
        offset += len(img)

    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(images)))
        f.write(entries)
        f.write(data)


if __name__ == "__main__":
    import os

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard.ico")
    build_ico(out_path)
    print(f"Готово: {out_path}")
