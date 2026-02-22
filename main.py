import discord
import os
import asyncio
import requests
from datetime import datetime, timezone

# ================= CONFIG =================
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = "au"
ODDS_FORMAT = "decimal"
EV_CAP = 0.10
CHECK_INTERVAL = 1800  # 30 mins

SPORTS = [
    "americanfootball_nfl",
    "aussierules_afl",
    "rugby_league_nrl",
    "basketball_nba",
    "soccer_epl"
]

MARKETS = [
    "h2h",
    "spreads",
    "totals",
    "player_points",
    "player_pass_tds",
    "player_anytime_td",
    "player_goals"
]

# ==========================================

intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted_bets = set()

# ================= TIME FUNCTIONS =================

def discord_timestamp(iso_time):
    dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    unix = int(dt.timestamp())
    return f"<t:{unix}:F>"

def discord_relative(iso_time):
    dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    unix = int(dt.timestamp())
    return f"<t:{unix}:R>"

# ================= STAKING =================

def calculate_units(ev):
    if ev >= 0.09:
        return 3
    elif ev >= 0.07:
        return 2
    elif ev >= 0.05:
        return 1
    else:
        return 0.5

# ================= EV CHECK =================

def calculate_ev(best_price, sharp_price):
    if sharp_price == 0:
        return 0
    fair_prob = 1 / sharp_price
    ev = (best_price * fair_prob) - 1
    return ev

# ================= MAIN LOGIC =================

async def check_sport(channel, sport):
    try:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": REGION,
            "markets": ",".join(MARKETS),
            "oddsFormat": ODDS_FORMAT
        }

        r = requests.get(url, params=params)

        if r.status_code != 200:
            print("API Error:", r.status_code, r.text)
            return

        games = r.json()

        for game in games:

            start_time = game["commence_time"]

            # Only within 24 hours
            game_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            hours_to_start = (game_time - datetime.now(timezone.utc)).total_seconds() / 3600

            if hours_to_start > 24:
                continue

            bookmakers = game.get("bookmakers", [])
            if not bookmakers:
                continue

            for market in MARKETS:
                prices = []
                for book in bookmakers:
                    for m in book.get("markets", []):
                        if m["key"] == market:
                            for outcome in m["outcomes"]:
                                prices.append({
                                    "book": book["title"],
                                    "name": outcome["name"],
                                    "price": outcome["price"]
                                })

                if len(prices) < 2:
                    continue

                best = max(prices, key=lambda x: x["price"])

                # Use average as synthetic sharp price
                avg_price = sum(p["price"] for p in prices) / len(prices)

                ev = calculate_ev(best["price"], avg_price)

                if ev <= 0 or ev > EV_CAP:
                    continue

                bet_id = f"{game['id']}_{market}_{best['name']}"
                if bet_id in posted_bets:
                    continue

                units = calculate_units(ev)

                supplementary = [
                    f"{p['book']} {p['price']}"
                    for p in prices
                    if p["name"] == best["name"] and p["book"] != best["book"]
                ]

                message = f"""
🔥 **Positive EV Bet Found**

🏈 {game['home_team']} vs {game['away_team']}
📊 Market: {market}
🎯 Selection: {best['name']}
💰 Best Price: {best['price']} @ {best['book']}
📈 EV: {round(ev*100,2)}%
📦 Stake: {units} Units

🕒 Start: {discord_timestamp(start_time)} ({discord_relative(start_time)})

📚 Other Books:
{", ".join(supplementary) if supplementary else "None"}
"""

                await channel.send(message)
                posted_bets.add(bet_id)

    except Exception as e:
        print("Error:", e)

# ================= LOOP =================

async def ev_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while not client.is_closed():
        try:
            now = datetime.now(timezone.utc).strftime("%H:%M UTC")
            await channel.send(f"🔍 Searching for EV bets... ({now})")

            for sport in SPORTS:
                await check_sport(channel, sport)

        except Exception as e:
            print("Loop Error:", e)

        await asyncio.sleep(CHECK_INTERVAL)

# ================= START =================

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(ev_loop())

client.run(TOKEN)
