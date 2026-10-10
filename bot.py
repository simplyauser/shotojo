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

# Préfixes autorisés par commande
# + = bl, ban
# - = baninfo, blinfo, banpanel, maintenance, help
# & = unbl
PREFIX_RULES = {
    "bl":          "+",
    "ban":         "+",
    "baninfo":     "-",
    "blinfo":      "-",
    "banpanel":    "-",
    "maintenance": "-",
    "help":        "-",
    "unbl":        "&",
}

# ════════════════════════════════════════════════════════════════
#  STORAGE
# ════════════════════════════════════════════════════════════════
def load(file):
    if os.path.exists(file):
        try:
            with open(file) as f: return json.load(f)
        except: pass
    return {}

def save(file, data):
    with open(file, "w") as f: json.dump(data, f, indent=2)

blacklist = load(BL_FILE)
tempbans  = load(TEMPBAN_FILE)
flammes   = load(FLAMME_FILE)

# ════════════════════════════════════════════════════════════════
#  BOT
# ════════════════════════════════════════════════════════════════
async def get_prefix(bot, message):
    return ["+", "-", "&"]

def make_activity():
    return discord.Activity(
        type=discord.ActivityType.watching,
        name="Shotojo 🌸 #🇯🇵",
        state="Nous vous préparons de grandes choses",
    )

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None,
                   status=discord.Status.online, activity=make_activity())
tree = bot.tree
maintenance = False

async def apply_presence():
    if maintenance:
        await bot.change_presence(status=discord.Status.dnd,
            activity=discord.Game(name="🔧 Maintenance en cours"))
    else:
        await bot.change_presence(status=discord.Status.online, activity=make_activity())

# ════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════
def is_sys_plus(uid): return uid in SYS_PLUS_IDS

def fmt(ts): return f"<t:{int(ts)}:F>"
def fmt_rel(ts): return f"<t:{int(ts)}:R>"
def now_ts(): return datetime.now(timezone.utc).timestamp()

def parse_duration(s):
    total = 0
    for val, unit in re.findall(r"(\d+)([smhj])", s.lower()):
        total += int(val) * {"s": 1, "m": 60, "h": 3600, "j": 86400}[unit]
    return total

def fmt_duration(seconds):
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

violations = {}
VIOLATION_LIMIT = 2
TIMEOUT_MIN = 1

async def sys_violation(member):
    uid = member.id
    violations[uid] = violations.get(uid, 0) + 1
    if violations[uid] < VIOLATION_LIMIT:
        return "Tu es qui bas staff ? Prochaine fois c'est sanction !"
    violations.pop(uid, None)
    guild = getattr(member, "guild", None)
    try:
        await member.timeout(timedelta(minutes=TIMEOUT_MIN), reason="Tentative de commandes Sys+")
        sanction = f"🔇 Je t'avais prévenu, t'es timeout {TIMEOUT_MIN} minute."
        ok = True
    except:
        sanction = "Je t'avais prévenu... (timeout impossible)"
        ok = False
    if guild:
        e = discord.Embed(title="🔇 Auto-timeout", color=0xFF6600, timestamp=datetime.now(timezone.utc))
        e.add_field(name="👤", value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="📝", value="Tentatives de commandes Sys+", inline=True)
        e.add_field(name="⏱️", value=f"`{TIMEOUT_MIN} min`" if ok else "Échec", inline=True)
        try: await log(guild, e)
        except: pass
    return sanction

async def not_sys_plus(ctx):
    await ctx.reply(await sys_violation(ctx.author))

async def try_dm(user, embed):
    try: await user.send(embed=embed); return True
    except: return False

async def make_invite(guild):
    try:
        channels = [guild.system_channel, guild.rules_channel] + list(guild.text_channels)
        for ch in channels:
            if ch and ch.permissions_for(guild.me).create_instant_invite:
                inv = await ch.create_invite(max_age=0, max_uses=0, unique=False, reason="Invitation de retour")
                return inv.url
    except: pass
    return None

