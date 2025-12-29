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

# Markets per sport
SPORT_MARKETS = {
    "americanfootball_nfl": ["h2h", "touchdown_scorer", "totals", "spreads"],
    "australianfootball_afl": [],  # empty = fetch all markets
    "rugbyleague_nrl": ["h2h", "tryscorer"],
    "soccer_epl": ["h2h", "totals", "first_goal", "anytime_goal_scorer"],
    "soccer_uefa_champs_league": ["h2h", "totals", "first_goal", "anytime_goal_scorer"]
}

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
last_odds = {}             # Track line movement: {game-market-outcome-book: last_price}

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
    markets = SPORT_MARKETS.get(sport_key)
    markets_param = ",".join(markets) if markets else ""  # empty fetches all

    url = (
        f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions={REGION}"
        f"&markets={markets_param}"
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
        home = game.get("home_team", "N/A")
        away = game.get("away_team", "N/A")
        hrs_to_start = hours_until_start(game["commence_time"])
        books = game.get("bookmakers", [])
        if len(books) < 2:
            continue

        for market_idx, market in enumerate(books[0]["markets"]):
            market_name = market.get("key", "Market")
            for outcome_idx, outcome in enumerate(market.get("outcomes", [])):
                outcome_name = outcome["name"]

                # ----- REFERENCE ODDS (TRUSTED BOOKS ONLY) -----
                ref_prices = []
                for b in books:
                    if b["title"] in TRUSTED_BOOKS:
                        try:
                            ref_price = next(
                                o["price"] for o in b["markets"][market_idx]["outcomes"]
                                if o["name"] == outcome_name
                            )
                            ref_prices.append(ref_price)
                        except:
                            continue

                if len(ref_prices) < 2:
                    continue

                true_prob = sum(1 / p for p in ref_prices) / len(ref_prices)
                if max(ref_prices)/min(ref_prices) > 1.15:
                    continue  # filter out outliers

                # ----- BEST BOOK & LINE MOVEMENT -----
                best_price = 0
                best_book = None
                supplementary = []
                line_movement_note = ""

                for b in books:
                    try:
                        price = next(
                            o["price"] for o in b["markets"][market_idx]["outcomes"]
                            if o["name"] == outcome_name
                        )
                        key = f"{game_id}-{market_name}-{outcome_name}-{b['title']}"
                        prev_price = last_odds.get(key)
                        if prev_price and prev_price != price:
                            line_movement_note += f"📈 {b['title']} moved: {prev_price} → {price}\n"
                        last_odds[key] = price

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

                bet_key = f"{game_id}-{market_name}-{outcome_name}"
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
                    f"Market: **{market_name}**\n"
                    f"🆚 {away} vs {home}\n"
                    f"📌 **{outcome_name}**\n\n"
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
