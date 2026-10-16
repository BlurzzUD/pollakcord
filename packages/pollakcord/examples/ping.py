import asyncio
import os

from pollakcord import Bot, Interaction

bot = Bot(os.environ["POLLAKCORD_ORIGIN"], os.environ["POLLAKCORD_BOT_TOKEN"])


@bot.slash("ping", "Check whether this user-hosted bot is running")
async def ping(interaction: Interaction) -> None:
    await interaction.respond("Pong!")


@bot.on_message
async def on_message(message: dict) -> None:
    if message.get("content") == "!ping":
        await bot.send_message(message["channel_id"], "Pong!")


asyncio.run(bot.run())
