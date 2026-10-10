import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone

# ════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════
SYS_PLUS_IDS = {1419320803199029402, 1514099294611701842}
GUILD_ID     = int(os.getenv("GUILD_ID"))
LOGS_ID      = int(os.getenv("LOGS_CHANNEL_ID", "0"))

BL_FILE      = "blacklist.json"
TEMPBAN_FILE = "tempbans.json"
FLAMME_FILE  = "flammes.json"

# ════════════════════════════════════════════════════════════════
#  STORAGE
# ════════════════════════════════════════════════════════════════
def load(file):
    if os.path.exists(file):
        try:
            with open(file) as f:
                return json.load(f)
        except: pass
    return {}

def save(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

blacklist = load(BL_FILE)   # uid -> {raison, by, at}
tempbans  = load(TEMPBAN_FILE)  # uid -> {raison, by, at, until, guild_id}
flammes   = load(FLAMME_FILE)   # uid -> {raison, by, at}

# ════════════════════════════════════════════════════════════════
#  BOT
# ════════════════════════════════════════════════════════════════
async def get_prefix(bot, message):
    return ["+", "-"]

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)
tree = bot.tree

# ════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════
def is_sys_plus(uid): return uid in SYS_PLUS_IDS

def fmt(ts: float) -> str:
    return f"<t:{int(ts)}:F>"

def fmt_rel(ts: float) -> str:
    return f"<t:{int(ts)}:R>"

def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def parse_duration(s: str) -> int:
    """'1h30m', '2j', '45m' → secondes"""
    total = 0
    for val, unit in re.findall(r"(\d+)([smhj])", s.lower()):
        val = int(val)
        total += val * {"s": 1, "m": 60, "h": 3600, "j": 86400}[unit]
    return total

def fmt_duration(seconds: int) -> str:
    j, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if j: parts.append(f"{j}j")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}min")
    if s: parts.append(f"{s}s")
    return " ".join(parts) or "0s"

async def log(guild, embed):
    if not LOGS_ID: return
    ch = guild.get_channel(LOGS_ID)
    if ch: await ch.send(embed=embed)

async def not_sys_plus(ctx):
    await ctx.reply("Tu es qui bas staff ? Prochaine fois c'est sanction !")

# ════════════════════════════════════════════════════════════════
#  MIDDLEWARE : bloquer les non-Sys+
# ════════════════════════════════════════════════════════════════
@bot.before_invoke
async def check_sysplus(ctx):
    if not is_sys_plus(ctx.author.id):
        await not_sys_plus(ctx)
        raise commands.CheckFailure()

# ════════════════════════════════════════════════════════════════
#  EVENTS
# ════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    check_tempbans.start()
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")

@bot.event
async def on_member_join(member):
    # Re-ban automatique si blacklisté
    uid = str(member.id)
    if uid in blacklist:
        data = blacklist[uid]
        try:
            await member.send(embed=discord.Embed(
                title="🚫 Accès refusé",
                description=f"Tu es **blacklisté** de ce serveur.\n**Raison :** {data['raison']}",
                color=0xFF0000,
            ))
        except: pass
        await member.ban(reason=f"[Blacklist] {data['raison']}", delete_message_days=0)

# ════════════════════════════════════════════════════════════════
#  TASK : auto-unban tempbans
# ════════════════════════════════════════════════════════════════
@tasks.loop(seconds=30)
async def check_tempbans():
    now = now_ts()
    to_unban = [(uid, d) for uid, d in list(tempbans.items()) if d["until"] <= now]
    for uid, data in to_unban:
        guild = bot.get_guild(data["guild_id"])
        if not guild: continue
        try:
            user = await bot.fetch_user(int(uid))
            await guild.unban(user, reason="Tempban expiré")
            try:
                await user.send(embed=discord.Embed(
                    title="✅ Ton ban a expiré",
                    description=f"Tu as été **débanni** de **{guild.name}**.\nTu peux désormais rejoindre à nouveau le serveur.",
                    color=0x57F287,
                ))
            except: pass
            embed = discord.Embed(title="✅ Unban automatique", color=0x57F287, timestamp=datetime.now(timezone.utc))
            embed.add_field(name="👤 Membre", value=f"`{user}` (`{uid}`)", inline=True)
            embed.add_field(name="📅 Banni le", value=fmt(data["at"]), inline=True)
            embed.add_field(name="⏱️ Durée", value=data["duree_str"], inline=True)
            await log(guild, embed)
        except: pass
        del tempbans[uid]
        save(TEMPBAN_FILE, tempbans)

