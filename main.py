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
MIN_EV = 0.03           # +3% minimum EV to alert
MAJOR_EV = 0.08         # overrides kickoff window
MAX_HOURS_TO_START = 24
CHECK_INTERVAL = 900    # 15 minutes

# Trusted sharp AU bookmakers for EV calculations
TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

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

# ===== MEMORY =====
posted_bets = set()        # Prevent duplicate alerts
last_odds = {}             # Track line movement: {game-team-book: last_price}

# ===== HELPERS =====
def calc_ev(book_odds, true_prob):
    return (book_odds * true_prob) - 1

def staking_units(ev):
    if ev >= 0.08:
        return 3.0
    elif ev >= 0.06:
        return 2.0
    elif ev >= 0.04:
        return 1.0
    return 0.5

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

    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            print(f"Odds API error {sport_name}: {res.status_code}")
            return
        games = res.json()
    except Exception as e:
        print(f"Error fetching {sport_name}: {e}")
        return

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

            # ----- REFERENCE ODDS (TRUSTED BOOKS ONLY) -----
            ref_prices = [
                b["markets"][0]["outcomes"][outcome_idx]["price"]
                for b in books if b["title"] in TRUSTED_BOOKS
            ]

            if len(ref_prices) < 2:
                continue  # need multiple sharp books to calculate EV

            # Weighted true probability
            true_prob = sum(1 / p for p in ref_prices) / len(ref_prices)

            # Filter out extreme outliers (>15% higher than min ref)
            if max(ref_prices) / min(ref_prices) > 1.15:
                continue

            # ----- BEST BOOK & LINE MOVEMENT -----
            best_price = 0
            best_book = None
            supplementary = []
            line_movement_note = ""

            for b in books:
                try:
                    price = b["markets"][0]["outcomes"][outcome_idx]["price"]
                    key = f"{game_id}-{team}-{b['title']}"

                    # Detect line movement
                    prev_price = last_odds.get(key)
                    if prev_price and prev_price != price:
                        line_movement_note += f"📈 {b['title']} moved: {prev_price} → {price}\n"
                    last_odds[key] = price

                    # Determine best odds
                    if price > best_price:
                        if best_book:
                            supplementary.append((best_book["title"], best_price))
                        best_price = price
                        best_book = b
                    else:
                        supplementary.append((b["title"], price))
                except:
                    continue

            # ----- EV & FILTERS -----
            ev = calc_ev(best_price, true_prob)
            if ev < MIN_EV:
                continue
            if hrs_to_start > MAX_HOURS_TO_START and ev < MAJOR_EV:
                continue

            bet_key = f"{game_id}-{team}"
            if bet_key in posted_bets:
                continue

            units = staking_units(ev)
            if units <= 0:
                continue

            posted_bets.add(bet_key)

            # ----- FORMAT MESSAGE -----
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
                f"{line_movement_note}"
                f"📚 **Other Books:**\n{sup_text}"
            )

            await channel.send(msg)

# ===== LOOP =====
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
