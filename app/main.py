from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, PhotoSize

from .config import get_settings
from .db import init_db
from .gemini import generate_motivation
from .imagegen import generate_banner, generate_image_gemini, STYLE_PRESETS, generate_banner_for_item
from .logic import (
	add_expense,
	add_or_update_category,
	append_aliases,
	ensure_user,
	parse_message,
	sum_by_period,
	sum_by_user,
	top_categories,
	total_all_time,
	undo_last_today,
)
from .db import (
	add_wishlist_item,
	list_wishlist_items,
	list_wishlist,
	remove_wishlist_item,
	remove_wishlist_by_id,
	pick_random_wishlist_item,
	list_categories_with_aliases,
	add_user_photo,
	pick_random_user_photo,
	pick_random_other_user_photo,
	list_user_photos_with_ids,
	remove_user_photo_by_id,
	delete_expenses_for_chat,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()

# Style state per chat: 'random' or exact style name
CHAT_STYLE: dict[int, str] = {}  # default to 'random' when not set
STYLE_LIST = list(STYLE_PRESETS.keys())
LAST_RANDOM_STYLE: dict[int, str] = {}

# Wishlist add state per user (awaiting next text to add)
AWAIT_WISH_TEXT: dict[int, bool] = {}

# Probability to use sender's wishlist item as suggestion (e.g., 30%)
WISHLIST_PROB = 0.3

PHOTO_DIR = "/data/photos"
os.makedirs(PHOTO_DIR, exist_ok=True)


def allowed_chat(chat_id: int) -> bool:
	if settings.allowed_chat_id is None:
		return True
	return chat_id == settings.allowed_chat_id


def style_keyboard(current: Optional[str] = None) -> InlineKeyboardMarkup:
	buttons = []
	# First row: Random
	is_random = (current is None) or (current == "random")
	random_text = "Случайный ✓" if is_random else "Случайный"
	buttons.append([InlineKeyboardButton(text=random_text, callback_data="style:random")])
	# Other styles in rows of 3
	row = []
	for i, name in enumerate(STYLE_LIST, start=1):
		label = f"{name} ✓" if name == current else name
		row.append(InlineKeyboardButton(text=label, callback_data=f"style:{name}"))
		if i % 3 == 0:
			buttons.append(row)
			row = []
	if row:
		buttons.append(row)
	return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("style"))
async def cmd_style(message: Message) -> None:
	if not message.chat:
		return
	current = CHAT_STYLE.get(message.chat.id, "random")
	await message.reply("Выбери стиль кнопкой ниже:", reply_markup=style_keyboard(current=current))


@dp.callback_query(F.data.startswith("style:"))
async def cb_style(call: CallbackQuery) -> None:
	if not call.message or not call.message.chat:
		return
	style = call.data.split(":", 1)[1]
	if style != "random" and style not in STYLE_PRESETS:
		await call.answer("Неизвестный стиль", show_alert=False)
		return
	CHAT_STYLE[call.message.chat.id] = style
	await call.answer(f"Стиль: {('случайный' if style=='random' else style)}", show_alert=False)
	await call.message.edit_text("Стиль обновлён.", reply_markup=style_keyboard(current=style))


def wishlist_keyboard(tg_user_id: int) -> InlineKeyboardMarkup:
	rows = []
	# Add button
	rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="wl:add")])
	# Current items with remove buttons (each row item + remove)
	items = list_wishlist(tg_user_id)
	for wid, text in items[:10]:
		rows.append([InlineKeyboardButton(text=f"✖ {text}", callback_data=f"wl:rm:{wid}")])
	return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("wishlist"))
async def cmd_wishlist(message: Message) -> None:
	if not message.from_user:
		return
	await message.reply("Твой вишлист:", reply_markup=wishlist_keyboard(message.from_user.id))


@dp.callback_query(F.data == "wl:add")
async def cb_wl_add(call: CallbackQuery) -> None:
	if not call.from_user:
		return
	AWAIT_WISH_TEXT[call.from_user.id] = True
	await call.answer("Введи одним сообщением, что добавить", show_alert=False)
	await call.message.edit_text("Введи одним сообщением название предмета для вишлиста")


@dp.callback_query(F.data.startswith("wl:rm:"))
async def cb_wl_rm(call: CallbackQuery) -> None:
	if not call.from_user:
		return
	try:
		wish_id = int(call.data.split(":", 2)[2])
	except Exception:
		await call.answer("Ошибка id", show_alert=False)
		return
	ok = remove_wishlist_by_id(call.from_user.id, wish_id)
	await call.answer("Удалено" if ok else "Не найдено")
	# Refresh keyboard
	try:
		await call.message.edit_text("Твой вишлист:", reply_markup=wishlist_keyboard(call.from_user.id))
	except Exception:
		pass


