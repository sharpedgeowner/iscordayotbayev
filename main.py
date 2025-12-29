import discord
import os
import asyncio
import requests
from datetime import datetime, timezone, timedelta

# ===== ENV VARS =====
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# ===== CONFIG =====
REGION = "au"
ODDS_FORMAT = "decimal"
MIN_EV = 0.03           # +3% minimum
MAJOR_EV = 0.08         # overrides kickoff window
MAX_HOURS_TO_START = 24
CHECK_INTERVAL = 900    # 15 minutes

SPORTS = {
    "americanfootball_nfl": "🏈 NFL",
    "australianfootball_afl": "🏉 AFL",
    "rugbyleague_nrl": "🏉 NRL",
    "soccer_epl": "⚽ Soccer",
    "soccer_uefa_champs_league": "⚽ Soccer"
}

# ===== DISCORD =====
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ===== MEMORY (ANTI-SPAM) =====
posted_bets = set()

# ===== HELPERS =====
def calc_ev(decimal_odds, true_prob):
    return (true_prob * decimal_odds) - 1

def staking_units(ev):
    # Fewer bets, higher conviction
    if ev >= 0.12:
        return 3.0
    elif ev >= 0.08:
        return 2.0
    elif ev >= 0.05:
        return 1.0
    elif ev >= 0.03:
        return 0.5
    return 0

def hours_until_start(commence_time):
    start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (start - now).total_seconds() / 3600

# ===== CORE LOGIC =====
async def check_sport(channel, sport_key, sport_name):
    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGION}"
        f"&markets=h2h"
        f"&oddsFormat={ODDS_FORMAT}"
    )

    res = requests.get(url)
    if res.status_code != 200:
        return

    games = res.json()

    for game in games:
        game_id = game["id"]
        home = game["home_team"]
        away = game["away_team"]
        hrs_to_start = hours_until_start(game["commence_time"])

        books = game.get("bookmakers", [])
        if len(books) < 2:
            continue

        for outcome_idx in [0, 1]:
            team = books[0]["markets"][0]["outcomes"][outcome_idx]["name"]

            # ===== FIND TRUE ODDS (BEST AVG PROXY) =====
            ref_prices = []
            for b in books:
                try:
                    ref_prices.append(
                        b["markets"][0]["outcomes"][outcome_idx]["price"]
                    )
                except:
                    pass

            if len(ref_prices) < 2:
                continue

            true_prob = sum(1 / p for p in ref_prices) / len(ref_prices)

            # ===== FIND BEST BOOK =====
            best_price = 0
            best_book = None
            supplementary = []

            for b in books:
                try:
                    price = b["markets"][0]["outcomes"][outcome_idx]["price"]
                    if price > best_price:
                        if best_book:
                            supplementary.append((best_book["title"], best_price))
                        best_price = price
                        best_book = b
                    else:
                        supplementary.append((b["title"], price))
                except:
                    continue

            ev = calc_ev(best_price, true_prob)
            units = staking_units(ev)

            # ===== FILTERS =====
            if ev < MIN_EV:
                continue

            if hrs_to_start > MAX_HOURS_TO_START and ev < MAJOR_EV:
                continue

            bet_key = f"{game_id}-{team}"
            if bet_key in posted_bets:
                continue

            if units <= 0:
                continue

            posted_bets.add(bet_key)

            # ===== FORMAT MESSAGE =====
            sup_text = ""
            for book, price in sorted(supplementary, key=lambda x: -x[1])[:4]:
                sup_text += f"• {book}: {price}\n"

            msg = (
                f"🔥 **+EV BET** 🔥\n\n"
                f"{sport_name}\n"
                f"🆚 {away} vs {home}\n"
                f"📌 **{team} ML**\n\n"
                f"🏆 **Best Odds:** {best_price} ({best_book['title']})\n"
                f"📊 **EV:** {round(ev*100,2)}%\n"
                f"📈 **Stake:** {units} units\n"
                f"⏱ Starts in: {round(hrs_to_start,1)}h\n\n"
                f"📚 **Other Books:**\n{sup_text}"
            )

            await channel.send(msg)

async def ev_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        for sport_key, sport_name in SPORTS.items():
            await check_sport(channel, sport_key, sport_name)
        await asyncio.sleep(CHECK_INTERVAL)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(ev_loop())

client.run(TOKEN)
