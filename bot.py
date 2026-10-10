import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

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
    return ["+", "-", "&"]

def make_activity():
    return discord.Activity(
        type=discord.ActivityType.watching,
        name="Shotojo \U0001F338 #\U0001F1EF\U0001F1F5",   # Shotojo 🌸 #🇯🇵
        state="Nous vous préparons de grandes choses",
    )

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None,
    status=discord.Status.online,
    activity=make_activity(),
)
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

# Compteur de tentatives des non-Sys+ (en mémoire) : 2e tentative = timeout 1 min
violations = {}
VIOLATION_LIMIT = 2
TIMEOUT_MIN = 1

async def sys_violation(member) -> str:
    """Appelé quand un non-Sys+ tente une commande. Retourne le message à envoyer."""
    uid = member.id
    violations[uid] = violations.get(uid, 0) + 1

    if violations[uid] < VIOLATION_LIMIT:
        return "Tu es qui bas staff ? Prochaine fois c'est sanction !"

    violations.pop(uid, None)
    guild = getattr(member, "guild", None)
    try:
        await member.timeout(timedelta(minutes=TIMEOUT_MIN), reason="Tentative d'utilisation de commandes Sys+")
        sanction = f"🔇 Je t'avais prévenu, t'es **timeout {TIMEOUT_MIN} minute**."
        ok = True
    except Exception:
        sanction = "Je t'avais prévenu... (timeout impossible, permissions insuffisantes)"
        ok = False

    if guild:
        embed = discord.Embed(title="🔇 Auto-timeout", color=0xFF6600, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="👤 Membre", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="📝 Raison", value="Tentatives de commandes Sys+", inline=True)
        embed.add_field(name="⏱️ Durée", value=f"`{TIMEOUT_MIN} min`" if ok else "Échec ❌", inline=True)
        try: await log(guild, embed)
        except Exception: pass
    return sanction

async def not_sys_plus(ctx):
    await ctx.reply(await sys_violation(ctx.author))

async def try_dm(user, embed) -> bool:
    """Envoie un MP. Retourne False si impossible (MP fermés / aucun serveur en commun)."""
    try:
        await user.send(embed=embed)
        return True
    except:
        return False

