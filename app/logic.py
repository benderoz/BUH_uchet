from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Select, and_, func, select

from .config import get_settings
from .db import Category, Expense, User, session_scope


_AMOUNT_RE = re.compile(r"(?P<amount>[0-9]+(?:[\.,][0-9]{1,2})?)\s*(?P<currency>[₽рRUB$€])?", re.IGNORECASE)


DEFAULT_ALIASES: Dict[str, List[str]] = {
	"alcohol": [
		"алкоголь", "алко", "пиво", "вино", "джин", "ром", "текила", "водка", "коньяк", "бар",
	],
	"food": [
		"еда", "ресторан", "рестик", "суши", "бургер", "кофе", "кафе", "пицца", "доставка",
	],
	"smoking": [
		"курилки", "сигареты", "сигара", "вейп", "iqos", "табак",
	],
	"fun": [
		"развлечения", "кино", "концерт", "бар", "игры", "клуб",
	],
	"tech": [
		"техника", "гаджеты", "электроника", "кабели", "наушники",
	],
	"clothes": [
		"одежда", "куртка", "кроссовки", "кеды", "штаны", "футболка",
	],
	"transport": [
		"такси", "бензин", "топливо", "метро", "транспорт",
	],
	"прочее": [
		"прочее", "другое", "без категории",
	],
}


@dataclass
class ParsedMessage:
	amount: float
	currency: str
	category: str
	note: Optional[str]


def normalize_amount(text: str) -> Optional[Tuple[float, str]]:
	m = _AMOUNT_RE.search(text.replace(" ", ""))
	if not m:
		m2 = _AMOUNT_RE.search(text)
		if not m2:
			return None
		m = m2
	amount_str = m.group("amount").replace(",", ".")
	try:
		amount = float(amount_str)
	except ValueError:
		return None
	currency = m.group("currency") or "₽"
	if currency.lower() in {"r", "rub", "р"}:
		currency = "₽"
	return amount, currency


def load_alias_map() -> Dict[str, str]:
	# Lowercase alias -> category key
	alias_to_cat: Dict[str, str] = {}
	for cat, aliases in DEFAULT_ALIASES.items():
		for a in [cat] + aliases:
			alias_to_cat[a.lower()] = cat
	# Extend with DB categories
	with session_scope() as s:
		for row in s.execute(select(Category)).scalars():
			alias_to_cat[row.name.lower()] = row.name
			if row.aliases:
				for a in row.aliases.split("|"):
					alias_to_cat[a.strip().lower()] = row.name
	return alias_to_cat


def guess_category(rest_text: str, alias_map: Dict[str, str]) -> str:
	words = re.findall(r"[\wЁёА-Яа-я]+", rest_text.lower())
	for w in words:
		if w in alias_map:
			return alias_map[w]
	return "прочее"


def parse_message(text: str) -> Optional[ParsedMessage]:
	amount_currency = normalize_amount(text)
	if not amount_currency:
		return None
	amount, currency = amount_currency
	# Remove the first found amount+currency from text to analyze the rest
	rest = _AMOUNT_RE.sub(" ", text, count=1)
	alias_map = load_alias_map()
	category = guess_category(rest, alias_map)
	note = rest.strip() or None
	return ParsedMessage(amount=amount, currency=currency, category=category, note=note)


# CRUD helpers

def ensure_user(tg_user_id: int, username: Optional[str]) -> None:
	with session_scope() as s:
		existing = s.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
		if existing:
			if username and existing.username != username:
				existing.username = username
			return
		s.add(User(tg_user_id=tg_user_id, username=username))


def add_expense(tg_user_id: int, chat_id: int, amount: float, currency: str, category: str, note: Optional[str]) -> Expense:
	with session_scope() as s:
		exp = Expense(
			tg_user_id=tg_user_id,
			chat_id=chat_id,
			amount=round(amount, 2),
			currency=currency,
			category=category,
			note=note,
		)
		s.add(exp)
		s.flush()
		# refresh managed object
		_ = exp.id
		return exp


def undo_last_today(tg_user_id: int) -> bool:
	start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
	with session_scope() as s:
		q = (
			select(Expense)
			.where(and_(Expense.tg_user_id == tg_user_id, Expense.created_at >= start))
			.order_by(Expense.id.desc())
		)
		last = s.execute(q).scalars().first()
		if not last:
			return False
		s.delete(last)
		return True


# Stats

def period_bounds(kind: str) -> Tuple[datetime, datetime]:
	now = datetime.now(timezone.utc)
	if kind == "week":
		# Monday 00:00 UTC
		weekday = now.weekday()
		start = (now - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
		return start, now
	if kind == "month":
		start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
		return start, now
	return datetime.fromtimestamp(0, tz=timezone.utc), now


def sum_by_period(chat_id: int, kind: str) -> float:
	start, end = period_bounds(kind)
	with session_scope() as s:
		q = select(func.coalesce(func.sum(Expense.amount), 0.0)).where(
			and_(Expense.chat_id == chat_id, Expense.created_at >= start, Expense.created_at <= end)
		)
		return float(s.execute(q).scalar_one())


def sum_by_user(chat_id: int, kind: str) -> Dict[int, float]:
	start, end = period_bounds(kind)
	with session_scope() as s:
		q = (
			select(Expense.tg_user_id, func.coalesce(func.sum(Expense.amount), 0.0))
			.where(and_(Expense.chat_id == chat_id, Expense.created_at >= start, Expense.created_at <= end))
			.group_by(Expense.tg_user_id)
		)
		rows = s.execute(q).all()
		return {uid: float(total) for uid, total in rows}


def top_categories(chat_id: int, kind: str, limit: int = 3) -> List[Tuple[str, float]]:
	start, end = period_bounds(kind)
	with session_scope() as s:
		q = (
			select(Expense.category, func.coalesce(func.sum(Expense.amount), 0.0))
			.where(and_(Expense.chat_id == chat_id, Expense.created_at >= start, Expense.created_at <= end))
			.group_by(Expense.category)
			.order_by(func.sum(Expense.amount).desc())
		)
		rows = s.execute(q).all()
		return [(c, float(v)) for c, v in rows[:limit]]


def total_all_time(chat_id: int) -> float:
	with session_scope() as s:
		q = select(func.coalesce(func.sum(Expense.amount), 0.0)).where(Expense.chat_id == chat_id)
		return float(s.execute(q).scalar_one())


def add_or_update_category(name: str, aliases: List[str]) -> None:
	name = name.strip()
	alias_str = "|".join(sorted({a.strip() for a in aliases if a.strip()})) or None
	with session_scope() as s:
		existing = s.execute(select(Category).where(Category.name == name)).scalar_one_or_none()
		if existing:
			existing.aliases = alias_str
			return
		s.add(Category(name=name, aliases=alias_str))