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
CHECK_INTERVAL = 1800
MIN_EV = 0.02
MAX_HOURS_TO_START = 72

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": {
        "name": "🏈 NFL",
        "markets": ["h2h", "spreads", "totals", "player_anytime_td"]
    },
    "basketball_nba": {
        "name": "🏀 NBA",
        "markets": ["h2h", "spreads", "totals", "player_points"]
    },
    "soccer_epl": {
        "name": "⚽ EPL",
        "markets": ["h2h", "totals", "btts", "player_goal_scorer"]
    },
    "rugbyleague_nrl": {
        "name": "🏉 NRL",
        "markets": ["h2h", "spreads", "totals"]
    },
    "australianfootball_afl": {
        "name": "🏉 AFL",
        "markets": ["h2h", "spreads", "totals"]
    }
}

# ================= DISCORD =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted_bets = set()
status_message = None

# ================= HELPERS =================

def hours_until_start(commence):
    start = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(price, true_prob):
    return (price * true_prob) - 1

def staking(ev):
    if ev >= 0.08: return 3
    if ev >= 0.05: return 2
    if ev >= 0.03: return 1
    return 0.5

def discord_time(iso):
    ts = int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    return f"<t:{ts}:F>"

# ================= CORE =================

async def check_sport(channel, sport_key, config):

    markets_param = ",".join(config["markets"])

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGION}"
        f"&markets={markets_param}"
        f"&oddsFormat={ODDS_FORMAT}"
    )

    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"{sport_key} API error:", r.status_code)
            return

        games = r.json()
        if not isinstance(games, list):
            return

    except Exception as e:
        print("Request failed:", e)
        return

    print(f"{config['name']} games:", len(games))

    for game in games:

        if hours_until_start(game["commence_time"]) > MAX_HOURS_TO_START:
            continue

        books = game.get("bookmakers", [])
        if len(books) < 2:
            continue

        # Collect reference prices
        reference = {}

        for b in books:
            if b["title"] not in TRUSTED_BOOKS:
                continue

            for market in b.get("markets", []):
                key = market["key"]

                for outcome in market.get("outcomes", []):
                    ref_key = (key, outcome["name"])
                    reference.setdefault(ref_key, []).append(outcome["price"])

        for (market_key, outcome_name), prices in reference.items():

            if len(prices) < 2:
                continue

            true_prob = sum(1/p for p in prices) / len(prices)

            best_price = 0
            best_book = None

            for b in books:
                for market in b.get("markets", []):
                    if market["key"] != market_key:
                        continue

                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == outcome_name:
                            if outcome["price"] > best_price:
                                best_price = outcome["price"]
                                best_book = b["title"]

            if best_price == 0:
                continue

            ev = calc_ev(best_price, true_prob)

            if ev < MIN_EV:
                continue

            bet_id = f"{game['id']}-{market_key}-{outcome_name}"
            if bet_id in posted_bets:
                continue

            units = staking(ev)

            msg = (
                f"🔥 **+EV BET** 🔥\n\n"
                f"{config['name']}\n"
                f"Market: {market_key}\n"
                f"Game: {game.get('away_team','')} @ {game.get('home_team','')}\n"
                f"Start: {discord_time(game['commence_time'])}\n"
                f"Pick: {outcome_name}\n"
                f"Best Odds: {best_price} ({best_book})\n"
                f"EV: {round(ev*100,2)}%\n"
                f"Stake: {units} units"
            )

            await channel.send(msg)
            posted_bets.add(bet_id)
            print("Posted:", bet_id)

# ================= LOOP =================

async def main_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    global status_message
    status_message = await channel.send("🔍 Searching for +EV bets...")

    while True:

        for sport_key, config in SPORTS.items():
            await check_sport(channel, sport_key, config)

        now = datetime.now(timezone.utc).strftime("%H:%M UTC")

        await status_message.edit(
            content=f"🔍 Searching for +EV bets...\nLast check: {now}"
        )

        await asyncio.sleep(CHECK_INTERVAL)

# ================= EVENTS =================

@client.event
async def on_ready():
    print("Bot online")
    client.loop.create_task(main_loop())

client.run(TOKEN)
