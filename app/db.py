from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import String, create_engine, func, select, text
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