import discord
import os
import asyncio
import requests
import sqlite3
from datetime import datetime, timezone

# ================= ENV =================
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# ================= CONFIG =================
REGION = "au"
ODDS_FORMAT = "decimal"
CHECK_INTERVAL = 1800  # 30 mins
MIN_EV = 0.02          # relaxed so it actually posts
MAX_HOURS_TO_START = 168  # 7 days

SPORTS = {
    "americanfootball_nfl": "🏈 NFL",
    "basketball_nba": "🏀 NBA",
    "soccer_epl": "⚽ EPL"
}

# ================= DATABASE =================
conn = sqlite3.connect("bets.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS bets (
    id TEXT PRIMARY KEY,
    sport TEXT,
    pick TEXT,
    odds REAL,
    ev REAL,
    placed_at TEXT
)
""")
conn.commit()

# ================= DISCORD =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

status_message = None  # single updating status message

# ================= HELPERS =================
def hours_until_start(commence):
    start = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(price, true_prob):
    return (price * true_prob) - 1

# ================= CORE =================
async def check_sport(channel, sport_key, sport_name):
    found_bet = False

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGION}"
        f"&markets=h2h"
        f"&oddsFormat={ODDS_FORMAT}"
    )

    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return False
        games = r.json()
    except:
        return False

    for game in games:
        if hours_until_start(game["commence_time"]) > MAX_HOURS_TO_START:
            continue

        books = [b for b in game.get("bookmakers", []) if b.get("markets")]
        if len(books) < 2:
            continue

        outcomes = books[0]["markets"][0]["outcomes"]

        for outcome in outcomes:
            name = outcome["name"]
            prices = []

            for b in books:
                try:
                    price = next(
                        o["price"] for o in b["markets"][0]["outcomes"]
                        if o["name"] == name
                    )
                    prices.append(price)
                except:
                    continue

            if len(prices) < 2:
                continue

            true_prob = sum(1 / p for p in prices) / len(prices)
            best_price = max(prices)
            ev = calc_ev(best_price, true_prob)

            if ev < MIN_EV:
                continue

            bet_id = f"{game['id']}-{name}"
            c.execute("SELECT 1 FROM bets WHERE id=?", (bet_id,))
            if c.fetchone():
                continue

            msg = (
                f"🔥 **+EV BET FOUND** 🔥\n\n"
                f"{sport_name}\n"
                f"🆚 {game['away_team']} @ {game['home_team']}\n"
                f"🎯 **Pick:** {name}\n"
                f"💰 **Odds:** {best_price}\n"
                f"📊 **EV:** {round(ev*100,2)}%\n"
            )

            await channel.send(msg)

            c.execute(
                "INSERT INTO bets VALUES (?, ?, ?, ?, ?, ?)",
                (
                    bet_id,
                    sport_key,
                    name,
                    best_price,
                    ev,
                    datetime.now(timezone.utc).isoformat()
                )
            )
            conn.commit()

            found_bet = True

    return found_bet

# ================= EVENTS =================
@client.event
async def on_ready():
    print("Bot online")

    channel = client.get_channel(CHANNEL_ID)
    global status_message

    status_message = await channel.send("🔍 Searching for +EV bets...")

    while True:
        found_any = False

        for sport_key, sport_name in SPORTS.items():
            found = await check_sport(channel, sport_key, sport_name)
            if found:
                found_any = True

        now = datetime.now(timezone.utc).strftime("%H:%M UTC")

        if status_message:
            if found_any:
                await status_message.edit(
                    content=f"✅ Bets found this cycle\nLast check: {now}"
                )
            else:
                await status_message.edit(
                    content=f"🔍 Searching for +EV bets...\nLast check: {now}"
                )

        await asyncio.sleep(CHECK_INTERVAL)

client.run(TOKEN)
