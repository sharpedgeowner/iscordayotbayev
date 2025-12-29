import discord
import os
import asyncio

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(run_loop())

async def run_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while True:
        await channel.send(
            "🔥 **EV BOT ONLINE** 🔥\n"
            "Checking for +EV bets..."
        )
        await asyncio.sleep(600)  # every 10 minutes

client.run(TOKEN)