async def make_invite(guild):
    """Crée une invitation permanente pour que le membre puisse revenir."""
    try:
        channels = [guild.system_channel, guild.rules_channel] + list(guild.text_channels)
        for ch in channels:
            if ch and ch.permissions_for(guild.me).create_instant_invite:
                inv = await ch.create_invite(max_age=0, max_uses=0, unique=False, reason="Invitation de retour (fin de tempban)")
                return inv.url
    except:
        pass
    return None

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
    await bot.change_presence(
        status=discord.Status.online,
        activity=make_activity(),
    )
    if not check_tempbans.is_running():
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

            invite = await make_invite(guild)
            desc = (
                f"Tu as été **débanni** de **{guild.name}**.\n"
                "Tu peux désormais **rejoindre à nouveau le serveur**."
            )
            if invite:
                desc += f"\n\n🔗 Lien pour revenir : {invite}"
            dm_ok = await try_dm(user, discord.Embed(
                title="✅ Ton ban a expiré",
                description=desc,
                color=0x57F287,
            ))

            embed = discord.Embed(title="✅ Unban automatique", color=0x57F287, timestamp=datetime.now(timezone.utc))
            embed.add_field(name="👤 Membre", value=f"`{user}` (`{uid}`)", inline=True)
            embed.add_field(name="📅 Banni le", value=fmt(data["at"]), inline=True)
            embed.add_field(name="⏱️ Durée", value=data["duree_str"], inline=True)
            embed.add_field(name="📩 MP", value="Envoyé ✅" if dm_ok else "Impossible ❌ (aucun serveur en commun / MP fermés)", inline=False)
            await log(guild, embed)
        except: pass
        tempbans.pop(uid, None)
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

    invite = await make_invite(ctx.guild)
    desc = (
        f"**Serveur :** {ctx.guild.name}\n"
        f"**Raison :** {raison}\n"
        f"**Par :** {ctx.author}\n"
        f"**Durée :** {duree_str}\n"
        f"**Banni le :** {fmt(now)}\n"
        f"**Fin du ban :** {fmt(until)} ({fmt_rel(until)})\n\n"
        "✅ **Tu pourras re-rejoindre le serveur une fois la durée terminée.**"
    )
    if invite:
        desc += f"\n🔗 Lien pour revenir : {invite}"

    try:
        await user.send(embed=discord.Embed(
            title="🔨 Tu as été banni temporairement",
            description=desc,
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
#  &unbl <id>
# ════════════════════════════════════════════════════════════════
@bot.command(name="unbl")
async def unbl_cmd(ctx, user_id: str = None):
    if not user_id:
        return await ctx.reply("❌ `&unbl <id>`")
    uid = str(user_id).strip()
    if uid in flammes:
        return await ctx.reply("🔥 Cette personne est **flammée**, utilise `/unflamme` à la place.")
    if uid not in blacklist:
        return await ctx.reply(embed=discord.Embed(description="❌ Cet ID n'est pas blacklisté.", color=0xFF0000))
    try:
        user = await bot.fetch_user(int(uid))
    except:
        return await ctx.reply("❌ ID invalide.")

    try:
        await ctx.guild.unban(user, reason=f"[UNBL] par {ctx.author}")
    except discord.NotFound:
        pass  # pas banni sur le serveur, on retire quand même la blacklist
    except discord.Forbidden:
        return await ctx.reply("❌ Permissions insuffisantes pour unban.")

    data = blacklist.pop(uid)
    save(BL_FILE, blacklist)

    now = now_ts()
    invite = await make_invite(ctx.guild)
    desc = f"Ta **blacklist** sur **{ctx.guild.name}** a été **levée**.\nTu peux de nouveau rejoindre le serveur."
    if invite:
        desc += f"\n\n🔗 Lien pour revenir : {invite}"
    dm_ok = await try_dm(user, discord.Embed(title="✅ Blacklist levée", description=desc, color=0x57F287))

    embed_log = discord.Embed(title="✅ UNBL", color=0x57F287, timestamp=datetime.now(timezone.utc))
    embed_log.add_field(name="👤 Membre", value=f"`{user}` (`{uid}`)", inline=True)
    embed_log.add_field(name="🛡️ Par", value=ctx.author.mention, inline=True)
    embed_log.add_field(name="📅 Date", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    embed_log.add_field(name="📝 Raison de la blacklist", value=data["raison"], inline=False)
    embed_log.add_field(name="📩 MP", value="Envoyé ✅" if dm_ok else "Impossible ❌", inline=True)
    await log(ctx.guild, embed_log)

    await ctx.reply(embed=discord.Embed(
        description=f"✅ **{user}** a été retiré de la blacklist et débanni.",
        color=0x57F287,
    ))

# ════════════════════════════════════════════════════════════════
#  /flamme <id> <raison>
# ════════════════════════════════════════════════════════════════
@tree.command(name="flamme", description="Flamme un membre — ban définitif toutes plateformes [Sys+]")
@app_commands.describe(user_id="ID Discord du membre", raison="Raison de la flamme")
async def flamme_slash(interaction: discord.Interaction, user_id: str, raison: str = "Aucune raison"):
    if not is_sys_plus(interaction.user.id):
        return await interaction.response.send_message(
            await sys_violation(interaction.user), ephemeral=True)
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
#  /flamme-info <id>
# ════════════════════════════════════════════════════════════════
@tree.command(name="flamme-info", description="Infos sur une flamme [Sys+]")
@app_commands.describe(user_id="ID Discord du membre")
async def flamme_info(interaction: discord.Interaction, user_id: str):
    if not is_sys_plus(interaction.user.id):
        return await interaction.response.send_message(
            await sys_violation(interaction.user), ephemeral=True)
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
#  /unflamme <id>
# ════════════════════════════════════════════════════════════════
@tree.command(name="unflamme", description="Retire une flamme (unban + retrait de la blacklist) [Sys+]")
@app_commands.describe(user_id="ID Discord du membre")
async def unflamme_slash(interaction: discord.Interaction, user_id: str):
    if not is_sys_plus(interaction.user.id):
        return await interaction.response.send_message(
            await sys_violation(interaction.user), ephemeral=True)

    uid = str(user_id).strip()
    if uid not in flammes:
        return await interaction.response.send_message(
            embed=discord.Embed(description="❌ Aucune flamme trouvée pour cet ID.", color=0xFF0000),
            ephemeral=True)
    try:
        user = await bot.fetch_user(int(uid))
    except:
        return await interaction.response.send_message("❌ ID invalide.", ephemeral=True)

    try:
        await interaction.guild.unban(user, reason=f"[UNFLAMME] par {interaction.user}")
    except discord.NotFound:
        pass  # pas banni sur le serveur, on retire quand même la flamme
    except discord.Forbidden:
        return await interaction.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)

    data = flammes.pop(uid)
    blacklist.pop(uid, None)
    save(FLAMME_FILE, flammes)
    save(BL_FILE, blacklist)

    now = now_ts()
    invite = await make_invite(interaction.guild)
    desc = f"Ta **flamme** sur **{interaction.guild.name}** a été **levée**.\nTu peux de nouveau rejoindre le serveur."
    if invite:
        desc += f"\n\n🔗 Lien pour revenir : {invite}"
    dm_ok = await try_dm(user, discord.Embed(title="✅ Flamme levée", description=desc, color=0x57F287))

    embed_log = discord.Embed(title="✅ UNFLAMME", color=0x57F287, timestamp=datetime.now(timezone.utc))
    embed_log.add_field(name="👤 Membre", value=f"`{user}` (`{uid}`)", inline=True)
    embed_log.add_field(name="🛡️ Par", value=interaction.user.mention, inline=True)
    embed_log.add_field(name="📅 Date", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    embed_log.add_field(name="📝 Raison de la flamme", value=data["raison"], inline=False)
    embed_log.add_field(name="📩 MP", value="Envoyé ✅" if dm_ok else "Impossible ❌", inline=True)
    await log(interaction.guild, embed_log)

    await interaction.response.send_message(embed=discord.Embed(
        title="✅ Flamme retirée",
        description=f"**{user}** n'est plus flammé (unban + retiré de la blacklist).",
        color=0x57F287,
    ))

# ════════════════════════════════════════════════════════════════
#  /unban-all  (ne touche pas aux blacklist / flammes)
# ════════════════════════════════════════════════════════════════
@tree.command(name="unban-all", description="Déban tout le monde sauf les blacklist et flammes [Sys+]")
async def unban_all_slash(interaction: discord.Interaction):
    if not is_sys_plus(interaction.user.id):
        return await interaction.response.send_message(
            await sys_violation(interaction.user), ephemeral=True)

    await interaction.response.defer()
    guild = interaction.guild
    protected = set(blacklist.keys()) | set(flammes.keys())
    unbanned = skipped = failed = 0

    async for entry in guild.bans(limit=None):
        uid = str(entry.user.id)
        if uid in protected:
            skipped += 1
            continue
        try:
            await guild.unban(entry.user, reason=f"[UNBAN-ALL] par {interaction.user}")
            tempbans.pop(uid, None)
            unbanned += 1
        except:
            failed += 1
        await asyncio.sleep(0.5)  # évite le rate limit

    save(TEMPBAN_FILE, tempbans)

    now = now_ts()
    embed_log = discord.Embed(title="🔓 UNBAN-ALL", color=0x57F287, timestamp=datetime.now(timezone.utc))
    embed_log.add_field(name="🛡️ Par", value=interaction.user.mention, inline=True)
    embed_log.add_field(name="✅ Débannis", value=str(unbanned), inline=True)
    embed_log.add_field(name="🚫 Ignorés (BL/flamme)", value=str(skipped), inline=True)
    if failed:
        embed_log.add_field(name="⚠️ Échecs", value=str(failed), inline=True)
    embed_log.add_field(name="📅 Date", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=False)
    await log(guild, embed_log)

    await interaction.followup.send(embed=discord.Embed(
        title="🔓 Unban-all terminé",
        description=(
            f"✅ **{unbanned}** membre(s) débanni(s)\n"
            f"🚫 **{skipped}** ignoré(s) (blacklist / flamme)\n"
            + (f"⚠️ **{failed}** échec(s)\n" if failed else "")
        ),
        color=0x57F287,
    ))

# ════════════════════════════════════════════════════════════════
#  -banpanel  (tempbans + blacklist + flammes + bans manuels)
# ════════════════════════════════════════════════════════════════
PANEL_PER_PAGE = 4
CATS = {
    "tempban": ("🔨", "Tempban", 0xFF6600),
    "bl":      ("🚫", "Blacklist", 0xFF0000),
    "flamme":  ("🔥", "Flamme", 0xE74C3C),
    "manuel":  ("⚖️", "Ban manuel", 0x95A5A6),
}

def cut(text, n=250):
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "…"

async def collect_bans(guild):
    entries = []
    for uid, d in tempbans.items():
        entries.append({"type": "tempban", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in flammes.items():
        entries.append({"type": "flamme", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in blacklist.items():
        if uid in flammes:  # déjà affiché comme flamme
            continue
        entries.append({"type": "bl", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})

    known = set(tempbans) | set(blacklist) | set(flammes)
    try:
        async for e in guild.bans(limit=None):
            uid = str(e.user.id)
            if uid in known:
                continue
            entries.append({"type": "manuel", "uid": uid, "data": {"raison": e.reason or "Aucune raison"},
                            "at": None, "user": e.user})
    except Exception:
        pass

    entries.sort(key=lambda x: x["at"] or 0, reverse=True)
    return entries

async def entry_name(entry):
    if entry["user"]:
        return str(entry["user"])
    try:
        u = await bot.fetch_user(int(entry["uid"]))
        return str(u)
    except Exception:
        return "Utilisateur inconnu"

def entry_value(entry) -> str:
    t, uid, d = entry["type"], entry["uid"], entry["data"]
    lines = [f"🆔 `{uid}`"]
    if t == "tempban":
        remaining = max(0, d["until"] - now_ts())
        lines += [
            f"🛡️ **Par :** {d['by']}",
            f"⏱️ **Durée :** `{d['duree_str']}`  •  ⏳ **Reste :** `{fmt_duration(int(remaining))}`",
            f"📅 **Banni le :** {fmt(d['at'])} ({fmt_rel(d['at'])})",
            f"🔓 **Fin :** {fmt(d['until'])} ({fmt_rel(d['until'])})",
            f"📝 **Raison :** {cut(d['raison'])}",
        ]
    elif t in ("bl", "flamme"):
        lines += [
            f"🛡️ **Par :** {d['by']}",
            f"📅 **Date :** {fmt(d['at'])} ({fmt_rel(d['at'])})",
            f"📝 **Raison :** {cut(d['raison'])}",
            "♾️ **Permanent**" + (" — IP signalée" if t == "flamme" else ""),
        ]
    else:
        lines += [
            f"📝 **Raison :** {cut(d['raison'])}",
            "ℹ️ Ban fait à la main (hors bot)",
        ]
    return "\n".join(lines)[:1024]

class BanPanel(discord.ui.View):
    def __init__(self, author_id, entries):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.entries = entries
        self.filter = "all"
        self.page = 0
        self.message = None

    def filtered(self):
        if self.filter == "all":
            return self.entries
        return [e for e in self.entries if e["type"] == self.filter]

    def total_pages(self):
        return max(1, -(-len(self.filtered()) // PANEL_PER_PAGE))

    async def build(self):
        items = self.filtered()
        pages = self.total_pages()
        self.page = max(0, min(self.page, pages - 1))
        chunk = items[self.page * PANEL_PER_PAGE:(self.page + 1) * PANEL_PER_PAGE]

        counts = {k: sum(1 for e in self.entries if e["type"] == k) for k in CATS}
        embed = discord.Embed(
            title="🛡️ Panel des bans",
            description=(
                f"**Total : {len(self.entries)}**\n"
                f"🔨 Tempbans : `{counts['tempban']}`  •  🚫 Blacklist : `{counts['bl']}`\n"
                f"🔥 Flammes : `{counts['flamme']}`  •  ⚖️ Bans manuels : `{counts['manuel']}`"
            ),
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
        if not chunk:
            embed.add_field(name="Aucun résultat", value="Aucun ban dans cette catégorie.", inline=False)
        for e in chunk:
            emoji, label, _ = CATS[e["type"]]
            name = await entry_name(e)
            embed.add_field(name=f"{emoji} {label} — {name}"[:256], value=entry_value(e), inline=False)
        filt = "Tous" if self.filter == "all" else CATS[self.filter][1]
        embed.set_footer(text=f"Filtre : {filt}  •  Page {self.page + 1}/{pages}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except Exception: pass

    @discord.ui.select(
        placeholder="Filtrer par type…",
        options=[
            discord.SelectOption(label="Tous", value="all", emoji="📋"),
            discord.SelectOption(label="Tempbans", value="tempban", emoji="🔨"),
            discord.SelectOption(label="Blacklist", value="bl", emoji="🚫"),
            discord.SelectOption(label="Flammes", value="flamme", emoji="🔥"),
            discord.SelectOption(label="Bans manuels", value="manuel", emoji="⚖️"),
        ],
    )
    async def filter_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.filter = select.values[0]
        self.page = 0
        await interaction.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page - 1) % self.total_pages()
        await interaction.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page + 1) % self.total_pages()
        await interaction.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="🔄 Actualiser", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.entries = await collect_bans(interaction.guild)
        await interaction.response.edit_message(embed=await self.build(), view=self)

@bot.command(name="banpanel")
async def banpanel_cmd(ctx):
    msg = await ctx.reply("⏳ Chargement du panel…")
    entries = await collect_bans(ctx.guild)
    view = BanPanel(ctx.author.id, entries)
    view.message = msg
    await msg.edit(content=None, embed=await view.build(), view=view)

# ════════════════════════════════════════════════════════════════
#  -help
# ════════════════════════════════════════════════════════════════
@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="📖 Aide — Commandes Sys+",
        description="Préfixes disponibles : `+`, `-` et `&`\nToutes les commandes sont réservées aux **Sys+**.",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="🚫 Blacklist",
        value=(
            "`+bl <id> <raison>` — Blacklist + ban permanent\n"
            "`&unbl <id>` — Retire une blacklist + unban\n"
            "`-blinfo <id>` — Infos sur une blacklist"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔨 Tempban",
        value=(
            "`+ban <id> <durée> <raison>` — Ban temporaire\n"
            "Durées : `s`, `m`, `h`, `j` (ex: `1h30m`, `2j`)\n"
            "`-baninfo <id>` — Infos sur un tempban"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔥 Flamme (slash)",
        value=(
            "`/flamme <id> <raison>` — Ban définitif toutes plateformes\n"
            "`/flamme-info <id>` — Infos sur une flamme\n"
            "`/unflamme <id>` — Retire une flamme (unban + retrait BL)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔓 Unban",
        value="`/unban-all` — Déban tout le monde sauf blacklist et flammes",
        inline=False,
    )
    embed.add_field(
        name="🛡️ Panel",
        value="`-banpanel` — Liste détaillée de tous les bans (tempban, BL, flamme, manuels)",
        inline=False,
    )
    embed.add_field(
        name="❓ Aide",
        value="`-help` — Affiche ce message",
        inline=False,
    )
    embed.set_footer(text=f"Demandé par {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=embed)

# ════════════════════════════════════════════════════════════════
#  LANCEMENT
# ════════════════════════════════════════════════════════════════
bot.run(os.environ["TOKEN"])
