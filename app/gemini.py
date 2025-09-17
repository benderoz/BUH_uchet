from __future__ import annotations

import random
from typing import Optional

import google.generativeai as genai

from .config import get_settings


_SETTINGS = get_settings()

genai.configure(api_key=_SETTINGS.gemini_api_key)

_MODEL = genai.GenerativeModel("gemini-1.5-flash")


SUGGESTED_ITEMS = [
	("мотоциклетный шлем", 15000, 60000),
	("абонемент в зал на 3 мес.", 6000, 20000),
	("пол айфона", 40000, 70000),
	("гантели и эспандеры", 5000, 20000),
	("чугунная сковорода и нож", 4000, 12000),
	("билеты на концерт", 3000, 20000),
	("наушники", 7000, 30000),
	("куртка", 8000, 30000),
	("кроссовки", 6000, 20000),
	("диски на авто (часть)", 20000, 80000),
]


def pick_item_for_budget(total: float) -> str:
	candidates = [name for name, low, high in SUGGESTED_ITEMS if low <= total <= high]
	if not candidates:
		# fallback: scale idea
		if total < 3000:
			return "мешок протеина (часть)"
		if total > 80000:
			return "мотошлем топового уровня или приличную долю мотоцикла"
		return "что-то из спортивного или музыкального снаряжения"
	return random.choice(candidates)


def generate_motivation(total_all_time: float, last_amount: float, last_category: str) -> str:
	idea = pick_item_for_budget(total_all_time)
	prompt = (
		"Мы вдвоём ведём учёт трат на алкоголь/развлечения. "
		f"Последний тратились: {last_amount:.0f} {_SETTINGS.default_currency} на категорию '{last_category}'. "
		f"Всего за период: {total_all_time:.0f} {_SETTINGS.default_currency}. "
		"Сгенерируй короткую жёстко-юморную мотивацию (1–2 предложения) без эмодзи. "
		"Избегай оскорбления групп людей, но можно жёсткий тон. "
		f"Упомяни, что уже могли бы купить: {idea}."
	)
	try:
		resp = _MODEL.generate_content(prompt)
		text = (resp.text or "").strip()
		if not text:
			return f"Хватит сливать в '{last_category}'. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}."
		return text
	except Exception:
		return f"Хватит сливать в '{last_category}'. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}."