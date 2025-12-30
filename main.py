import discord
import os
import asyncio
import requests
from datetime import datetime, timezone

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

REGION = "au"
MIN_EV = 0.03
MAX_HOURS_TO_START = 24
CHECK_INTERVAL = 900

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": "🏈 NFL",
    "australianfootball_afl": "🏉 AFL",
    "rugbyleague_nrl": "🏉 NRL",
    "soccer_epl": "⚽ EPL",
    "soccer_uefa_champs_league": "⚽ UCL"
}

SAFE_MARKETS = {
    "americanfootball_nfl": ["h2h", "spreads", "totals"],
    "australianfootball_afl": ["h2h", "spreads", "totals"],
    "rugbyleague_nrl": ["h2h", "spreads", "totals"],
    "soccer_epl": ["h2h", "totals"],
    "soccer_uefa_champs_league": ["h2h", "totals"]
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted = set()

def hours_to_start(t):
    start = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(price, fair_price):
    return (price / fair_price) - 1

def stake(ev):
    if ev >= 0.08:
        return 3
    if ev >= 0.06:
        return 2
    if ev >= 0.04:
        return 1
    return 0.5

async def check_sport(channel, key, label):
    markets = ",".join(SAFE_MARKETS[key])

    url = (
        f"https://api.the-odds-api.com/v4/sports/{key}/odds"
        f"?apiKey={ODDS_API_KEY}&regions={REGION}"
        f"&markets={markets}&oddsFormat=decimal"
    )

    r = requests.get(url)
    if r.status_code != 200:
        return

    for game in r.json():
        if hours_to_start(game["commence_time"]) > MAX_HOURS_TO_START:
            continue

        books = game.get("bookmakers", [])
        for market in SAFE_MARKETS[key]:
            outcomes = {}

            for b in books:
                if b["title"] not in TRUSTED_BOOKS:
                    continue
                m = next((m for m in b["markets"] if m["key"] == market), None)
                if not m:
                    continue
                for o in m["outcomes"]:
                    outcomes.setdefault(o["name"], []).append(o["price"])

            for name, prices in outcomes.items():
                if len(prices) < 2:
                    continue

                fair = sum(prices) / len(prices)
                best = max(prices)
                ev = calc_ev(best, fair)

                if ev < MIN_EV:
                    continue

                bet_id = f"{game['id']}-{market}-{name}"
                if bet_id in posted:
                    continue

                posted.add(bet_id)

                msg = (
                    f"🔥 **+EV BET**\n\n"
                    f"{label}\n"
                    f"{game['away_team']} vs {game['home_team']}\n"
                    f"Market: **{market}**\n"
                    f"Pick: **{name}**\n\n"
                    f"Best Odds: {best}\n"
                    f"EV: {round(ev*100,2)}%\n"
                    f"Stake: {stake(ev)} units"
                )
                await channel.send(msg)

async def loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    while True:
        for k, v in SPORTS.items():
            await check_sport(channel, k, v)
        await asyncio.sleep(CHECK_INTERVAL)

@client.event
async def on_ready():
    print("Bot online")
    client.loop.create_task(loop())

client.run(TOKEN)
