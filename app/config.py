from __future__ import annotations

import os
from typing import Optional, Set

from pydantic import BaseModel, Field, ValidationError, field_validator
from dotenv import load_dotenv


class Settings(BaseModel):
	telegram_bot_token: str = Field(validation_alias="TELEGRAM_BOT_TOKEN")
	gemini_api_key: str = Field(validation_alias="GEMINI_API_KEY")
	database_url: str = Field(default="sqlite:////data/finance.db", validation_alias="DATABASE_URL")
	admins: Set[int] = Field(default_factory=set, validation_alias="ADMINS")
	allowed_chat_id: Optional[int] = Field(default=None, validation_alias="ALLOWED_CHAT_ID")
	default_currency: str = Field(default="₽", validation_alias="DEFAULT_CURRENCY")
	week_start: str = Field(default="monday", validation_alias="WEEK_START")

	@field_validator("admins", mode="before")
	@classmethod
	def _parse_admins(cls, v):
		# Accept: None, int, list[int], set[int], or string like "1,2,3" or "123"
		if v is None or v == "":
			return set()
		if isinstance(v, (set, list)):
			return {int(x) for x in v}
		if isinstance(v, int):
			return {v}
		if isinstance(v, str):
			parts = [p.strip() for p in v.split(",") if p.strip()]
			return {int(p) for p in parts} if parts else set()
		return v

	@classmethod
	def load(cls) -> "Settings":
		# Load from .env if present
		load_dotenv(override=False)
		# Preprocess optional ids
		env = dict(os.environ)
		allowed_raw = env.get("ALLOWED_CHAT_ID", "").strip()
		if allowed_raw == "":
			env.pop("ALLOWED_CHAT_ID", None)
		return cls.model_validate(env)


def get_settings() -> Settings:
	try:
		return Settings.load()
	except ValidationError as e:
		raised = RuntimeError(f"Configuration error: {e}")
		raised.__cause__ = None
		raise raised