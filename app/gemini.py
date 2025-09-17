from __future__ import annotations

import json
import random
from typing import Optional, List

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

LOW_BUDGET_POOL = [
	"перчатки для зала",
	"скакалка",
	"шейкер и креатин",
	"гири 16 кг",
	"мешок протеина",
	"антипригарная сковорода",
]


def _recent_items_key() -> str:
	# Key is namespaced by chat_id via DB column, so key string can be constant
	return "recent_items"


def _load_recent(chat_id: int) -> List[str]:
	recent_json = get_state(chat_id, _recent_items_key())
	if not recent_json:
		return []
	try:
		lst = json.loads(recent_json)
		return [str(x) for x in lst][:5]
	except Exception:
		return []


def _save_recent(chat_id: int, recent: List[str]) -> None:
	set_state(chat_id, _recent_items_key(), json.dumps(recent[:5], ensure_ascii=False))


def pick_item_for_budget(total: float, chat_id: Optional[int] = None) -> str:
	if total <= 0:
		total = 0
	candidates = [name for name, low, high in SUGGESTED_ITEMS if low <= total <= high]
	if not candidates:
		if total < 6000:
			candidates = LOW_BUDGET_POOL[:]
		else:
			candidates = ["половина айфона", "шлем топового уровня", "часть мотоцикла", "инструменты для гаража"]
	if not chat_id:
		return random.choice(candidates)

	recent = _load_recent(chat_id)
	# Pick first candidate not in recent
	for c in candidates:
		if c not in recent:
			choice = c
			break
	else:
		# All seen recently — rotate by taking the one least recently used (last in list)
		choice = candidates[0]
		for c in candidates:
			if c in recent and recent.index(c) == len(recent) - 1:
				choice = c
				break
	# Update recent LRU: put chosen first
	new_recent = [choice] + [x for x in recent if x != choice]
	_save_recent(chat_id, new_recent)
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