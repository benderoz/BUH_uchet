from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from typing import Optional, Tuple, List

from PIL import Image, ImageDraw, ImageFont, ImageStat

try:
	import google.generativeai as genai
except Exception:
	genai = None

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
		img = Image.open(bio).convert("RGB")
		w, h = img.size
		if w < 128 or h < 128:
			return False
		stat = ImageStat.Stat(img)
		if max(stat.stddev) < 1.0:
			return False
		return True
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
		"Создай горизонтальное изображение 16:9: двое парней, вдохновляясь референс‑фото, "
		f"держат/рассматривают предмет: {item}. "
		"Добавь атмосферу и детали по стилю. Без текста и логотипов. "
		f"Общий бюджет (для масштаба предмета): {total:.0f} {_SETTINGS.default_currency}. "
		f"Стиль: {style} ({style_preset})."
	)


def _try_google_generativeai(prompt: str) -> Optional[BytesIO]:
	if genai is None:
		return None
	candidates = [
		os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image-preview").strip() or "gemini-2.5-flash-image-preview",
	]
	for name in candidates:
		try:
			model = genai.GenerativeModel(name)
			resp = model.generate_content(prompt)
			logger.info("Gemini Images response (model=%s): %s", name, getattr(resp, "_raw_response", str(resp))[:500])
			b64 = None
			if getattr(resp, "media", None):
				for m in resp.media:
					if getattr(m, "mime_type", "").startswith("image/") and getattr(m, "data", None):
						b64 = m.data
						break
			if b64 is None and getattr(resp, "candidates", None):
				try:
					b64 = resp.candidates[0].content.parts[0].inline_data.data
				except Exception:
					b64 = None
			if not b64:
				continue
			raw = base64.b64decode(b64)
			if not _is_image_valid(raw):
				logger.info("Generated image failed validation (integrity/flat).")
				continue
			bio = BytesIO(raw)
			bio.seek(0)
			return bio
		except Exception as e:
			msg = str(e)
			if "429" in msg:
				logger.warning("Gemini image quota exceeded: %s", e)
				return None
			logger.warning("Gemini image generation failed (google-generativeai): %s", e)
	return None


def _try_google_genai_stream(prompt: str, photo_paths: Optional[List[str]]) -> Optional[BytesIO]:
	if genai2 is None or genai2_types is None:
		return None
	try:
		client = genai2.Client(api_key=os.getenv("GEMINI_API_KEY"))
		parts = [genai2_types.Part.from_text(text=prompt)]
		# Attach up to two reference images if paths provided
		for p in (photo_paths or [])[:2]:
			try:
				with open(p, "rb") as f:
					data = f.read()
				parts.append(genai2_types.Part.from_inline_data(mime_type="image/jpeg", data=data))
			except Exception:
				continue
		contents = [genai2_types.Content(role="user", parts=parts)]
		config = genai2_types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
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
		if isinstance(buf, str):
			data = base64.b64decode(buf)
		else:
			data = buf
		if not _is_image_valid(data):
			logger.info("Streamed image failed validation (integrity/flat).")
			return None
		bio = BytesIO(data)
		bio.seek(0)
		return bio
	except Exception as e:
		msg = str(e)
		if "429" in msg:
			logger.warning("Gemini image quota exceeded (stream): %s", e)
			return None
		logger.warning("Gemini image generation failed (google-genai stream): %s", e)
		return None


def generate_image_gemini(user_descriptions: str, item: str, total: float, style: str, photo_paths: Optional[List[str]] = None) -> Optional[BytesIO]:
	prompt = _compose_image_prompt(item, total, style)
	bio = _try_google_generativeai(prompt)
	if bio:
		return bio
	return _try_google_genai_stream(prompt, photo_paths)