@dp.message(Command("addphoto"))
async def cmd_addphoto(message: Message) -> None:
	if not message.from_user:
		return
	photo: Optional[PhotoSize] = None
	# If message has photo
	if message.photo:
		photo = max(message.photo, key=lambda p: p.file_size or 0)
	# Or if replying to a photo
	elif message.reply_to_message and message.reply_to_message.photo:
		photo = max(message.reply_to_message.photo, key=lambda p: p.file_size or 0)
	if not photo:
		await message.reply("Пришли команду /addphoto с фото или ответом на фото.")
		return
	file = await bot.get_file(photo.file_id)
	file_path = file.file_path
	# Save file locally under /data/photos/{user_id}_{random}.jpg
	filename = f"{message.from_user.id}_{random.randint(1000,9999)}.jpg"
	local_path = os.path.join(PHOTO_DIR, filename)
	await bot.download_file(file_path, destination=local_path)
	add_user_photo(message.from_user.id, local_path)
	await message.reply("Фото добавлено. Будем использовать для картинок.")


@dp.message(Command("categories"))
async def cmd_categories(message: Message) -> None:
	pairs = list_categories_with_aliases()
	if not pairs:
		await message.reply("Категорий в БД нет. Используй /addcat чтобы добавить.")
		return
	lines = []
	for name, aliases in pairs:
		alias_str = ", ".join(aliases) if aliases else "—"
		lines.append(f"{name}: {alias_str}")
	await message.reply("Категории и алиасы:\n" + "\n".join(lines))


@dp.message(Command("addcat"))
async def cmd_addcat(message: Message) -> None:
	user_id = message.from_user.id if message.from_user else 0
	if user_id not in settings.admins:
		await message.reply("Только админы могут управлять категориями.")
		return
	args = (message.text or "").split(maxsplit=2)
	if len(args) == 1:
		await message.reply("Форматы:\n/addcat set <имя> | алиас1 | алиас2 — перезаписать алиасы\n/addcat add <имя> | алиас1 | алиас2 — добавить алиасы")
		return
	action = args[1].lower()
	if action not in {"set", "add"}:
		await message.reply("Укажи действие: set или add")
		return
	if len(args) < 3:
		await message.reply("Формат: /addcat set|add <имя> | алиас1 | алиас2")
		return
	payload = args[2]
	parts = [p.strip() for p in payload.split("|")]
	name = parts[0]
	aliases = parts[1:] if len(parts) > 1 else []
	if action == "set":
		add_or_update_category(name, aliases)
		await message.reply(f"Категория '{name}' перезаписана. Алиасы: {', '.join(aliases) if aliases else '—'}")
		return
	# add mode (append)
	added, conflicts = append_aliases(name, aliases)
	resp = []
	if added:
		resp.append("Добавлено: " + ", ".join(added))
	if conflicts:
		resp.append("Конфликт (уже занято в других категориях): " + ", ".join(conflicts))
	if not resp:
		resp = ["Нет изменений"]
	await message.reply(f"Категория '{name}':\n" + "\n".join(resp))


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
		"Команды: /stats, /week, /month, /all, /me, /categories, /addcat, /undo, /style, /wishlist, /addphoto, /myphotos, /resetdata.\n"
		"/style — выбор стиля кнопками (по умолчанию — Случайный).\n"
		"/wishlist — кнопки для добавления/удаления хотелок.\n"
		"/addphoto — отправь с фото или ответом на фото — сохраним для генерации.\n"
		"/myphotos — список твоих фото с кнопками удаления.\n"
		"/resetdata — очистка трат (только админы)."
	)
	await message.reply(text)


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
	# If awaiting wishlist text from this user
	if AWAIT_WISH_TEXT.get(message.from_user.id):
		add_wishlist_item(message.from_user.id, message.text.strip())
		AWAIT_WISH_TEXT.pop(message.from_user.id, None)
		await message.reply("Добавил в вишлист.")
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

	# Use wishlist occasionally (for this sender)
	idea_from_wishlist = None
	if random.random() < WISHLIST_PROB:
		idea_from_wishlist = pick_random_wishlist_item(message.from_user.id)

	quip, idea = generate_motivation(all_time, parsed.amount, parsed.category, chat_id=message.chat.id)
	if idea_from_wishlist:
		idea = idea_from_wishlist

	reply_text = (
		f"Добавлено: {parsed.amount:.0f} {parsed.currency} в '{parsed.category}'.\n"
		f"Итого за период: {all_time:.0f} {settings.default_currency}.\n\n{quip}"
	)
	await message.reply(reply_text, reply_to_message_id=message.message_id)

	# Image generation with user photos if available
	style_state = CHAT_STYLE.get(message.chat.id, "random")
	if style_state == "random":
		prev = LAST_RANDOM_STYLE.get(message.chat.id)
		candidates = [s for s in STYLE_LIST if s != prev] or STYLE_LIST
		style = random.choice(candidates)
		LAST_RANDOM_STYLE[message.chat.id] = style
	else:
		style = style_state

	photo1 = pick_random_user_photo(message.from_user.id)
	photo2 = pick_random_other_user_photo(message.from_user.id)
	photo_paths = [p for p in [photo1, photo2] if p]
	user_desc = "есть пользовательские фото" if photo_paths else "фото профиля недоступны"

	img = generate_image_gemini(user_desc, idea, all_time, style, photo_paths=photo_paths)
	if img:
		file = BufferedInputFile(img.getvalue(), filename="idea.png")
		await message.reply_photo(photo=file, caption=f"Стиль: {style}")
		return

	banner = generate_banner_for_item(item=idea, style=style, total=all_time)
	file = BufferedInputFile(banner.getvalue(), filename="banner.png")
	await message.reply_photo(photo=file, caption="Изображения временно недоступны.")


