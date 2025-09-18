from __future__ import annotations

import json
import os
import random
from typing import Optional, List, Tuple

import google.generativeai as genai

from .config import get_settings
from .db import get_state, set_state


_SETTINGS = get_settings()

genai.configure(api_key=_SETTINGS.gemini_api_key)

# Text model (configurable, default to Gemini 2.5 Flash)
_TEXT_MODEL_NAME = os.getenv("TEXT_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
_MODEL = genai.GenerativeModel(_TEXT_MODEL_NAME)


INTERESTS = [
	"спорт (качалка)", "авто", "мотоциклы", "одежда", "секс",
	"техника", "еда", "кулинария", "тяжёлая музыка", "концерты",
]


def _recent_items_key() -> str:
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


def _ask_gemini_for_items(total: float, n: int = 6, recent: Optional[List[str]] = None) -> List[str]:
	recent = recent or []
	gen_config = {"temperature": 1.1, "top_p": 0.95, "top_k": 50}
	prompt = (
		"Ты помощник по покупкам. Дай ИДЕИ ПРЕДМЕТОВ строго на основе ОБЩЕЙ суммы за весь период (не последней траты). "
		"Ответь ТОЛЬКО JSON массивом коротких названий вещей, без брендов и эмодзи.\n"
		f"Интересы: {', '.join(INTERESTS)}\n"
		f"Общая сумма за весь период: {total:.0f} {_SETTINGS.default_currency}\n"
		f"Избегай повторов из недавнего списка: {json.dumps(recent, ensure_ascii=False)}\n"
		f"Сколько вариантов нужно: {n}"
	)
	try:
		resp = _MODEL.generate_content(prompt, generation_config=gen_config)
		text = (resp.text or "").strip()
		items = json.loads(text)
		if not isinstance(items, list):
			raise ValueError("not a list")
		return [str(x).strip() for x in items if str(x).strip()]
	except Exception:
		# Safety fallback by tiers
		if total < 8000:
			base = ["перчатки для зала", "скакалка", "крепления для турника", "шейкер и креатин"]
		elif total < 20000:
			base = ["гантели и эспандеры", "чугунная сковорода", "нож шефа", "билеты на концерт"]
		elif total < 50000:
			base = ["наушники", "абонемент в зал на 6 мес.", "экшн-камера", "кожаная куртка"]
		else:
			base = ["мотоциклетный шлем", "часть комплекта резины", "инструменты для гаража", "часть айфона"]
		return base


def pick_item_for_budget(total: float, chat_id: Optional[int] = None) -> str:
	recent = _load_recent(chat_id) if chat_id else []
	candidates = _ask_gemini_for_items(total, n=8, recent=recent)
	if not candidates:
		return "что-то полезное"
	# Prefer first unseen, else random
	for c in candidates:
		if c not in recent:
			choice = c
			break
	else:
		choice = random.choice(candidates)
	if chat_id:
		new_recent = [choice] + [x for x in recent if x != choice]
		_save_recent(chat_id, new_recent)
	return choice


def generate_motivation(total_all_time: float, last_amount: float, last_category: str, chat_id: Optional[int] = None) -> Tuple[str, str]:
	idea = pick_item_for_budget(total_all_time, chat_id=chat_id)
	gen_config = {"temperature": 1.25, "top_p": 0.95, "top_k": 40}
	prompt = (
		"Мы вдвоём ведём учёт трат. Используй ОБЩУЮ сумму за весь период для сравнений (не последнюю трату). "
		f"Последняя трата: {last_amount:.0f} {_SETTINGS.default_currency} на '{last_category}'. "
		f"Общая сумма за весь период: {total_all_time:.0f} {_SETTINGS.default_currency}. "
		"Сгенерируй 1–2 очень коротких предложения, чёрный юмор с матерком, без эмодзи. "
		"Избегай дискриминации групп и прямых угроз, но допускай сарказм и жёсткость. "
		f"Упомяни предмет, который реально можно было бы купить на общую сумму: {idea}. "
		"Формулируй свежо, не повторяйся."
	)
	try:
		resp = _MODEL.generate_content(prompt, generation_config=gen_config)
		text = (resp.text or "").strip()
		if not text:
			return (f"Жгите дальше в '{last_category}', ага. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}.", idea)
		return (text, idea)
	except Exception:
		return (f"Жгите дальше в '{last_category}'. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}.", idea)