# ════════════════════════════════════════════════════════════════
#  MIDDLEWARE : vérif préfixe + vérif Sys+
# ════════════════════════════════════════════════════════════════
@bot.before_invoke
async def check_prefix_and_sysplus(ctx):
    cmd_name = ctx.command.name if ctx.command else None
    expected = PREFIX_RULES.get(cmd_name)

    # Mauvais préfixe : on ignore silencieusement
    if expected and ctx.prefix != expected:
        raise commands.CheckFailure()

    # Pas Sys+
    if not is_sys_plus(ctx.author.id):
        await not_sys_plus(ctx)
        raise commands.CheckFailure()

# ════════════════════════════════════════════════════════════════
#  EVENTS
# ════════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    await apply_presence()
    if not check_tempbans.is_running(): check_tempbans.start()
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")

@bot.event
async def on_member_join(member):
    uid = str(member.id)
    if uid in blacklist:
        data = blacklist[uid]
        try:
            await member.send(embed=discord.Embed(
                title="🚫 Accès refusé",
                description=f"Tu es blacklisté de ce serveur.\nRaison : {data['raison']}",
                color=0xFF0000))
        except: pass
        await member.ban(reason=f"[Blacklist] {data['raison']}", delete_message_days=0)

# ════════════════════════════════════════════════════════════════
#  TASK : auto-unban tempbans
# ════════════════════════════════════════════════════════════════
@tasks.loop(seconds=30)
async def check_tempbans():
    now = now_ts()
    for uid, data in [(u, d) for u, d in list(tempbans.items()) if d["until"] <= now]:
        guild = bot.get_guild(data["guild_id"])
        if not guild: continue
        try:
            user = await bot.fetch_user(int(uid))
            await guild.unban(user, reason="Tempban expiré")
            invite = await make_invite(guild)
            desc = f"Tu as été débanni de **{guild.name}**.\nTu peux rejoindre à nouveau."
            if invite: desc += f"\n\n🔗 {invite}"
            dm_ok = await try_dm(user, discord.Embed(title="✅ Ban expiré", description=desc, color=0x57F287))
            e = discord.Embed(title="✅ Unban automatique", color=0x57F287, timestamp=datetime.now(timezone.utc))
            e.add_field(name="👤", value=f"`{user}` (`{uid}`)", inline=True)
            e.add_field(name="⏱️ Durée", value=data["duree_str"], inline=True)
            e.add_field(name="📩 MP", value="✅" if dm_ok else "❌", inline=True)
            await log(guild, e)
        except: pass
        tempbans.pop(uid, None)
        save(TEMPBAN_FILE, tempbans)