def myphotos_keyboard(tg_user_id: int) -> InlineKeyboardMarkup:
	rows = []
	photos = list_user_photos_with_ids(tg_user_id)
	for pid, path in photos[:10]:
		rows.append([InlineKeyboardButton(text=f"✖ {os.path.basename(path)}", callback_data=f"ph:rm:{pid}")])
	if not rows:
		rows = [[InlineKeyboardButton(text="Нет фото", callback_data="ph:none")]]
	return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("myphotos"))
async def cmd_myphotos(message: Message) -> None:
	if not message.from_user:
		return
	try:
		await message.reply("Твои фото (удаление по кнопке):", reply_markup=myphotos_keyboard(message.from_user.id))
	except Exception:
		# Fallback plain text
		photos = list_user_photos_with_ids(message.from_user.id)
		if not photos:
			await message.reply("У тебя пока нет фото. Добавь через /addphoto.")
			return
		lines = [f"{pid}: {os.path.basename(path)}" for pid, path in photos[:10]]
		await message.reply("Твои фото:\n" + "\n".join(lines))


@dp.message(Command("photos"))
async def cmd_photos_alias(message: Message) -> None:
	# Alias to myphotos
	await cmd_myphotos(message)


@dp.callback_query(F.data == "ph:none")
async def cb_ph_none(call: CallbackQuery) -> None:
	await call.answer("Фото пока нет", show_alert=False)


@dp.callback_query(F.data.startswith("ph:rm:"))
async def cb_photo_remove(call: CallbackQuery) -> None:
	if not call.from_user:
		return
	try:
		pid = int(call.data.split(":", 2)[2])
	except Exception:
		await call.answer("Ошибка id", show_alert=False)
		return
	path = remove_user_photo_by_id(call.from_user.id, pid)
	if path:
		try:
			os.remove(path)
		except Exception:
			pass
		await call.answer("Удалено", show_alert=False)
	else:
		await call.answer("Не найдено", show_alert=False)
	try:
		await call.message.edit_text("Твои фото (удаление по кнопке):", reply_markup=myphotos_keyboard(call.from_user.id))
	except Exception:
		pass


def reset_keyboard(chat_id: int) -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		inline_keyboard=[[InlineKeyboardButton(text="🧹 Подтвердить очистку", callback_data=f"reset:{chat_id}")]]
	)


@dp.message(Command("resetdata"))
async def cmd_resetdata(message: Message) -> None:
	if not message.from_user or not message.chat:
		return
	if message.from_user.id not in settings.admins:
		await message.reply("Только админы могут очищать данные.")
		return
	await message.reply("Очистить все траты и статистику в этом чате?", reply_markup=reset_keyboard(message.chat.id))


@dp.callback_query(F.data.startswith("reset:"))
async def cb_reset(call: CallbackQuery) -> None:
	if not call.from_user or not call.message or not call.message.chat:
		return
	if call.from_user.id not in settings.admins:
		await call.answer("Недостаточно прав", show_alert=False)
		return
	try:
		cid = int(call.data.split(":", 1)[1])
	except Exception:
		await call.answer("Ошибка", show_alert=False)
		return
	deleted = delete_expenses_for_chat(cid)
	await call.answer("Готово", show_alert=False)
	try:
		await call.message.edit_text(f"Удалено записей: {deleted}")
	except Exception:
		pass


async def main() -> None:
	init_db()
	await dp.start_polling(bot)


if __name__ == "__main__":
	asyncio.run(main())