## Finance Buddy Telegram Bot (Group Expenses with Gemini quips)

A Telegram bot for two friends to track "fun" expenses (alcohol, smoking, restaurants, etc.), see weekly/monthly/all-time stats, and receive dark-humor motivational lines powered by Gemini. Optionally generates a simple image with a suggested item you could have bought for the total.

### Features
- Add expenses by just sending messages with an amount and optional category/note
- Category aliases (ru/en), extensible via command
- Stats: week, month, all-time; per-user breakdown
- Gemini-generated short quips referencing what you could have bought
- Simple image generation via Pillow
- Dockerized, deploy anywhere (Render/Railway/VPS)

### Quick Start (Local)
1. Create `.env` from `.env.example` and fill secrets (use NEW tokens):
```
cp .env.example .env
```
2. Create and activate venv, install deps:
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
3. Run:
```
python -m app.main
```
4. Add the bot to your group chat and send messages like:
- `1500 алкоголь бар`
- `250 суши еда`
- `1000 курилки iqos`
- `500`

### Docker
Build and run:
```
docker build -t finance-buddy .
docker run -d --name finance-buddy --restart unless-stopped \
  -v $(pwd)/data:/data \
  --env-file .env \
  finance-buddy
```

### Deploy (Render)
- Create a new Web Service or Background Worker from this repo (better: Worker)
- Build command: none (Dockerfile builds)
- Start command: `python -m app.main`
- Add environment variables from `.env`
- Add a persistent disk mounted to `/data` for SQLite

### Commands
- `/start`, `/help` — brief instructions
- `/stats` — all-time + week + month summary
- `/week`, `/month`, `/all` — period totals
- `/me` — your own totals for current month
- `/categories` — show available categories and aliases
- `/addcat <name> | aliases...` — add/extend category (admins only)
- `/undo` — undo your last expense today

### Security
- Never commit `.env` or share your secrets. Rotate leaked tokens immediately.

### License
MIT