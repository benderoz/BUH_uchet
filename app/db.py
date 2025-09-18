from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterable, Optional, List, Tuple

from sqlalchemy import String, create_engine, func, select, text, and_, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
	pass


class User(Base):
	__tablename__ = "users"

	id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
	tg_user_id: Mapped[int] = mapped_column(index=True, unique=True)
	username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
	first_seen_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Expense(Base):
	__tablename__ = "expenses"

	id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
	tg_user_id: Mapped[int] = mapped_column(index=True)
	chat_id: Mapped[int] = mapped_column(index=True)
	amount: Mapped[float]
	currency: Mapped[str] = mapped_column(String(8), default="RUB")
	category: Mapped[str] = mapped_column(String(64), default="прочее", index=True)
	note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
	created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)


class Category(Base):
	__tablename__ = "categories"

	id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
	name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
	aliases: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # pipe-separated aliases


class BotState(Base):
	__tablename__ = "bot_state"

	id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
	chat_id: Mapped[int] = mapped_column(index=True)
	key: Mapped[str] = mapped_column(String(64), index=True)
	value: Mapped[str] = mapped_column(String(1024))
	updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class Wishlist(Base):
	__tablename__ = "wishlist"

	id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
	tg_user_id: Mapped[int] = mapped_column(index=True)
	item: Mapped[str] = mapped_column(String(200), index=True)
	created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)


def init_db() -> None:
	Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
	session = SessionLocal()
	try:
		yield session
		session.commit()
	except Exception:
		session.rollback()
		raise
	finally:
		session.close()


def get_state(chat_id: int, key: str) -> Optional[str]:
	with session_scope() as s:
		row = s.execute(
			select(BotState).where(BotState.chat_id == chat_id, BotState.key == key)
		).scalar_one_or_none()
		return row.value if row else None


def set_state(chat_id: int, key: str, value: str) -> None:
	with session_scope() as s:
		row = s.execute(
			select(BotState).where(BotState.chat_id == chat_id, BotState.key == key)
		).scalar_one_or_none()
		if row:
			row.value = value
			row.updated_at = datetime.utcnow()
			return
		s.add(BotState(chat_id=chat_id, key=key, value=value))


# Wishlist CRUD

def add_wishlist_item(tg_user_id: int, item: str) -> None:
	item = item.strip()
	if not item:
		return
	with session_scope() as s:
		s.add(Wishlist(tg_user_id=tg_user_id, item=item))


def list_wishlist_items(tg_user_id: int) -> List[str]:
	with session_scope() as s:
		rows = s.execute(select(Wishlist.item).where(Wishlist.tg_user_id == tg_user_id).order_by(Wishlist.created_at.desc())).all()
		return [r[0] for r in rows]


def remove_wishlist_item(tg_user_id: int, item: str) -> bool:
	item = item.strip()
	with session_scope() as s:
		res = s.execute(delete(Wishlist).where(and_(Wishlist.tg_user_id == tg_user_id, Wishlist.item == item)))
		return res.rowcount > 0


def pick_random_wishlist_item(tg_user_id: int) -> Optional[str]:
	items = list_wishlist_items(tg_user_id)
	if not items:
		return None
	import random as _r
	return _r.choice(items)


# Categories helpers

def list_categories_with_aliases() -> List[Tuple[str, List[str]]]:
	with session_scope() as s:
		rows = s.execute(select(Category)).scalars().all()
		result: List[Tuple[str, List[str]]] = []
		for c in rows:
			aliases = [a.strip() for a in (c.aliases or "").split("|") if a.strip()]
			result.append((c.name, aliases))
		return result