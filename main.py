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
MAX_HOURS_TO_START = 24

TRUSTED_BOOKS = ["Sportsbet", "PointsBet", "TAB", "Neds", "Betfair AU"]

SPORTS = {
    "americanfootball_nfl": {
        "name": "🏈 NFL",
        "markets": [
            "h2h", "spreads", "totals",
            "anytime_touchdown",
            "player_pass_yds", "player_pass_tds",
            "player_rush_yds", "player_rec_yds"
        ]
    },
    "basketball_nba": {
        "name": "🏀 NBA",
        "markets": [
            "h2h", "spreads", "totals",
            "player_points", "player_rebounds", "player_assists"
        ]
    },
    "soccer_epl": {
        "name": "⚽ Soccer",
        "markets": ["h2h", "totals", "anytime_goal_scorer"]
    }
}

# ================= DISCORD =================
intents = discord.Intents.default()
client = discord.Client(intents=intents)

posted_bets = set()

# ================= HELPERS =================
def hours_until_start(commence):
    start = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    return (start - datetime.now(timezone.utc)).total_seconds() / 3600

def calc_ev(price, true_prob):
    return (price * true_prob) - 1

def staking(ev):
    if ev >= 0.08: return 3
    if ev >= 0.06: return 2
    if ev >= 0.04: return 1
    return 0.5

# ================= CORE =================
async def check_sport(channel, sport_key, cfg):
    for market in cfg["markets"]:
        url = (
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
            f"?apiKey={ODDS_API_KEY}"
            f"&regions={REGION}"
            f"&markets={market}"
            f"&oddsFormat={ODDS_FORMAT}"
        )

        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            games = r.json()
        except:
            continue

        for game in games:
            if hours_until_start(game["commence_time"]) > MAX_HOURS_TO_START:
                continue

            books = game.get("bookmakers", [])
            if len(books) < 2:
                continue

            for outcome in books[0]["markets"][0]["outcomes"]:
                name = outcome["name"]

                ref_prices = []
                for b in books:
                    if b["title"] in TRUSTED_BOOKS:
                        try:
                            price = next(o["price"] for o in b["markets"][0]["outcomes"] if o["name"] == name)
                            ref_prices.append(price)
                        except:
                            pass

                if len(ref_prices) < 2:
                    continue

                true_prob = sum(1/p for p in ref_prices) / len(ref_prices)

                best_price = 0
                best_book = None
                for b in books:
                    try:
                        price = next(o["price"] for o in b["markets"][0]["outcomes"] if o["name"] == name)
                        if price > best_price:
                            best_price = price
                            best_book = b["title"]
                    except:
                        pass

                ev = calc_ev(best_price, true_prob)
                if ev < MIN_EV:
                    continue

                bet_id = f"{game['id']}-{market}-{name}"
                if bet_id in posted_bets:
                    continue
                posted_bets.add(bet_id)

                units = staking(ev)

                msg = (
                    f"🔥 **+EV BET** 🔥\n\n"
                    f"{cfg['name']}\n"
                    f"Market: **{market}**\n"
                    f"Pick: **{name}**\n"
                    f"Best Odds: **{best_price} ({best_book})**\n"
                    f"EV: **{round(ev*100,2)}%**\n"
                    f"Stake: **{units} units**"
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
