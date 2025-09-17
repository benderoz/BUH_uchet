from __future__ import annotations

from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def generate_banner(text_top: str, text_bottom: Optional[str] = None, width: int = 800, height: int = 400) -> BytesIO:
	img = Image.new("RGB", (width, height), color=(20, 20, 20))
	draw = ImageDraw.Draw(img)
	# Basic fonts (Pillow default). On servers without fonts, load_default is safest.
	font_big = ImageFont.load_default()
	font_small = ImageFont.load_default()

	# Top text
	margin = 20
	w_top, h_top = draw.textbbox((0, 0), text_top, font=font_big)[2:]
	draw.text(((width - w_top) / 2, margin), text_top, font=font_big, fill=(240, 240, 240))

	if text_bottom:
		w_bot, h_bot = draw.textbbox((0, 0), text_bottom, font=font_small)[2:]
		draw.text(((width - w_bot) / 2, height - h_bot - margin), text_bottom, font=font_small, fill=(200, 200, 200))

	bio = BytesIO()
	img.save(bio, format="PNG")
	bio.seek(0)
	return bio