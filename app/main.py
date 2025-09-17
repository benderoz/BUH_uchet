from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

from .config import get_settings
from .db import init_db
from .gemini import generate_motivation
from .imagegen import generate_banner, generate_image_gemini, STYLE_PRESETS
from .logic import (
	add_expense,
	add_or_update_category,
	ensure_user,
	parse_message,
	sum_by_period,
	sum_by_user,
	top_categories,
	total_all_time,
	undo_last_today,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()

# Simple in-memory style choice per chat (stateless across restarts)
CHAT_STYLE: dict[int, str] = {}
STYLE_LIST = list(STYLE_PRESETS.keys())


def allowed_chat(chat_id: int) -> bool:
	if settings.allowed_chat_id is None:
		return True
	return chat_id == settings.allowed_chat_id


@dp.message(Command("style"))
async def cmd_style(message: Message) -> None:
	if not message.chat or not message.text:
		return
	parts = message.text.split(maxsplit=1)
	if len(parts) < 2:
		await message.reply("Задай стиль: /style <стиль>. Доступно: " + ", ".join(STYLE_LIST))
		return
	style = parts[1].strip().lower()
	if style not in STYLE_PRESETS:
		await message.reply("Не знаю такой стиль. Доступно: " + ", ".join(STYLE_LIST))
		return
	CHAT_STYLE[message.chat.id] = style
	await message.reply(f"Стиль установлен: {style}")


async def reply_stats(message: Message) -> None:
	if not message.chat:
		return
	cid = message.chat.id
	w = sum_by_period(cid, "week")
	m = sum_by_period(cid, "month")
	all_time = total_all_time(cid)
	per_user = sum_by_user(cid, "month")
	cats = top_categories(cid, "month")

	def h(x: float) -> str:
		return f"{x:.0f} {settings.default_currency}"

	per_user_lines = []
	for uid, total in per_user.items():
		per_user_lines.append(f"{uid}: {h(total)}")
	cat_lines = [f"{c}: {h(v)}" for c, v in cats]
	text = (
		"Сводка:\n" f"Неделя: {h(w)}\n" f"Месяц: {h(m)}\n" f"Всё время: {h(all_time)}\n\n"
		"По пользователям (месяц):\n" + ("\n".join(per_user_lines) or "—") + "\n\n"
		"Топ категории (месяц):\n" + ("\n".join(cat_lines) or "—")
	)
	await message.reply(text)


@dp.message(Command("start", "help"))
async def cmd_start(message: Message) -> None:
	if not message.chat:
		return
	if not allowed_chat(message.chat.id):
		await message.reply("Этот бот привязан к другому групповому чату.")
		return
	text = (
		"Добавляй траты просто сообщением: '1500 алкоголь бар' или '250 суши еда'.\n"
		"Команды: /stats, /week, /month, /all, /me, /categories, /addcat, /undo, /style.\n"
		"/style <стиль> — выбор стиля картинки: " + ", ".join(STYLE_LIST)
	)
	await message.reply(text)


@dp.message(Command("categories"))
async def cmd_categories(message: Message) -> None:
	await message.reply("Категории пополняются автоматически по алиасам. Добавить: /addcat <имя> | алиасы...")


@dp.message(Command("addcat"))
async def cmd_addcat(message: Message) -> None:
	user_id = message.from_user.id if message.from_user else 0
	if user_id not in settings.admins:
		await message.reply("Только админы могут добавлять категории.")
		return
	args = (message.text or "").split(maxsplit=1)
	if len(args) < 2:
		await message.reply("Формат: /addcat <имя> | алиас1 | алиас2 ...")
		return
	payload = args[1]
	parts = [p.strip() for p in payload.split("|")]
	name = parts[0]
	aliases = parts[1:] if len(parts) > 1 else []
	add_or_update_category(name, aliases)
	await message.reply(f"Категория '{name}' обновлена. Алиасы: {', '.join(aliases) if aliases else '—'}")


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
	await reply_stats(message)


@dp.message(Command("week"))
async def cmd_week(message: Message) -> None:
	if not message.chat:
		return
	total = sum_by_period(message.chat.id, "week")
	await message.reply(f"Неделя: {total:.0f} {settings.default_currency}")


@dp.message(Command("month"))
async def cmd_month(message: Message) -> None:
	if not message.chat:
		return
	total = sum_by_period(message.chat.id, "month")
	await message.reply(f"Месяц: {total:.0f} {settings.default_currency}")


@dp.message(Command("all"))
async def cmd_all(message: Message) -> None:
	if not message.chat:
		return
	total = total_all_time(message.chat.id)
	await message.reply(f"Всё время: {total:.0f} {settings.default_currency}")


@dp.message(Command("me"))
async def cmd_me(message: Message) -> None:
	if not message.chat or not message.from_user:
		return
	uid = message.from_user.id
	per_user = sum_by_user(message.chat.id, "month")
	total = per_user.get(uid, 0.0)
	await message.reply(f"За месяц ты потратил: {total:.0f} {settings.default_currency}")


@dp.message(Command("undo"))
async def cmd_undo(message: Message) -> None:
	if not message.from_user:
		return
	ok = undo_last_today(message.from_user.id)
	await message.reply("Удалил последнюю запись за сегодня." if ok else "Нечего отменять сегодня.")


async def _describe_user(bot: Bot, user_id: int) -> str:
	try:
		photos = await bot.get_user_profile_photos(user_id=user_id, offset=0, limit=1)
		count = photos.total_count or 0
		return f"есть {count} фото профиля"
	except Exception:
		return "фото профиля недоступны"


@dp.message(F.text)
async def on_text(message: Message) -> None:
	if not message.chat or not message.from_user or not message.text:
		return
	if not allowed_chat(message.chat.id):
		return

	ensure_user(message.from_user.id, message.from_user.username)
	parsed = parse_message(message.text)
	if not parsed:
		return

	_ = add_expense(
		tg_user_id=message.from_user.id,
		chat_id=message.chat.id,
		amount=parsed.amount,
		currency=parsed.currency,
		category=parsed.category,
		note=parsed.note,
	)
	all_time = total_all_time(message.chat.id)
	quip, idea = generate_motivation(all_time, parsed.amount, parsed.category, chat_id=message.chat.id)

	reply_text = (
		f"Добавлено: {parsed.amount:.0f} {parsed.currency} в '{parsed.category}'.\n"
		f"Итого за период: {all_time:.0f} {settings.default_currency}.\n\n{quip}"
	)
	await message.reply(reply_text, reply_to_message_id=message.message_id)

	# Image generation
	style = CHAT_STYLE.get(message.chat.id, random.choice(STYLE_LIST))
	user_desc_1 = await _describe_user(bot, message.from_user.id)
	desc = f"Пара пользователей: {user_desc_1}".strip()
	img = generate_image_gemini(desc, idea, all_time, style)
	if img:
		# Wrap BytesIO with FSInputFile and filename
		file = FSInputFile(img, filename="idea.png")
		await message.reply_photo(photo=file, caption=f"Стиль: {style}")
		return

	# Fallback banner
	subtitle_variants = [
		"Ещё немного — и берём полезную штуку",
		"Дальше — только трезвость и покупки",
		"Почти хватит на что-то стоящее",
	]
	banner = generate_banner(
		text_top=f"Всего: {all_time:.0f} {settings.default_currency}",
		text_bottom=random.choice(subtitle_variants),
	)
	file = FSInputFile(banner, filename="banner.png")
	await message.reply_photo(photo=file)


async def main() -> None:
	init_db()
	await dp.start_polling(bot)


if __name__ == "__main__":
	asyncio.run(main())