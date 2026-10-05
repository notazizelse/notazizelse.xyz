# Haven Tashkent Bot

Telegram bot for **Haven Tashkent**, a 2-day teen game-jam hackathon
(Nov 14–15, 2026). Handles registration (uz/ru/en), a referral system
with reward tiers, and admin tools for check-in day.

## Project structure

```
bot.py                    entry point: registers handlers, runs polling
db.py                     SQLite schema + data-access helpers
config.py                 loads BOT_TOKEN / ADMIN_IDS, reward tiers, get_tier()
locales.py                all user-facing text, per language (uz/ru/en)
handlers/
  registration.py         /start + ConversationHandler (language, name, age,
                           school, phone, team status) + referral capture
  referrals.py             /myreferrals, /leaderboard
  info.py                  /myid, /schedule, /faq, /venue
  admin.py                 /stats, /referrals, /broadcast, /export, /checkin
.env.example               template for secrets/config
requirements.txt
logs/bot.log               created automatically on first run
```

## How the referral system works

- Every registration gets a code like `HVN-0001`, which also serves as
  that person's referral code.
- Referral links look like `https://t.me/<bot_username>?start=HVN-0001`.
  Telegram passes the part after `?start=` to the bot as `context.args[0]`.
- Referral counts are **never stored** — every command that shows a
  count runs `SELECT COUNT(*) FROM registrations WHERE referred_by = ?`
  live, so the number can't drift out of sync.
- One phone number = one registration (enforced by a `UNIQUE` constraint).
  If someone tries to register a phone number that's already in the
  database, no new row is created — they're just shown their existing
  code. This is the main defense against fake-account referral farming.
- Self-referrals (opening your own invite link) are silently ignored.
- Reward tiers are defined in `config.py` (`REWARD_TIERS`) and are easy
  to edit — `get_tier(count)` and `get_next_tier(count)` do the lookup
  everywhere else in the code.

## Setup

### 1. Get a bot token from @BotFather

1. Open Telegram and search for **@BotFather** (verified, blue check).
2. Send `/newbot`.
3. Pick a display name (e.g. `Haven Tashkent`) and a unique username
   ending in `bot` (e.g. `haven_tashkent_bot`).
4. BotFather replies with an API token that looks like
   `123456789:AAExampleTokenReplaceMe`. Copy it.
5. Optional but nice: send `/setdescription`, `/setabouttext`, and
   `/setuserpic` to BotFather to polish how the bot looks to attendees.

### 2. Find your own Telegram user ID (for `ADMIN_IDS`)

Easiest way: open Telegram, search for **@userinfobot** (or
**@RawDataBot**), and send it `/start`. It replies with your numeric
user ID. Do this for every organizer who should have admin access, and
put all of their IDs, comma-separated, in `ADMIN_IDS`.

### 3. Configure the project

```bash
git clone <this-repo-or-copy-the-folder>
cd haven-tashkent_bot
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```
```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy the environment template and fill it in:

```bash
cp .env.example .env
```

Edit `.env`:

```
BOT_TOKEN=123456789:AAExampleTokenReplaceMe
ADMIN_IDS=111111111,222222222
```

### 4. Run it

```bash
python bot.py
```

You should see log lines in the terminal and in `logs/bot.log`,
including `Starting Haven Tashkent bot (polling)...`. Open Telegram,
find your bot by its username, and send `/start`.

The SQLite database file (`haven.db` by default) is created
automatically on first run in the project directory — no separate DB
server needed.

## Commands

**Everyone**
- `/start` — register (or, if already registered, shows your existing code)
- `/myid` — your registration code and check-in status
- `/myreferrals` — your referral link, count, tier, and progress to the next one
- `/leaderboard` — public top 10 referrers (first name + count only)
- `/schedule`, `/faq`, `/venue` — event info
- `/cancel` — cancel an in-progress registration

**Admins only** (must be in `ADMIN_IDS`)
- `/stats` — totals, team-status breakdown, checked-in count, referral vs. direct
- `/referrals` — full leaderboard with names, Telegram IDs, counts, tiers
- `/broadcast <message>` — send a message to every registered user
- `/export` — download a CSV of all registrations (including referral counts)
- `/checkin <code>` — mark an attendee checked in and see their reward tier

## Editing copy

All bot text lives in `locales.py` in the `TEXTS` dict, one language
(`uz` / `ru` / `en`) at a time. A non-developer can edit the strings
there directly — placeholders like `{code}` or `{link}` get filled in
by the code, so keep them intact when editing.

## Notes on scope

- No payment processing.
- No automatic scheduled reminders in this version — `/broadcast` is
  the current way to message everyone. The code is structured (plain
  functions, no global state tied to polling) so `APScheduler` could be
  added later to send reminders automatically without a rewrite.
