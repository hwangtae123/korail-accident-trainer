"""확인용 그림 공용 함수 (쪽 그림 위 라벨)."""


def label_font(size: int = 14):
    """라벨용 TrueType 폰트 (ASCII 라벨만 쓰므로 Arial). 없으면 PIL 기본 폰트."""
    from PIL import ImageFont

    try:
        return ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def draw_label(d, font, y: float, text: str, color) -> None:
    """라벨을 쪽 왼쪽 여백 (영역 top 높이)에 흰 바탕으로 그린다. 영역 위에 그리면 붙어 있는 영역의 글자와 겹친다."""
    x0, y0, x1, y1 = d.textbbox((4, y), text, font=font)
    d.rectangle([x0 - 2, y0 - 1, x1 + 2, y1 + 1], fill=(255, 255, 255), outline=color)
    d.text((4, y), text, fill=color, font=font)
