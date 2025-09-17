from __future__ import annotations

import json
import random
from typing import Optional, List

import google.generativeai as genai

from .config import get_settings
from .db import get_state, set_state


_SETTINGS = get_settings()

genai.configure(api_key=_SETTINGS.gemini_api_key)

# Use a faster model; allow edgy tone via prompts
_MODEL = genai.GenerativeModel("gemini-1.5-flash")


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


def _ask_gemini_for_items(total: float, n: int = 4) -> List[str]:
	gen_config = {"temperature": 1.0, "top_p": 0.95, "top_k": 40}
	prompt = (
		"Ты помощник по покупкам. По списку интересов пользователей и бюджету предложи варианты вещей, "
		"которые можно купить СЕЙЧАС на этот бюджет в моей стране (грубые цены). "
		"Нужны ИМЕНА ПРЕДМЕТОВ, коротко, без брендов (если не очевидно), без эмодзи. "
		"Ответь ТОЛЬКО JSON массивом строк (пример: [\"гантели 24 кг\", \"мотоциклетный шлем\"]). Без пояснений.\n"
		f"Интересы: {', '.join(INTERESTS)}\n"
		f"Бюджет: примерно {total:.0f} {_SETTINGS.default_currency}\n"
		f"Количество вариантов: {n}"
	)
	try:
		resp = _MODEL.generate_content(prompt, generation_config=gen_config)
		text = (resp.text or "").strip()
		# Try strict JSON parse first
		items = json.loads(text)
		if not isinstance(items, list):
			raise ValueError("not a list")
		return [str(x).strip() for x in items if str(x).strip()]
	except Exception:
		# Fallback minimal sensible defaults based on budget tiers
		if total < 8000:
			return ["перчатки для зала", "скакалка", "крепления для турника", "шейкер и креатин"]
		if total < 20000:
			return ["гантели и эспандеры", "чугунная сковорода", "нож шефа", "билеты на концерт"]
		if total < 50000:
			return ["наушники", "абонемент в зал на 6 мес.", "экшн-камера", "кожаная куртка"]
		return ["мотоциклетный шлем", "часть комплекта резины", "инструменты для гаража", "часть айфона"]


def pick_item_for_budget(total: float, chat_id: Optional[int] = None) -> str:
	candidates = _ask_gemini_for_items(total, n=5)
	if not chat_id:
		return random.choice(candidates) if candidates else "что-то полезное"
	recent = _load_recent(chat_id)
	for c in candidates:
		if c not in recent:
			choice = c
			break
	else:
		choice = candidates[0] if candidates else "что-то полезное"
	new_recent = [choice] + [x for x in recent if x != choice]
	_save_recent(chat_id, new_recent)
	return choice


def generate_motivation(total_all_time: float, last_amount: float, last_category: str, chat_id: Optional[int] = None) -> str:
	idea = pick_item_for_budget(total_all_time, chat_id=chat_id)
	gen_config = {"temperature": 1.25, "top_p": 0.95, "top_k": 40}
	prompt = (
		"Мы вдвоём ведём учёт трат на алкоголь/развлечения. "
		f"Последний тратились: {last_amount:.0f} {_SETTINGS.default_currency} на категорию '{last_category}'. "
		f"Всего за период: {total_all_time:.0f} {_SETTINGS.default_currency}. "
		"Сгенерируй 1–2 очень коротких предложения, чёрный юмор с матерком, без эмодзи. "
		"Избегай дискриминации групп и прямых угроз, но допускай сарказм и жёсткость. "
		"Вставь идею покупки, которую уже могли бы купить на общий бюджет, формулируй свежо, без повторов. "
		f"Идея покупки: {idea}. "
		"Не упоминай, что ты ИИ."
	)
	try:
		resp = _MODEL.generate_content(prompt, generation_config=gen_config)
		text = (resp.text or "").strip()
		if not text:
			return f"Жгите дальше в '{last_category}', ага. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}."
		return text
	except Exception:
		return f"Жгите дальше в '{last_category}'. На {total_all_time:.0f} {_SETTINGS.default_currency} уже взяли бы: {idea}."