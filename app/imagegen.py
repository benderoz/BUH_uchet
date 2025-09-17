from __future__ import annotations

import base64
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

try:
	import google.generativeai as genai
except Exception:
	genai = None

from .config import get_settings


_SETTINGS = get_settings()


STYLE_PRESETS = {
	"шарж": "caricature, exaggerated features, humorous portrait, vibrant colors",
	"киберпанк": "cyberpunk, neon, dystopian city lights, chrome",
	"качки": "fitness, bodybuilders, gym, dramatic lighting",
	"фэнтези": "fantasy art, epic, mystical aura, painterly",
	"абстракция": "abstract shapes, bold colors, modern art poster",
	"алкоголики": "dark humor, gritty bar vibe, cheeky, comic poster",
	"бомжи": "gritty street comic style, satirical, rough textures",
	"ретро-плакат": "retro poster, vintage print, halftone",
	"аниме": "anime style, dynamic, bright colors",
	"комикс": "comic book style, halftone dots, bold outlines",
}


def generate_banner(text_top: str, text_bottom: Optional[str] = None, width: int = 800, height: int = 400) -> BytesIO:
	img = Image.new("RGB", (width, height), color=(20, 20, 20))
	draw = ImageDraw.Draw(img)
	font_big = ImageFont.load_default()
	font_small = ImageFont.load_default()
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


def _compose_image_prompt(user_descriptions: str, item: str, total: float, style: str) -> str:
	style_preset = STYLE_PRESETS.get(style, "")
	return (
		"Сгенерируй горизонтальное изображение 16:9: двое парней из Telegram (образы по фото), "
		f"держат/рассматривают предмет: {item}. "
		"Добавь атмосферу и детали по стилю. Без текста на изображении, без логотипов. "
		f"Бюджет: около {total:.0f} {_SETTINGS.default_currency}. "
		f"Стиль: {style} ({style_preset})."
	)


def generate_image_gemini(user_descriptions: str, item: str, total: float, style: str) -> Optional[BytesIO]:
	if genai is None:
		return None
	try:
		model = genai.GenerativeModel("imagen-3.0")
		prompt = _compose_image_prompt(user_descriptions, item, total, style)
		resp = model.generate_content(prompt)
		if not hasattr(resp, "media") and not getattr(resp, "candidates", None):
			return None
		# Attempt to get first image as base64
		b64 = None
		if getattr(resp, "media", None):
			for m in resp.media:
				if getattr(m, "mime_type", "").startswith("image/"):
					b64 = m.data
					break
		if b64 is None and getattr(resp, "candidates", None):
			# Some SDK variants return inline base64 in candidates
			try:
				b64 = resp.candidates[0].content.parts[0].inline_data.data
			except Exception:
				b64 = None
		if not b64:
			return None
		raw = base64.b64decode(b64)
		bio = BytesIO(raw)
		bio.seek(0)
		return bio
	except Exception:
		return None