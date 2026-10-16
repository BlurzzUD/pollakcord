import os

import pollakcord as discord
from pollakcord.ext import commands

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", origin=os.environ["POLLAKCORD_ORIGIN"], intents=intents)


@bot.event
async def on_ready():
    print(f"Connected as {bot.user}")


@bot.command()
async def ping(ctx: commands.Context):
    await ctx.send("Pong!")


@bot.tree.command(name="ping", description="Check whether the bot is running")
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    channel = bot.get_channel(int(os.environ["POLLAKCORD_WELCOME_CHANNEL_ID"]))
    if channel is not None and channel.guild.id == member.guild.id:
        name = discord.utils.escape_mentions(discord.utils.escape_markdown(member.name))
        await channel.send(f"Welcome, {name}! 👋")


bot.run(os.environ["POLLAKCORD_BOT_TOKEN"])