# ════════════════════════════════════════════════════════════════
#  +bl
# ════════════════════════════════════════════════════════════════
@bot.command(name="bl")
async def bl_cmd(ctx, user_id: str = None, *, raison: str = "Aucune raison"):
    if not user_id: return await ctx.reply("❌ `+bl <id> <raison>`")
    try: uid_int = int(user_id); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply("❌ ID invalide.")
    uid = str(uid_int); now = now_ts()
    blacklist[uid] = {"raison": raison, "by": str(ctx.author), "by_id": ctx.author.id, "at": now}
    save(BL_FILE, blacklist)
    try:
        await user.send(embed=discord.Embed(title="🚫 Tu as été blacklisté",
            description=f"Serveur : {ctx.guild.name}\nRaison : {raison}\nPar : {ctx.author}\nDate : {fmt(now)}\n\nSanction permanente.",
            color=0xFF0000))
    except: pass
    try: await ctx.guild.ban(user, reason=f"[BL] {raison}", delete_message_days=0)
    except discord.Forbidden: return await ctx.reply("❌ Permissions insuffisantes.")
    e = discord.Embed(title="🚫 Blacklist", color=0xFF0000, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{user}` (`{uid_int}`)", inline=True)
    e.add_field(name="🛡️ Par", value=ctx.author.mention, inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.add_field(name="📅", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(description=f"🚫 **{user}** blacklisté.\n📝 {raison}", color=0xFF0000))

# ════════════════════════════════════════════════════════════════
#  +ban
# ════════════════════════════════════════════════════════════════
@bot.command(name="ban")
async def ban_cmd(ctx, user_id: str = None, duree: str = None, *, raison: str = "Aucune raison"):
    if not user_id or not duree: return await ctx.reply("❌ `+ban <id> <durée> <raison>` ex: `+ban 123 1h30m Spam`")
    try: uid_int = int(user_id); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply("❌ ID invalide.")
    seconds = parse_duration(duree)
    if seconds <= 0: return await ctx.reply("❌ Durée invalide. Ex: `1h`, `30m`, `2j`, `1h30m`")
    uid = str(uid_int); now = now_ts(); until = now + seconds; duree_str = fmt_duration(seconds)
    tempbans[uid] = {"raison": raison, "by": str(ctx.author), "by_id": ctx.author.id,
                     "at": now, "until": until, "guild_id": ctx.guild.id, "duree_str": duree_str}
    save(TEMPBAN_FILE, tempbans)
    invite = await make_invite(ctx.guild)
    desc = (f"Serveur : {ctx.guild.name}\nRaison : {raison}\nPar : {ctx.author}\n"
            f"Durée : {duree_str}\nBanni le : {fmt(now)}\nFin : {fmt(until)} ({fmt_rel(until)})\n\n"
            "Tu pourras revenir une fois la durée terminée.")
    if invite: desc += f"\n🔗 {invite}"
    try: await user.send(embed=discord.Embed(title="🔨 Banni temporairement", description=desc, color=0xFF6600))
    except: pass
    try: await ctx.guild.ban(user, reason=f"[Tempban {duree_str}] {raison}", delete_message_days=0)
    except discord.Forbidden: return await ctx.reply("❌ Permissions insuffisantes.")
    e = discord.Embed(title="🔨 Tempban", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{user}` (`{uid_int}`)", inline=True)
    e.add_field(name="🛡️ Par", value=ctx.author.mention, inline=True)
    e.add_field(name="⏱️ Durée", value=f"`{duree_str}`", inline=True)
    e.add_field(name="🔓 Fin", value=f"{fmt(until)}\n{fmt_rel(until)}", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(
        description=f"🔨 **{user}** banni **{duree_str}**.\n📝 {raison}\n🔓 Fin : {fmt(until)}", color=0xFF6600))

# ════════════════════════════════════════════════════════════════
#  -baninfo
# ════════════════════════════════════════════════════════════════
@bot.command(name="baninfo")
async def baninfo_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-baninfo <id>`")
    uid = str(user_id).strip()
    data = tempbans.get(uid)
    if not data: return await ctx.reply(embed=discord.Embed(description="❌ Aucun tempban pour cet ID.", color=0xFF0000))
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    remaining = max(0, data["until"] - now_ts())
    e = discord.Embed(title="🔍 Infos Tempban", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{name}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par", value=data["by"], inline=True)
    e.add_field(name="⏱️ Durée", value=f"`{data['duree_str']}`", inline=True)
    e.add_field(name="📅 Banni le", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    e.add_field(name="🔓 Fin", value=f"{fmt(data['until'])}\n{fmt_rel(data['until'])}", inline=True)
    e.add_field(name="⏳ Reste", value=f"`{fmt_duration(int(remaining))}`", inline=True)
    e.add_field(name="📝 Raison", value=data["raison"], inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)

# ════════════════════════════════════════════════════════════════
#  -blinfo
# ════════════════════════════════════════════════════════════════
@bot.command(name="blinfo")
async def blinfo_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-blinfo <id>`")
    uid = str(user_id).strip(); data = blacklist.get(uid)
    if not data: return await ctx.reply(embed=discord.Embed(description="❌ Aucune blacklist pour cet ID.", color=0xFF0000))
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    e = discord.Embed(title="🔍 Infos Blacklist", color=0xFF0000, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{name}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par", value=data["by"], inline=True)
    e.add_field(name="📅 Date", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    e.add_field(name="📝 Raison", value=data["raison"], inline=False)
    e.set_footer(text="Sanction permanente")
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)

# ════════════════════════════════════════════════════════════════
#  &unbl
# ════════════════════════════════════════════════════════════════
@bot.command(name="unbl")
async def unbl_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `&unbl <id>`")
    uid = str(user_id).strip()
    if uid in flammes: return await ctx.reply("🔥 Cette personne est flammée, utilise `/unflamme`.")
    if uid not in blacklist: return await ctx.reply(embed=discord.Embed(description="❌ Cet ID n'est pas blacklisté.", color=0xFF0000))
    try: user = await bot.fetch_user(int(uid))
    except: return await ctx.reply("❌ ID invalide.")
    try: await ctx.guild.unban(user, reason=f"[UNBL] par {ctx.author}")
    except discord.NotFound: pass
    except discord.Forbidden: return await ctx.reply("❌ Permissions insuffisantes.")
    data = blacklist.pop(uid); save(BL_FILE, blacklist)
    now = now_ts(); invite = await make_invite(ctx.guild)
    desc = f"Ta blacklist sur **{ctx.guild.name}** a été levée."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(title="✅ Blacklist levée", description=desc, color=0x57F287))
    e = discord.Embed(title="✅ UNBL", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{user}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par", value=ctx.author.mention, inline=True)
    e.add_field(name="📩 MP", value="✅" if dm_ok else "❌", inline=True)
    e.add_field(name="📝 Raison initiale", value=data["raison"], inline=False)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(description=f"✅ **{user}** retiré de la blacklist et débanni.", color=0x57F287))

# ════════════════════════════════════════════════════════════════
#  /flamme
# ════════════════════════════════════════════════════════════════
@tree.command(name="flamme", description="Flamme un membre - ban définitif [Sys+]")
@app_commands.describe(user_id="ID Discord", raison="Raison")
async def flamme_slash(i: discord.Interaction, user_id: str, raison: str = "Aucune raison"):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    try: user = await bot.fetch_user(int(user_id))
    except: return await i.response.send_message("❌ ID invalide.", ephemeral=True)
    uid = str(user_id); now = now_ts()
    flammes[uid] = {"raison": raison, "by": str(i.user), "by_id": i.user.id, "at": now}
    blacklist[uid] = {"raison": f"[FLAMME] {raison}", "by": str(i.user), "by_id": i.user.id, "at": now}
    save(FLAMME_FILE, flammes); save(BL_FILE, blacklist)
    try:
        await user.send(embed=discord.Embed(title="🔥 Tu as été flammé",
            description=f"Serveur : {i.guild.name}\nRaison : {raison}\nPar : {i.user}\nDate : {fmt(now)}\n\nSanction permanente et définitive.",
            color=0xFF0000))
    except: pass
    try: await i.guild.ban(user, reason=f"[FLAMME] {raison}", delete_message_days=7)
    except discord.Forbidden: return await i.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
    e = discord.Embed(title="🔥 FLAMME", color=0xE74C3C, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{user}` (`{user_id}`)", inline=True)
    e.add_field(name="🛡️ Par", value=i.user.mention, inline=True)
    e.add_field(name="📅", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    await log(i.guild, e)
    await i.response.send_message(embed=discord.Embed(
        title="🔥 Flamme exécutée",
        description=f"**{user}** flammé.\n📝 {raison}", color=0xE74C3C))

# ════════════════════════════════════════════════════════════════
#  /flamme-info
# ════════════════════════════════════════════════════════════════
@tree.command(name="flamme-info", description="Infos sur une flamme [Sys+]")
@app_commands.describe(user_id="ID Discord")
async def flamme_info(i: discord.Interaction, user_id: str):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    uid = str(user_id).strip(); data = flammes.get(uid)
    if not data: return await i.response.send_message(embed=discord.Embed(description="❌ Aucune flamme pour cet ID.", color=0xFF0000), ephemeral=True)
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    e = discord.Embed(title="🔥 Infos Flamme", color=0xE74C3C, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{name}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par", value=data["by"], inline=True)
    e.add_field(name="📅", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    e.add_field(name="📝 Raison", value=data["raison"], inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    await i.response.send_message(embed=e)

# ════════════════════════════════════════════════════════════════
#  /unflamme
# ════════════════════════════════════════════════════════════════
@tree.command(name="unflamme", description="Retire une flamme [Sys+]")
@app_commands.describe(user_id="ID Discord")
async def unflamme_slash(i: discord.Interaction, user_id: str):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    uid = str(user_id).strip()
    if uid not in flammes: return await i.response.send_message(embed=discord.Embed(description="❌ Aucune flamme pour cet ID.", color=0xFF0000), ephemeral=True)
    try: user = await bot.fetch_user(int(uid))
    except: return await i.response.send_message("❌ ID invalide.", ephemeral=True)
    try: await i.guild.unban(user, reason=f"[UNFLAMME] par {i.user}")
    except discord.NotFound: pass
    except discord.Forbidden: return await i.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
    data = flammes.pop(uid); blacklist.pop(uid, None)
    save(FLAMME_FILE, flammes); save(BL_FILE, blacklist)
    now = now_ts(); invite = await make_invite(i.guild)
    desc = f"Ta flamme sur **{i.guild.name}** a été levée."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(title="✅ Flamme levée", description=desc, color=0x57F287))
    e = discord.Embed(title="✅ UNFLAMME", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤", value=f"`{user}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par", value=i.user.mention, inline=True)
    e.add_field(name="📩 MP", value="✅" if dm_ok else "❌", inline=True)
    e.add_field(name="📝 Raison initiale", value=data["raison"], inline=False)
    await log(i.guild, e)
    await i.response.send_message(embed=discord.Embed(
        title="✅ Flamme retirée", description=f"**{user}** n'est plus flammé.", color=0x57F287))

# ════════════════════════════════════════════════════════════════
#  /unban-all
# ════════════════════════════════════════════════════════════════
@tree.command(name="unban-all", description="Déban tout sauf blacklist et flammes [Sys+]")
async def unban_all_slash(i: discord.Interaction):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    await i.response.defer()
    protected = set(blacklist.keys()) | set(flammes.keys())
    unbanned = skipped = failed = 0
    async for entry in i.guild.bans(limit=None):
        uid = str(entry.user.id)
        if uid in protected: skipped += 1; continue
        try:
            await i.guild.unban(entry.user, reason=f"[UNBAN-ALL] par {i.user}")
            tempbans.pop(uid, None); unbanned += 1
        except: failed += 1
        await asyncio.sleep(0.5)
    save(TEMPBAN_FILE, tempbans)
    now = now_ts()
    e = discord.Embed(title="🔓 UNBAN-ALL", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="🛡️ Par", value=i.user.mention, inline=True)
    e.add_field(name="✅ Débannis", value=str(unbanned), inline=True)
    e.add_field(name="🚫 Ignorés", value=str(skipped), inline=True)
    if failed: e.add_field(name="⚠️ Échecs", value=str(failed), inline=True)
    await log(i.guild, e)
    await i.followup.send(embed=discord.Embed(
        title="🔓 Unban-all terminé",
        description=f"✅ {unbanned} débanni(s)\n🚫 {skipped} ignoré(s)" + (f"\n⚠️ {failed} échec(s)" if failed else ""),
        color=0x57F287))

# ════════════════════════════════════════════════════════════════
#  -banpanel
# ════════════════════════════════════════════════════════════════
PANEL_PER_PAGE = 4
CATS = {
    "tempban": ("🔨", "Tempban",     0xFF6600),
    "bl":      ("🚫", "Blacklist",   0xFF0000),
    "flamme":  ("🔥", "Flamme",      0xE74C3C),
    "manuel":  ("⚖️", "Ban manuel",  0x95A5A6),
}

def cut(text, n=250):
    text = str(text)
    return text if len(text) <= n else text[:n-1] + "…"

async def collect_bans(guild):
    entries = []
    for uid, d in tempbans.items():
        entries.append({"type": "tempban", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in flammes.items():
        entries.append({"type": "flamme", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in blacklist.items():
        if uid in flammes: continue
        entries.append({"type": "bl", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    known = set(tempbans) | set(blacklist) | set(flammes)
    try:
        async for e in guild.bans(limit=None):
            uid = str(e.user.id)
            if uid in known: continue
            entries.append({"type": "manuel", "uid": uid, "data": {"raison": e.reason or "Aucune raison"}, "at": None, "user": e.user})
    except: pass
    entries.sort(key=lambda x: x["at"] or 0, reverse=True)
    return entries

async def entry_name(entry):
    if entry["user"]: return str(entry["user"])
    try: u = await bot.fetch_user(int(entry["uid"])); return str(u)
    except: return "Inconnu"

def entry_value(entry):
    t, uid, d = entry["type"], entry["uid"], entry["data"]
    lines = [f"🆔 `{uid}`"]
    if t == "tempban":
        remaining = max(0, d["until"] - now_ts())
        lines += [f"🛡️ Par : {d['by']}", f"⏱️ Durée : `{d['duree_str']}` - Reste : `{fmt_duration(int(remaining))}`",
                  f"📅 Banni le : {fmt(d['at'])}", f"🔓 Fin : {fmt(d['until'])} ({fmt_rel(d['until'])})", f"📝 {cut(d['raison'])}"]
    elif t in ("bl", "flamme"):
        lines += [f"🛡️ Par : {d['by']}", f"📅 {fmt(d['at'])} ({fmt_rel(d['at'])})", f"📝 {cut(d['raison'])}", "♾️ Permanent" + (" - IP signalée" if t == "flamme" else "")]
    else:
        lines += [f"📝 {cut(d['raison'])}", "ℹ️ Ban manuel"]
    return "\n".join(lines)[:1024]

class BanPanel(discord.ui.View):
    def __init__(self, author_id, entries):
        super().__init__(timeout=180)
        self.author_id = author_id; self.entries = entries; self.filter = "all"; self.page = 0; self.message = None

    def filtered(self):
        return self.entries if self.filter == "all" else [e for e in self.entries if e["type"] == self.filter]

    def total_pages(self): return max(1, -(-len(self.filtered()) // PANEL_PER_PAGE))

    async def build(self):
        items = self.filtered(); pages = self.total_pages()
        self.page = max(0, min(self.page, pages - 1))
        chunk = items[self.page * PANEL_PER_PAGE:(self.page + 1) * PANEL_PER_PAGE]
        counts = {k: sum(1 for e in self.entries if e["type"] == k) for k in CATS}
        e = discord.Embed(title="🛡️ Panel des bans",
            description=f"**Total : {len(self.entries)}**\n🔨 Tempbans : `{counts['tempban']}` - 🚫 Blacklist : `{counts['bl']}`\n🔥 Flammes : `{counts['flamme']}` - ⚖️ Bans manuels : `{counts['manuel']}`",
            color=0x5865F2, timestamp=datetime.now(timezone.utc))
        if not chunk: e.add_field(name="Aucun résultat", value="Aucun ban dans cette catégorie.", inline=False)
        for en in chunk:
            emoji, label, _ = CATS[en["type"]]
            name = await entry_name(en)
            e.add_field(name=f"{emoji} {label} - {name}"[:256], value=entry_value(en), inline=False)
        filt = "Tous" if self.filter == "all" else CATS[self.filter][1]
        e.set_footer(text=f"Filtre : {filt} - Page {self.page + 1}/{pages}")
        return e

    async def interaction_check(self, i):
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True); return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

    @discord.ui.select(placeholder="Filtrer par type…", options=[
        discord.SelectOption(label="Tous", value="all", emoji="📋"),
        discord.SelectOption(label="Tempbans", value="tempban", emoji="🔨"),
        discord.SelectOption(label="Blacklist", value="bl", emoji="🚫"),
        discord.SelectOption(label="Flammes", value="flamme", emoji="🔥"),
        discord.SelectOption(label="Bans manuels", value="manuel", emoji="⚖️"),
    ])
    async def filter_select(self, i, select):
        self.filter = select.values[0]; self.page = 0
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, i, b):
        self.page = (self.page - 1) % self.total_pages()
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, i, b):
        self.page = (self.page + 1) % self.total_pages()
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="🔄 Actualiser", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, i, b):
        self.entries = await collect_bans(i.guild)
        await i.response.edit_message(embed=await self.build(), view=self)

@bot.command(name="banpanel")
async def banpanel_cmd(ctx):
    msg = await ctx.reply("⏳ Chargement…")
    entries = await collect_bans(ctx.guild)
    view = BanPanel(ctx.author.id, entries); view.message = msg
    await msg.edit(content=None, embed=await view.build(), view=view)

# ════════════════════════════════════════════════════════════════
#  -maintenance
# ════════════════════════════════════════════════════════════════
@bot.command(name="maintenance")
async def maintenance_cmd(ctx, mode: str = None):
    global maintenance
    if mode and mode.lower() in ("on", "oui", "1"): maintenance = True
    elif mode and mode.lower() in ("off", "non", "0"): maintenance = False
    else: maintenance = not maintenance
    await apply_presence()
    if maintenance:
        await ctx.reply(embed=discord.Embed(title="🔧 Maintenance ON", description="Bot en Ne pas déranger.", color=0xED4245))
    else:
        await ctx.reply(embed=discord.Embed(title="✅ Maintenance OFF", description="Bot de nouveau en ligne.", color=0x57F287))
    e = discord.Embed(title="🔧 Maintenance " + ("ON" if maintenance else "OFF"),
        color=0xED4245 if maintenance else 0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="🛡️ Par", value=ctx.author.mention)
    await log(ctx.guild, e)

# ════════════════════════════════════════════════════════════════
#  -help
# ════════════════════════════════════════════════════════════════
@bot.command(name="help")
async def help_cmd(ctx):
    e = discord.Embed(title="📖 Aide - Commandes Sys+",
        description="Toutes les commandes sont réservées aux **Sys+**.", color=0x5865F2,
        timestamp=datetime.now(timezone.utc))
    e.add_field(name="🚫 Blacklist", value="`+bl <id> <raison>` - Blacklist + ban permanent\n`&unbl <id>` - Retire une blacklist\n`-blinfo <id>` - Infos sur une blacklist", inline=False)
    e.add_field(name="🔨 Tempban", value="`+ban <id> <durée> <raison>` - Ban temporaire\nDurées : `s`, `m`, `h`, `j` (ex: `1h30m`)\n`-baninfo <id>` - Infos sur un tempban", inline=False)
    e.add_field(name="🔥 Flamme", value="`/flamme <id> <raison>` - Ban définitif\n`/flamme-info <id>` - Infos\n`/unflamme <id>` - Retire une flamme", inline=False)
    e.add_field(name="🔓 Unban", value="`/unban-all` - Déban tout sauf BL et flammes", inline=False)
    e.add_field(name="🛡️ Panel", value="`-banpanel` - Liste de tous les bans", inline=False)
    e.add_field(name="🔧 Maintenance", value="`-maintenance [on|off]` - Mode maintenance", inline=False)
    e.set_footer(text=f"Demandé par {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=e)

# ════════════════════════════════════════════════════════════════
#  LANCEMENT
# ════════════════════════════════════════════════════════════════
bot.run(os.environ["TOKEN"])
