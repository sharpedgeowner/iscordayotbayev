import discord
import os
import asyncio
import requests
from datetime import datetime, timezone

# ================= ENV =================
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# ================= CONFIG =================
REGION = "au"
ODDS_FORMAT = "decimal"
CHECK_INTERVAL = 1800  # 30 mins (safe for rate limits)
MIN_EV = 0.02          # 2% minimum edge
MAX_HOURS = 48         # Only games within 48 hours

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": "🏈 NFL",
    "basketball_nba": "🏀 NBA",
    "rugbyleague_nrl": "🏉 NRL",
    "soccer_epl": "⚽ EPL"
}

# ================= DISCORD =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted = set()

# ================= HELPERS =================
def hours_until_start(commence):
    start = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(best_price, sharp_avg):
    true_prob = 1 / sharp_avg
    return (best_price * true_prob) - 1

def staking(ev):
    if ev >= 0.08: return 3
    if ev >= 0.05: return 2
    if ev >= 0.03: return 1
    return 0.5

def discord_time(iso):
    ts = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    return f"<t:{ts}:F>"

# ================= CORE =================
async def check_sport(channel, sport_key, sport_name):

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
            print("API error:", r.status_code)
            return

        games = r.json()
        print(sport_name, "games:", len(games))

    except Exception as e:
        print("Request error:", e)
        return

    for game in games:

        if hours_until_start(game["commence_time"]) > MAX_HOURS:
            continue

        books = game.get("bookmakers", [])
        if len(books) < 2:
            continue

        outcomes = books[0]["markets"][0]["outcomes"]

        for outcome in outcomes:
            team = outcome["name"]
            prices = []

            # Collect trusted book prices
            for b in books:
                if b["title"] in TRUSTED_BOOKS:
                    try:
                        price = next(
                            o["price"] for o in b["markets"][0]["outcomes"]
                            if o["name"] == team
                        )
                        prices.append((price, b["title"]))
                    except:
                        continue

            if len(prices) < 2:
                continue

            # Sharp average
            avg_price = sum(p[0] for p in prices) / len(prices)

            # Best available
            best_price, best_book = max(prices, key=lambda x: x[0])

            ev = calc_ev(best_price, avg_price)

            if ev < MIN_EV:
                continue

            bet_id = f"{game['id']}-{team}"
            if bet_id in posted:
                continue

            posted.add(bet_id)

            units = staking(ev)

            msg = (
                f"🔥 **+EV BET** 🔥\n\n"
                f"{sport_name}\n"
                f"**Game:** {game['away_team']} @ {game['home_team']}\n"
                f"**Start:** {discord_time(game['commence_time'])}\n\n"
                f"**Pick:** {team}\n"
                f"**Best Odds:** {best_price} ({best_book})\n"
                f"**Edge:** {round(ev*100,2)}%\n"
                f"**Stake:** {units} units"
            )

            await channel.send(msg)
            print("Posted:", team)

# ================= LOOP =================
async def ev_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        print("Searching for EV bets...")
        for sport_key, sport_name in SPORTS.items():
            await check_sport(channel, sport_key, sport_name)

        await asyncio.sleep(CHECK_INTERVAL)

# ================= EVENTS =================
@client.event
async def on_ready():
    print("Bot online as", client.user)
    client.loop.create_task(ev_loop())

client.run(TOKEN)
