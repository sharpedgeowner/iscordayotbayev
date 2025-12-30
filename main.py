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
CHECK_INTERVAL = 900
MIN_EV = 0.03
MAX_EV = 0.10
MAX_HOURS_TO_START = 24

SHARP_BOOKS = ["Betfair Exchange", "Pinnacle"]

SPORTS = {
    "americanfootball_nfl": {
        "emoji": "🏈",
        "markets": [
            "h2h",
            "player_pass_tds",
            "player_rush_tds",
            "player_receptions",
            "touchdown_scorer"
        ]
    },
    "basketball_nba": {
        "emoji": "🏀",
        "markets": [
            "h2h",
            "player_points",
            "player_rebounds",
            "player_assists"
        ]
    },
    "soccer_epl": {
        "emoji": "⚽",
        "markets": [
            "h2h",
            "anytime_goal_scorer",
            "first_goal_scorer"
        ]
    }
}

# ================= DISCORD =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted = set()

# ================= HELPERS =================
def hours_to_start(ts):
    start = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(best_odds, probs):
    true_prob = sum(probs) / len(probs)
    return (best_odds * true_prob) - 1

# ================= CORE =================
async def check_sport(channel, sport_key, cfg):
    markets = ",".join(cfg["markets"])

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGION}"
        f"&markets={markets}"
        f"&oddsFormat={ODDS_FORMAT}"
    )

    res = requests.get(url, timeout=10)
    if res.status_code != 200:
        return

    for game in res.json():
        hrs = hours_to_start(game["commence_time"])
        if hrs > MAX_HOURS_TO_START:
            continue

        bookmakers = game.get("bookmakers", [])
        if len(bookmakers) < 2:
            continue

        for market in game["bookmakers"][0]["markets"]:
            market_key = market["key"]

            for outcome in market["outcomes"]:
                name = outcome["name"]

                sharp_probs = []
                best_price = 0
                best_book = None

                for b in bookmakers:
                    for m in b["markets"]:
                        if m["key"] != market_key:
                            continue
                        for o in m["outcomes"]:
                            if o["name"] != name:
                                continue

                            price = o["price"]

                            if b["title"] in SHARP_BOOKS:
                                sharp_probs.append(1 / price)

                            if price > best_price:
                                best_price = price
                                best_book = b["title"]

                if len(sharp_probs) < 2:
                    continue

                ev = calc_ev(best_price, sharp_probs)
                if ev < MIN_EV or ev > MAX_EV:
                    continue

                key = f"{game['id']}-{market_key}-{name}"
                if key in posted:
                    continue
                posted.add(key)

                units = round(min(3, max(0.5, ev * 20)), 2)

                msg = (
                    f"🔥 **+EV BET**\n\n"
                    f"{cfg['emoji']} {sport_key}\n"
                    f"Market: **{market_key}**\n"
                    f"Selection: **{name}**\n\n"
                    f"🏆 Odds: {best_price} ({best_book})\n"
                    f"📊 EV: {round(ev*100,2)}%\n"
                    f"📈 Stake: {units} units\n"
                    f"⏱ Starts in: {round(hrs,1)}h"
                )

                await channel.send(msg)

# ================= LOOP =================
async def loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        for sport, cfg in SPORTS.items():
            await check_sport(channel, sport, cfg)
        await asyncio.sleep(CHECK_INTERVAL)

@client.event
async def on_ready():
    print("Bot online")
    client.loop.create_task(loop())

client.run(TOKEN)
