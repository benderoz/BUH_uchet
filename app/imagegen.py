from __future__ import annotations

import base64
import logging
import os
import time
from io import BytesIO
from typing import Optional, List

from PIL import Image, ImageDraw, ImageFont

try:
	from google import genai as genai2
	from google.genai import types as genai2_types
except Exception:
	genai2 = None
	genai2_types = None

from .config import get_settings


logger = logging.getLogger(__name__)
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


def _is_image_valid(b: bytes) -> bool:
	try:
		bio = BytesIO(b)
		img = Image.open(bio)
		img.verify()
		bio.seek(0)
		img = Image.open(bio)
		w, h = img.size
		return (w >= 128 and h >= 128)
	except Exception:
		return False


def generate_banner(text_top: str, text_bottom: Optional[str] = None, width: int = 900, height: int = 500) -> BytesIO:
	img = Image.new("RGB", (width, height), color=(15, 15, 20))
	draw = ImageDraw.Draw(img)
	font_big = ImageFont.load_default()
	font_small = ImageFont.load_default()
	margin = 24
	w_top, h_top = draw.textbbox((0, 0), text_top, font=font_big)[2:]
	draw.text(((width - w_top) / 2, margin), text_top, font=font_big, fill=(240, 240, 240))
	if text_bottom:
		w_bot, h_bot = draw.textbbox((0, 0), text_bottom, font=font_small)[2:]
		draw.text(((width - w_bot) / 2, height - h_bot - margin), text_bottom, font=font_small, fill=(200, 200, 200))
	bio = BytesIO()
	img.save(bio, format="PNG")
	bio.seek(0)
	return bio


def generate_banner_for_item(item: str, style: str, total: float) -> BytesIO:
	top = f"Всего: {total:.0f} {_SETTINGS.default_currency}"
	bottom = f"Идея: {item} | Стиль: {style}"
	return generate_banner(top, bottom)


def _compose_image_prompt(item: str, total: float, style: str) -> str:
	style_preset = STYLE_PRESETS.get(style, "")
	return (
		"Создай горизонтальное изображение 16:9. Если приложены референс‑фото пользователей, "
		"сохрани черты их лица максимально узнаваемыми (форма лица, борода/усы, прическа, цвет кожи, глаза). "
		"Стилизуй под указанный стиль, но не меняй идентичность людей. "
		f"Двое парней держат/рассматривают предмет: {item}. "
		"Без текста и логотипов на изображении. "
		f"Общий бюджет (масштаб предмета): {total:.0f} {_SETTINGS.default_currency}. "
		f"Стиль: {style} ({style_preset})."
	)


def _stream_image_with_refs(prompt: str, photo_paths: Optional[List[str]]) -> Optional[BytesIO]:
	if genai2 is None or genai2_types is None:
		return None
	client = genai2.Client(api_key=os.getenv("GEMINI_API_KEY"))
	parts = [genai2_types.Part.from_text(text=prompt)]
	for p in (photo_paths or [])[:2]:
		try:
			with open(p, "rb") as f:
				parts.append(genai2_types.Part.from_inline_data(mime_type="image/jpeg", data=f.read()))
		except Exception as e:
			logger.warning("Failed to attach reference image %s: %s", p, e)
	contents = [genai2_types.Content(role="user", parts=parts)]
	config = genai2_types.GenerateContentConfig(response_modalities=["IMAGE"])  # focus on image
	buf = None
	for chunk in client.models.generate_content_stream(
		model=os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image-preview"),
		contents=contents,
		config=config,
	):
		if not getattr(chunk, "candidates", None):
			continue
		part0 = chunk.candidates[0].content.parts[0]
		if getattr(part0, "inline_data", None) and getattr(part0.inline_data, "data", None):
			buf = part0.inline_data.data
			break
	if not buf:
		return None
	data = base64.b64decode(buf) if isinstance(buf, str) else buf
	return BytesIO(data) if _is_image_valid(data) else None


def generate_image_gemini(user_descriptions: str, item: str, total: float, style: str, photo_paths: Optional[List[str]] = None) -> Optional[BytesIO]:
	prompt = _compose_image_prompt(item, total, style)
	# Retries with backoff
	delays = [0, 1.0, 2.0]
	for i, d in enumerate(delays):
		if d:
			time.sleep(d)
		bio = _stream_image_with_refs(prompt, photo_paths)
		if bio:
			bio.seek(0)
			return bio
	logger.warning("All image generation attempts failed; returning None")
	return None