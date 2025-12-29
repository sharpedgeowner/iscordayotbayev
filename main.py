import discord
import os
import asyncio

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    client.loop.create_task(run_loop())

async def run_loop():
    while True:
        print("Bot is running...")
        await asyncio.sleep(300)  # runs every 5 minutes

client.run(TOKEN)
