from __future__ import annotations

import json
import random
from typing import Optional

import google.generativeai as genai

from .config import get_settings
from .db import get_state, set_state


_SETTINGS = get_settings()

genai.configure(api_key=_SETTINGS.gemini_api_key)

# Use a faster model; add safety via prompt, but allow edgy tone
_MODEL = genai.GenerativeModel("gemini-1.5-flash")


SUGGESTED_ITEMS = [
	("мотоциклетный шлем", 15000, 80000),
	("абонемент в зал на 6 мес.", 10000, 40000),
	("пол айфона", 40000, 80000),
	("гантели + скамья", 15000, 60000),
	("чугунная сковорода + нож шефа", 6000, 20000),
	("билеты на концерт (2–4)", 6000, 40000),
	("наушники", 10000, 50000),
	("кожаная куртка", 15000, 70000),
	("кроссовки топовые", 10000, 40000),
	("комплект резины на авто (часть)", 30000, 120000),
	("экшн-камера", 15000, 40000),
	("мясорубка + набор ножей", 8000, 30000),
]


def _recent_items_key(chat_id: int) -> str:
	return f"recent_items:{chat_id}"


def pick_item_for_budget(total: float, chat_id: Optional[int] = None) -> str:
	candidates = [name for name, low, high in SUGGESTED_ITEMS if low <= total <= high]
	if not candidates:
		if total < 6000:
			candidates = ["мешок протеина", "гири 16 кг", "сковорода и антипригар"]
		else:
			candidates = ["половина айфона", "шлем топового уровня", "часть мотоцикла"]
	recent_json = get_state(chat_id, _recent_items_key(chat_id)) if chat_id is not None else None
	recent = set()
	if recent_json:
		try:
			recent = set(json.loads(recent_json))
		except Exception:
			recent = set()
	pool = [c for c in candidates if c not in recent] or candidates
	choice = random.choice(pool)
	# update recent (keep last 5)
	if chat_id is not None:
		new_recent = [choice] + [x for x in list(recent) if x != choice]
		set_state(chat_id, _recent_items_key(chat_id), json.dumps(new_recent[:5], ensure_ascii=False))
	return choice


def generate_motivation(total_all_time: float, last_amount: float, last_category: str, chat_id: Optional[int] = None) -> str:
	idea = pick_item_for_budget(total_all_time, chat_id=chat_id)
	# Increase randomness via generation config
	gen_config = {
		"temperature": 1.2,
		"top_p": 0.95,
		"top_k": 40,
	}
	prompt = (
		"Мы вдвоём ведём учёт трат на алкоголь/развлечения. "
		f"Последний тратились: {last_amount:.0f} {_SETTINGS.default_currency} на категорию '{last_category}'. "
		f"Всего за период: {total_all_time:.0f} {_SETTINGS.default_currency}. "
		"Сгенерируй 1–2 очень коротких предложения, чёрный юмор с матерком, без эмодзи. "
		"Избегай дискриминации групп и прямых угроз, но допускай сарказм и жёсткость. "
		"Вставь идею покупки, которую уже могли бы осилить на общий бюджет, и каждый раз формулируй по-новому. "
		f"Идея покупки: {idea}. "
		"Используй неожиданные сравнения, избегай шаблонов, не повторяй прошлые формулировки."
	)
	try:
		resp = _MODEL.generate_content(prompt, generation_config=gen_config)
		text = (resp.text or "").strip()
		if not text:
			return f"Жгите дальше в '{last_category}', ага. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}."
		return text
	except Exception:
		return f"Жгите дальше в '{last_category}'. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}."