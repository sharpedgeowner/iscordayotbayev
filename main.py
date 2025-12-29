import discord
import os
import asyncio
import requests

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

MIN_EV = float(os.getenv("MIN_EV", 0.02))          # +2% EV
KELLY_FRAC = float(os.getenv("KELLY_FRACTION", 0.1))

# AU ONLY
REGION = "au"
MARKET = "h2h"   # moneyline / match winner
ODDS_FORMAT = "decimal"

# SPORTS TO CHECK
SPORTS = {
    "🏈 NFL": "americanfootball_nfl",
    "🏉 AFL": "aussierules_afl",
    "🏉 NRL": "rugbyleague_nrl",
    "⚽ Soccer": "soccer_epl,soccer_uefa_champs_league,soccer_fifa_world_cup"
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# Track last odds for line movement + duplicate prevention
last_seen = {}

def calc_ev(decimal_odds, true_prob):
    return (true_prob * decimal_odds) - 1

def kelly_units(ev, decimal_odds):
    b = decimal_odds - 1
    if b <= 0:
        return 0
    kelly = ev / b
    return round(max(0, kelly * KELLY_FRAC), 2)

async def fetch_sport(channel, emoji, sport_key):
    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGION}"
        f"&markets={MARKET}"
        f"&oddsFormat={ODDS_FORMAT}"
    )

    r = requests.get(url)
    if r.status_code != 200:
        return

    games = r.json()

    for game in games:
        home = game["home_team"]
        away = game["away_team"]
        books = game.get("bookmakers", [])

        if len(books) < 2:
            continue

        # Use best-priced book as fair reference
        ref_book = max(books, key=lambda b: max(o["price"] for o in b["markets"][0]["outcomes"]))

        for book in books:
            book_name = book["title"]

            for outcome in book["markets"][0]["outcomes"]:
                team = outcome["name"]
                price = outcome["price"]

                ref_outcome = next(
                    (o for o in ref_book["markets"][0]["outcomes"] if o["name"] == team),
                    None
                )
                if not ref_outcome:
                    continue

                ref_price = ref_outcome["price"]
                true_prob = 1 / ref_price
                ev = calc_ev(price, true_prob)

                key = (sport_key, home, away, book_name, team)
                prev_price = last_seen.get(key)

                line_move = ""
                if prev_price and prev_price != price:
                    line_move = f"\n📈 Line move: {prev_price} → {price}"

                last_seen[key] = price

                if ev >= MIN_EV:
                    units = kelly_units(ev, price)
                    if units <= 0:
                        continue

                    await channel.send(
                        f"🔥 **+EV BET (AU ONLY)** 🔥\n\n"
                        f"{emoji} {away} vs {home}\n"
                        f"📍 Book: {book_name}\n"
                        f"📌 {team} @ {price}\n"
                        f"📊 EV: {round(ev * 100, 2)}%\n"
                        f"📈 Stake: {units} Units"
                        f"{line_move}"
                    )

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(main_loop())

async def main_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        for emoji, sport in SPORTS.items():
            # soccer may contain multiple leagues
            if "," in sport:
                for s in sport.split(","):
                    await fetch_sport(channel, emoji, s)
            else:
                await fetch_sport(channel, emoji, sport)

        await asyncio.sleep(900)  # 15 minutes (API safe)

client.run(TOKEN)