# ════════════════════════════════════════════════════════════════
#  +bl <id> <raison>
# ════════════════════════════════════════════════════════════════
@bot.command(name="bl")
async def bl_cmd(ctx, user_id: str = None, *, raison: str = "Aucune raison"):
    if not user_id:
        return await ctx.reply("❌ `+bl <id> <raison>`")
    try:
        user_id = int(user_id)
        user = await bot.fetch_user(user_id)
    except:
        return await ctx.reply("❌ ID invalide.")

    uid = str(user_id)
    now = now_ts()

    blacklist[uid] = {"raison": raison, "by": str(ctx.author), "by_id": ctx.author.id, "at": now}
    save(BL_FILE, blacklist)

    try:
        await user.send(embed=discord.Embed(
            title="🚫 Tu as été blacklisté",
            description=f"**Serveur :** {ctx.guild.name}\n**Raison :** {raison}\n**Par :** {ctx.author}\n**Date :** {fmt(now)}\n\n*Cette sanction est permanente.*",
            color=0xFF0000,
        ))
    except: pass

    try:
        await ctx.guild.ban(user, reason=f"[BL] {raison}", delete_message_days=0)
    except discord.Forbidden:
        return await ctx.reply("❌ Permissions insuffisantes pour ban.")

    embed_log = discord.Embed(title="🚫 Blacklist", color=0xFF0000, timestamp=datetime.now(timezone.utc))
    embed_log.add_field(name="👤 Membre", value=f"`{user}` (`{user_id}`)", inline=True)
    embed_log.add_field(name="🛡️ Par", value=f"{ctx.author.mention}", inline=True)
    embed_log.add_field(name="📝 Raison", value=raison, inline=False)
    embed_log.add_field(name="📅 Date", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    embed_log.set_footer(text="Sanction permanente")
    await log(ctx.guild, embed_log)

    await ctx.reply(embed=discord.Embed(
        description=f"🚫 **{user}** a été **blacklisté**.\n📝 Raison : {raison}",
        color=0xFF0000,
    ))

# ════════════════════════════════════════════════════════════════
#  +ban <id> <durée> <raison>
# ════════════════════════════════════════════════════════════════
@bot.command(name="ban")
async def ban_cmd(ctx, user_id: str = None, duree: str = None, *, raison: str = "Aucune raison"):
    if not user_id or not duree:
        return await ctx.reply("❌ `+ban <id> <durée> <raison>` — ex: `+ban 123456 1h30m Spam`")
    try:
        user_id = int(user_id)
        user = await bot.fetch_user(user_id)
    except:
        return await ctx.reply("❌ ID invalide.")

    seconds = parse_duration(duree)
    if seconds <= 0:
        return await ctx.reply("❌ Durée invalide. Exemple : `1h`, `30m`, `2j`, `1h30m`")

    uid = str(user_id)
    now = now_ts()
    until = now + seconds
    duree_str = fmt_duration(seconds)

    tempbans[uid] = {
        "raison": raison, "by": str(ctx.author), "by_id": ctx.author.id,
        "at": now, "until": until, "guild_id": ctx.guild.id, "duree_str": duree_str,
    }
    save(TEMPBAN_FILE, tempbans)

    try:
        await user.send(embed=discord.Embed(
            title="🔨 Tu as été banni temporairement",
            description=(
                f"**Serveur :** {ctx.guild.name}\n"
                f"**Raison :** {raison}\n"
                f"**Par :** {ctx.author}\n"
                f"**Durée :** {duree_str}\n"
                f"**Banni le :** {fmt(now)}\n"
                f"**Fin du ban :** {fmt(until)} ({fmt_rel(until)})"
            ),
            color=0xFF6600,
        ))
    except: pass

    try:
        await ctx.guild.ban(user, reason=f"[Tempban {duree_str}] {raison}", delete_message_days=0)
    except discord.Forbidden:
        return await ctx.reply("❌ Permissions insuffisantes pour ban.")

    embed_log = discord.Embed(title="🔨 Tempban", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    embed_log.add_field(name="👤 Membre", value=f"`{user}` (`{user_id}`)", inline=True)
    embed_log.add_field(name="🛡️ Par", value=f"{ctx.author.mention}", inline=True)
    embed_log.add_field(name="⏱️ Durée", value=f"`{duree_str}`", inline=True)
    embed_log.add_field(name="📅 Banni le", value=f"{fmt(now)}", inline=True)
    embed_log.add_field(name="🔓 Fin du ban", value=f"{fmt(until)}\n{fmt_rel(until)}", inline=True)
    embed_log.add_field(name="📝 Raison", value=raison, inline=False)
    await log(ctx.guild, embed_log)

    await ctx.reply(embed=discord.Embed(
        description=f"🔨 **{user}** banni pour **{duree_str}**.\n📝 Raison : {raison}\n🔓 Fin : {fmt(until)}",
        color=0xFF6600,
    ))

# ════════════════════════════════════════════════════════════════
#  -baninfo <id>
# ════════════════════════════════════════════════════════════════
@bot.command(name="baninfo")
async def baninfo_cmd(ctx, user_id: str = None):
    if not user_id:
        return await ctx.reply("❌ `-baninfo <id>`")
    uid = str(user_id).strip()
    data = tempbans.get(uid)
    if not data:
        return await ctx.reply(embed=discord.Embed(description="❌ Aucun tempban trouvé pour cet ID.", color=0xFF0000))
    try:
        user = await bot.fetch_user(int(uid))
        name = str(user)
        avatar = user.display_avatar.url
    except:
        name = f"Utilisateur inconnu ({uid})"
        avatar = None

    remaining = max(0, data["until"] - now_ts())
    embed = discord.Embed(title="🔍 Infos Tempban", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="👤 Membre", value=f"`{name}` (`{uid}`)", inline=True)
    embed.add_field(name="🛡️ Banni par", value=data["by"], inline=True)
    embed.add_field(name="⏱️ Durée totale", value=f"`{data['duree_str']}`", inline=True)
    embed.add_field(name="📅 Banni le", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    embed.add_field(name="🔓 Fin du ban", value=f"{fmt(data['until'])}\n{fmt_rel(data['until'])}", inline=True)
    embed.add_field(name="⏳ Temps restant", value=f"`{fmt_duration(int(remaining))}`", inline=True)
    embed.add_field(name="📝 Raison", value=data["raison"], inline=False)
    if avatar: embed.set_thumbnail(url=avatar)
    await ctx.reply(embed=embed)

# ════════════════════════════════════════════════════════════════
#  -blinfo <id>
# ════════════════════════════════════════════════════════════════
@bot.command(name="blinfo")
async def blinfo_cmd(ctx, user_id: str = None):
    if not user_id:
        return await ctx.reply("❌ `-blinfo <id>`")
    uid = str(user_id).strip()
    data = blacklist.get(uid)
    if not data:
        return await ctx.reply(embed=discord.Embed(description="❌ Aucune blacklist trouvée pour cet ID.", color=0xFF0000))
    try:
        user = await bot.fetch_user(int(uid))
        name = str(user)
        avatar = user.display_avatar.url
    except:
        name = f"Utilisateur inconnu ({uid})"
        avatar = None

    embed = discord.Embed(title="🔍 Infos Blacklist", color=0xFF0000, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="👤 Membre", value=f"`{name}` (`{uid}`)", inline=True)
    embed.add_field(name="🛡️ Blacklisté par", value=data["by"], inline=True)
    embed.add_field(name="📅 Date", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    embed.add_field(name="📝 Raison", value=data["raison"], inline=False)
    embed.set_footer(text="Sanction permanente — Aucune expiration")
    if avatar: embed.set_thumbnail(url=avatar)
    await ctx.reply(embed=embed)

# ════════════════════════════════════════════════════════════════
#  /flamme <id> <raison>
# ════════════════════════════════════════════════════════════════
@tree.command(name="flamme", description="Flamme un membre — ban définitif toutes plateformes [Sys+]")
@app_commands.describe(user_id="ID Discord du membre", raison="Raison de la flamme")
async def flamme_slash(interaction: discord.Interaction, user_id: str, raison: str = "Aucune raison"):
    if not is_sys_plus(interaction.user.id):
        return await interaction.response.send_message(
            "Tu es qui bas staff ? Prochaine fois c'est sanction !", ephemeral=True)
    try:
        user = await bot.fetch_user(int(user_id))
    except:
        return await interaction.response.send_message("❌ ID invalide.", ephemeral=True)

    uid = str(user_id)
    now = now_ts()

    flammes[uid] = {"raison": raison, "by": str(interaction.user), "by_id": interaction.user.id, "at": now}
    blacklist[uid] = {"raison": f"[FLAMME] {raison}", "by": str(interaction.user), "by_id": interaction.user.id, "at": now}
    save(FLAMME_FILE, flammes)
    save(BL_FILE, blacklist)

    try:
        await user.send(embed=discord.Embed(
            title="🔥 Tu as été flammé",
            description=(
                f"**Serveur :** {interaction.guild.name}\n"
                f"**Raison :** {raison}\n"
                f"**Par :** {interaction.user}\n"
                f"**Date :** {fmt(now)}\n\n"
                "Cette sanction est **permanente et définitive**.\n"
                "Ton compte et ton IP ont été signalés."
            ),
            color=0xFF0000,
        ))
    except: pass

    try:
        await interaction.guild.ban(user, reason=f"[FLAMME] {raison}", delete_message_days=7)
    except discord.Forbidden:
        return await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)

    embed_log = discord.Embed(title="🔥 FLAMME", color=0xE74C3C, timestamp=datetime.now(timezone.utc))
    embed_log.add_field(name="👤 Membre", value=f"`{user}` (`{user_id}`)", inline=True)
    embed_log.add_field(name="🛡️ Par", value=f"{interaction.user.mention}", inline=True)
    embed_log.add_field(name="📅 Date", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    embed_log.add_field(name="📝 Raison", value=raison, inline=False)
    embed_log.set_footer(text="Sanction maximale — Ban définitif + IP signalée")
    await log(interaction.guild, embed_log)

    await interaction.response.send_message(embed=discord.Embed(
        title="🔥 Flamme exécutée",
        description=f"**{user}** a été **flammé**.\n📝 Raison : {raison}\n\nBan définitif appliqué, IP et compte signalés à Discord.",
        color=0xE74C3C,
    ))

# ════════════════════════════════════════════════════════════════
#  /wet-info <id>
# ════════════════════════════════════════════════════════════════
@tree.command(name="wet-info", description="Infos sur une flamme [Sys+]")
@app_commands.describe(user_id="ID Discord du membre")
async def wet_info(interaction: discord.Interaction, user_id: str):
    if not is_sys_plus(interaction.user.id):
        return await interaction.response.send_message(
            "Tu es qui bas staff ? Prochaine fois c'est sanction !", ephemeral=True)
    uid = str(user_id).strip()
    data = flammes.get(uid)
    if not data:
        return await interaction.response.send_message(
            embed=discord.Embed(description="❌ Aucune flamme trouvée pour cet ID.", color=0xFF0000),
            ephemeral=True)
    try:
        user = await bot.fetch_user(int(uid))
        name = str(user)
        avatar = user.display_avatar.url
    except:
        name = f"Utilisateur inconnu ({uid})"
        avatar = None

    embed = discord.Embed(title="🔥 Infos Flamme", color=0xE74C3C, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="👤 Membre", value=f"`{name}` (`{uid}`)", inline=True)
    embed.add_field(name="🛡️ Flammé par", value=data["by"], inline=True)
    embed.add_field(name="📅 Date", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    embed.add_field(name="📝 Raison", value=data["raison"], inline=False)
    embed.set_footer(text="Sanction maximale — Ban définitif + IP signalée")
    if avatar: embed.set_thumbnail(url=avatar)
    await interaction.response.send_message(embed=embed)

# ════════════════════════════════════════════════════════════════
#  LANCEMENT
# ════════════════════════════════════════════════════════════════
bot.run(os.environ["TOKEN"])
