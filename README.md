# Telegram Movie Search + Filter Bot

## Features
- Search a custom movie database by title, language, genre, and description.
- Browse by genre and language.
- Show latest added titles.
- Admin-only `/addmovie` and `/deletemovie` commands.
- Sends poster images when a poster URL is supplied.
- Stores metadata in PostgreSQL (not local SQLite).

Only add movie metadata, posters, and official/legal viewing pages that you have permission to use. This bot does not scrape or distribute copyrighted movie files.

## Files
- `bot.py`: bot application
- `requirements.txt`: Python dependencies

## 1) Create a Telegram bot
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot`.
3. Follow the prompts and copy the bot token. Keep it private.

## 2) Get your Telegram numeric user ID
Use a trusted Telegram ID bot such as `@userinfobot` and copy your numeric ID. This becomes `ADMIN_ID`.

## 3) Create PostgreSQL
In Render Dashboard:
1. Click **New + → PostgreSQL**.
2. Create a database. For testing, a free database may be available.
3. Copy its **Internal Database URL** if your web service is in the same Render region.
4. Put that value in the web service's `DATABASE_URL` environment variable.

Important: Render's free Postgres currently expires 30 days after creation. Upgrade it or use another durable PostgreSQL provider before storing data you need to keep.

## 4) Upload this project to GitHub
1. Create a new GitHub repository.
2. Upload `bot.py` and `requirements.txt` from this folder.
3. Make the repository private if you prefer.

## 5) Deploy on Render
1. Render Dashboard → **New + → Web Service**.
2. Connect your GitHub repository.
3. Set:
   - Runtime: `Python`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
   - Instance: Free for testing; a paid always-on instance for dependable 24/7 operation.
4. Add these Environment Variables:

| Key | Value |
|---|---|
| `BOT_TOKEN` | Token from @BotFather |
| `DATABASE_URL` | PostgreSQL Internal Database URL |
| `ADMIN_ID` | Your numeric Telegram user ID |
| `RENDER_EXTERNAL_URL` | Your Render URL, e.g. `https://your-service.onrender.com` |
| `WEBHOOK_PATH` | A long random path, e.g. `moviehook_8f31a9c2` |
| `WEBHOOK_SECRET` | A random 30+ character secret using letters, numbers, `_` or `-` |

5. Click **Create Web Service** and wait for the deploy to finish.

## 6) Add a movie
In your bot chat, as the admin, send one line in this exact format:

`/addmovie Title|Year|Language|Genre1,Genre2|Description|PosterURL|OfficialURL`

Example:

`/addmovie Sample Film|2024|English|Drama,Thriller|A sample movie description||https://example.com`

PosterURL and OfficialURL can be left blank, but keep the `|` separators. Use only poster images and official/legal viewing pages you are allowed to use.

Delete by database ID:
`/deletemovie 1`

## 7) Test
- Open your bot and send `/start`.
- Tap Search movie and enter a title.
- Browse genres and languages.
- Add one test record using `/addmovie`.

## Notes
- Free Render web services spin down after 15 minutes without inbound traffic and can take about a minute to wake. They are not suitable for guaranteed 24/7 bot availability.
- Free Render web services have ephemeral local filesystems, so this project uses PostgreSQL instead of SQLite.
- Render free Postgres databases expire after 30 days. Keep a backup or upgrade/use a durable PostgreSQL provider.
- Never share your bot token or database URL publicly. If a token is exposed, revoke it with @BotFather and generate a new one.
