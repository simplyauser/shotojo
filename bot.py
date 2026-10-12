import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import re
from datetime import datetime, timezone, timedelta

# ════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════
SYS_PLUS_IDS         = {1419320803199029402, 1514099294611701842}
CONTRIBUTOR_ROLE_IDS = {1556148445041926174}   # Pétale — ajouter les IDs supérieurs ici
GUILD_ID             = int(os.getenv("GUILD_ID"))
LOGS_ID              = int(os.getenv("LOGS_CHANNEL_ID", "0"))
MUTED_ROLE_ID        = 1558626042812301394
SUPPORT_CONTACT_ID   = 1419320803199029402  # Contact en attendant le serveur Support

BL_FILE        = "blacklist.json"
TEMPBAN_FILE   = "tempbans.json"
TEMPETE_FILE   = "tempetes.json"
SANCTIONS_FILE = "sanctions.json"

MUTE_REASONS = {
    "Propos déplacés": {"emoji": "🤐", "durees": ["10min", "30min", "1h"]},
    "Insultes":        {"emoji": "🤬", "durees": ["30min", "1h", "3h"]},
    "Spam":            {"emoji": "📢", "durees": ["10min", "30min", "1h"]},
    "Troll":           {"emoji": "🤡", "durees": ["30min", "1h", "6h"]},
    "Soundboard":      {"emoji": "🔊", "durees": ["10min", "30min"]},
    "Discrimination":  {"emoji": "⚠️", "durees": ["1h", "3h", "24h"]},
    "Double compte":   {"emoji": "👥", "durees": ["30min", "1h", "3h"]},
    "Pub":             {"emoji": "📣", "durees": ["1h", "3h", "24h"]},
}

CONTRIBUTOR_CMDS = {"tempmute", "warn", "unmute", "sanction", "infosanction"}
PUBLIC_CMDS      = {"help"}

PREFIX_RULES = {
    "bl":           "+",
    "ban":          "+",
    "unbl":         "&",
    "baninfo":      "-",
    "blinfo":       "-",
    "banpanel":     "-",
    "maintenance":  "-",
    "help":         "-",
    "tempmute":     "-",
    "warn":         "-",
    "unmute":       "-",
    "sanction":     "-",
    "infosanction": "-",
    "delsanction":  "-",
}

# ════════════════════════════════════════════════
# STORAGE
# ════════════════════════════════════════════════
def load(file):
    if os.path.exists(file):
        try:
            with open(file) as f: return json.load(f)
        except: pass
    return {}

def save(file, data):
    with open(file, "w") as f: json.dump(data, f, indent=2)

blacklist    = load(BL_FILE)
tempbans     = load(TEMPBAN_FILE)
tempetes     = load(TEMPETE_FILE)
sanctions_db = load(SANCTIONS_FILE) or {"next_id": 1, "sanctions": {}}
if "next_id"   not in sanctions_db: sanctions_db["next_id"]   = 1
if "sanctions" not in sanctions_db: sanctions_db["sanctions"] = {}

def save_sanctions():
    save(SANCTIONS_FILE, sanctions_db)

def add_sanction(user_id, type_, raison, by, by_id, at, **kwargs):
    sid = str(sanctions_db["next_id"])
    sanctions_db["next_id"] += 1
    entry = {"id": int(sid), "user_id": str(user_id), "type": type_,
              "raison": raison, "by": by, "by_id": by_id, "at": at, "active": True}
    entry.update(kwargs)
    sanctions_db["sanctions"][sid] = entry
    save_sanctions()
    return int(sid)

def get_user_sanctions(user_id):
    uid = str(user_id)
    return sorted([s for s in sanctions_db["sanctions"].values() if s["user_id"] == uid],
                  key=lambda x: x["at"])

def get_sanction(sid):
    return sanctions_db["sanctions"].get(str(sid))

# ════════════════════════════════════════════════
# BOT
# ════════════════════════════════════════════════
async def get_prefix(bot, message): return ["+", "-", "&"]

def make_activity():
    return discord.Activity(type=discord.ActivityType.watching,
                            name="Shotojo 🌸 #🇯🇵", state="Nous vous préparons de grandes choses")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None,
                   status=discord.Status.online, activity=make_activity())
tree        = bot.tree
maintenance = False

async def apply_presence():
    if maintenance:
        await bot.change_presence(status=discord.Status.dnd,
                                  activity=discord.Game(name="🔧 Maintenance en cours"))
    else:
        await bot.change_presence(status=discord.Status.online, activity=make_activity())

# ════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════
def is_sys_plus(uid): return uid in SYS_PLUS_IDS

def is_petale_or_plus(member):
    if is_sys_plus(member.id): return True
    if not hasattr(member, "roles"): return False
    return any(r.id in CONTRIBUTOR_ROLE_IDS for r in member.roles)

def fmt(ts):     return f"<t:{int(ts)}:F>"
def fmt_rel(ts): return f"<t:{int(ts)}:R>"
def now_ts():    return datetime.now(timezone.utc).timestamp()

def parse_duration(s):
    total = 0
    for val, unit in re.findall(r"(\d+)([smhj])", s.lower()):
        total += int(val) * {"s": 1, "m": 60, "h": 3600, "j": 86400}[unit]
    return total

def parse_dur_str(s):
    m = re.match(r"^(\d+)(min|h|j)$", s)
    if not m: return 0
    val, unit = int(m.group(1)), m.group(2)
    return val * {"min": 60, "h": 3600, "j": 86400}[unit]

def fmt_duration(seconds):
    j, r = divmod(seconds, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
    parts = []
    if j: parts.append(f"{j}j")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}min")
    if s: parts.append(f"{s}s")
    return " ".join(parts) or "0s"

def cut(text, n=250):
    text = str(text); return text if len(text) <= n else text[:n-1] + "…"

async def log(guild, embed):
    if not LOGS_ID: return
    ch = guild.get_channel(LOGS_ID)
    if ch: await ch.send(embed=embed)

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

def dm_footer_sanctions():
    return f"Pour toute contestation, envoie un MP à <@{SUPPORT_CONTACT_ID}> en attendant l'ouverture du serveur Support."

# ════════════════════════════════════════════════
# VIOLATIONS (commandes non autorisées)
# ════════════════════════════════════════════════
async def sys_violation(member):
    """Timeout immédiat dès la première tentative de commande non autorisée."""
    try:
        await member.timeout(timedelta(minutes=1), reason="Tentative de commande non autorisée")
        msg = "🔇 Accès refusé. Tu viens d'être timeout 1 minute."
        ok  = True
    except:
        msg = "🔇 Accès refusé."
        ok  = False
    guild = getattr(member, "guild", None)
    if guild:
        e = discord.Embed(
            title="🔇 Timeout automatique",
            description=f"{member.mention} a tenté d'utiliser une commande non autorisée.",
            color=0xFF4500,
            timestamp=datetime.now(timezone.utc))
        e.add_field(name="👤 Membre",  value=f"{member.mention}\n`{member.id}`", inline=True)
        e.add_field(name="⏱️ Durée",  value="`1 minute`" if ok else "Échec timeout", inline=True)
        e.add_field(name="📋 Raison", value="Tentative de commande non autorisée", inline=False)
        try: await log(guild, e)
        except: pass
    return msg

async def not_sys_plus(ctx):
    await ctx.reply(await sys_violation(ctx.author))

# ════════════════════════════════════════════════
# MIDDLEWARE
# ════════════════════════════════════════════════
@bot.before_invoke
async def check_prefix_and_perms(ctx):
    cmd_name = ctx.command.name if ctx.command else None
    expected = PREFIX_RULES.get(cmd_name)
    if expected and ctx.prefix != expected:
        raise commands.CheckFailure()
    if cmd_name in PUBLIC_CMDS:
        return
    if cmd_name in CONTRIBUTOR_CMDS:
        if not is_petale_or_plus(ctx.author):
            await ctx.reply("❌ Tu n'as pas les permissions nécessaires.")
            raise commands.CheckFailure()
        return
    if not is_sys_plus(ctx.author.id):
        await not_sys_plus(ctx)
        raise commands.CheckFailure()

# ════════════════════════════════════════════════
# EVENTS
# ════════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    await apply_presence()
    if not check_tempbans.is_running(): check_tempbans.start()
    if not check_mutes.is_running():    check_mutes.start()
    print(f"✅ {bot.user} connecté (ID: {bot.user.id})")

@bot.event
async def on_member_join(member):
    uid = str(member.id)
    if uid in blacklist:
        data = blacklist[uid]
        try:
            await member.send(embed=discord.Embed(
                title="🚫 Accès refusé — Shotojo",
                description=(
                    f"Tu es blacklisté(e) de **Shotojo**.\n"
                    f"**Raison :** {data['raison']}\n\n"
                    f"Il s'agit d'un ban IP définitif.\n\n"
                    f"{dm_footer_sanctions()}"
                ),
                color=0xFF0000))
        except: pass
        await member.ban(reason=f"[Blacklist — Ban IP] {data['raison']}", delete_message_days=0)

# ════════════════════════════════════════════════
# TASKS
# ════════════════════════════════════════════════
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
            desc = (
                f"Ton ban temporaire sur **{guild.name}** est expiré.\n"
                f"Tu peux désormais rejoindre le serveur."
            )
            if invite: desc += f"\n\n🔗 {invite}"
            dm_ok = await try_dm(user, discord.Embed(
                title="✅ Ban expiré — Shotojo",
                description=desc,
                color=0x57F287,
                timestamp=datetime.now(timezone.utc)))
            e = discord.Embed(title="✅ Unban automatique", color=0x57F287, timestamp=datetime.now(timezone.utc))
            e.add_field(name="👤 Membre", value=f"`{user}` (`{uid}`)", inline=True)
            e.add_field(name="⏱️ Durée", value=f"`{data['duree_str']}`", inline=True)
            e.add_field(name="📩 MP",     value="✅" if dm_ok else "❌", inline=True)
            await log(guild, e)
        except: pass
        tempbans.pop(uid, None)
        save(TEMPBAN_FILE, tempbans)

@tasks.loop(minutes=1)
async def check_mutes():
    now = now_ts(); changed = False
    guild = bot.get_guild(GUILD_ID)
    for sid, s in list(sanctions_db["sanctions"].items()):
        if s["type"] == "tempmute" and s.get("active") and s.get("until", 0) <= now:
            sanctions_db["sanctions"][sid]["active"] = False
            changed = True
            if guild:
                try:
                    member = guild.get_member(int(s["user_id"])) or await guild.fetch_member(int(s["user_id"]))
                    muted_role = guild.get_role(MUTED_ROLE_ID)
                    if muted_role and muted_role in member.roles:
                        await member.remove_roles(muted_role, reason="Mute expiré automatiquement")
                except: pass
    if changed: save_sanctions()

# ════════════════════════════════════════════════
# PANEL VIEWS
# ════════════════════════════════════════════════
class MuteReasonView(discord.ui.View):
    def __init__(self, author_id, target):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target    = target
        self.message   = None

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True); return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

    @discord.ui.select(
        placeholder="Choisir une raison...",
        options=[discord.SelectOption(label=r, value=r, emoji=d["emoji"]) for r, d in MUTE_REASONS.items()]
    )
    async def reason_select(self, i: discord.Interaction, select: discord.ui.Select):
        raison = select.values[0]
        view   = MuteDurationView(self.author_id, self.target, raison)
        view.message = self.message
        e = discord.Embed(
            title=f"🔇 Tempmute — {self.target.display_name}",
            description=f"**Raison sélectionnée :** {raison}\n\nChoisis la durée :",
            color=0xFF6600,
            timestamp=datetime.now(timezone.utc))
        e.set_thumbnail(url=self.target.display_avatar.url)
        await i.response.edit_message(embed=e, view=view)


class DurationButton(discord.ui.Button):
    def __init__(self, duree, raison, author_id, target):
        super().__init__(label=duree, style=discord.ButtonStyle.primary)
        self.duree = duree; self.raison = raison
        self.author_id = author_id; self.target = target

    async def callback(self, i: discord.Interaction):
        if i.user.id != self.author_id:
            return await i.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True)
        await apply_tempmute(i, self.target, self.raison, self.duree)


class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Annuler", style=discord.ButtonStyle.danger)

    async def callback(self, i: discord.Interaction):
        await i.response.edit_message(content="❌ Annulé.", embed=None, view=None)


class MuteDurationView(discord.ui.View):
    def __init__(self, author_id, target, raison):
        super().__init__(timeout=60)
        self.author_id = author_id; self.target = target; self.raison = raison; self.message = None
        for duree in MUTE_REASONS[raison]["durees"]:
            self.add_item(DurationButton(duree, raison, author_id, target))
        self.add_item(CancelButton())

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True); return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass


class WarnReasonView(discord.ui.View):
    def __init__(self, author_id, target):
        super().__init__(timeout=60)
        self.author_id = author_id; self.target = target; self.message = None

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True); return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

    @discord.ui.select(
        placeholder="Choisir une raison...",
        options=[discord.SelectOption(label=r, value=r, emoji=d["emoji"]) for r, d in MUTE_REASONS.items()]
    )
    async def reason_select(self, i: discord.Interaction, select: discord.ui.Select):
        await apply_warn(i, self.target, select.values[0])

# ════════════════════════════════════════════════
# APPLY FUNCTIONS
# ════════════════════════════════════════════════
async def apply_tempmute(i: discord.Interaction, member: discord.Member, raison: str, duree_str: str):
    seconds = parse_dur_str(duree_str)
    now = now_ts(); until = now + seconds

    muted_role = i.guild.get_role(MUTED_ROLE_ID)
    if not muted_role:
        return await i.response.edit_message(
            content="❌ Rôle Muted introuvable. Vérifie l'ID dans la config.", embed=None, view=None)
    try:
        await member.add_roles(muted_role, reason=f"[Mute] {raison}")
    except discord.Forbidden:
        return await i.response.edit_message(content="❌ Permissions insuffisantes.", embed=None, view=None)
    except Exception as exc:
        return await i.response.edit_message(content=f"❌ Erreur : {exc}", embed=None, view=None)

    sid = add_sanction(user_id=str(member.id), type_="tempmute", raison=raison,
                       duree_str=duree_str, duree_s=seconds, until=until,
                       by=str(i.user), by_id=i.user.id, at=now)

    dm_e = discord.Embed(
        title="🔇 Tu as été réduit(e) au silence — Shotojo",
        color=0xFF6600,
        timestamp=datetime.now(timezone.utc))
    dm_e.add_field(name="📋 Raison",   value=raison, inline=False)
    dm_e.add_field(name="⏱️ Durée",   value=f"`{duree_str}`", inline=True)
    dm_e.add_field(name="🔓 Fin",      value=fmt(until), inline=True)
    dm_e.add_field(name="📅 Appliqué", value=fmt(now), inline=True)
    dm_e.add_field(name="📩 Contact",  value=dm_footer_sanctions(), inline=False)
    dm_ok = await try_dm(member, dm_e)

    log_e = discord.Embed(title="🔇 Tempmute", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    log_e.add_field(name="👤 Membre",    value=f"{member.mention}\n`{member.id}`", inline=True)
    log_e.add_field(name="🛡️ Par",      value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    log_e.add_field(name="⏱️ Durée",    value=f"`{duree_str}`", inline=True)
    log_e.add_field(name="📅 Appliqué", value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    log_e.add_field(name="🔓 Fin",       value=f"{fmt(until)}\n{fmt_rel(until)}", inline=True)
    log_e.add_field(name="📩 MP",        value="✅" if dm_ok else "❌", inline=True)
    log_e.add_field(name="📝 Raison",    value=raison, inline=False)
    log_e.add_field(name="🆔 Sanction", value=f"`#{sid}`", inline=True)
    log_e.set_thumbnail(url=member.display_avatar.url)
    await log(i.guild, log_e)

    result_e = discord.Embed(
        title="✅ Mute appliqué",
        color=0xFF6600,
        timestamp=datetime.now(timezone.utc))
    result_e.add_field(name="👤 Membre",   value=f"{member.mention} (`{member.id}`)", inline=False)
    result_e.add_field(name="📝 Raison",   value=raison, inline=False)
    result_e.add_field(name="⏱️ Durée",   value=f"`{duree_str}`", inline=True)
    result_e.add_field(name="🔓 Fin",      value=fmt(until), inline=True)
    result_e.add_field(name="🆔 Sanction", value=f"`#{sid}`", inline=True)
    result_e.set_thumbnail(url=member.display_avatar.url)
    await i.response.edit_message(embed=result_e, view=None)


async def apply_warn(i: discord.Interaction, member: discord.Member, raison: str):
    now = now_ts()
    sid = add_sanction(user_id=str(member.id), type_="warn", raison=raison,
                       by=str(i.user), by_id=i.user.id, at=now)

    dm_e = discord.Embed(
        title="⚠️ Tu as reçu un avertissement — Shotojo",
        color=0xFFC107,
        timestamp=datetime.now(timezone.utc))
    dm_e.add_field(name="📋 Raison",  value=raison, inline=False)
    dm_e.add_field(name="📅 Date",    value=fmt(now), inline=True)
    dm_e.add_field(name="📩 Contact", value=dm_footer_sanctions(), inline=False)
    dm_ok = await try_dm(member, dm_e)

    log_e = discord.Embed(title="⚠️ Warn", color=0xFFC107, timestamp=datetime.now(timezone.utc))
    log_e.add_field(name="👤 Membre",    value=f"{member.mention}\n`{member.id}`", inline=True)
    log_e.add_field(name="🛡️ Par",      value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    log_e.add_field(name="📅 Date",      value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    log_e.add_field(name="📝 Raison",    value=raison, inline=False)
    log_e.add_field(name="📩 MP",        value="✅" if dm_ok else "❌", inline=True)
    log_e.add_field(name="🆔 Sanction", value=f"`#{sid}`", inline=True)
    log_e.set_thumbnail(url=member.display_avatar.url)
    await log(i.guild, log_e)

    result_e = discord.Embed(
        title="✅ Warn appliqué",
        color=0xFFC107,
        timestamp=datetime.now(timezone.utc))
    result_e.add_field(name="👤 Membre",   value=f"{member.mention} (`{member.id}`)", inline=False)
    result_e.add_field(name="📝 Raison",   value=raison, inline=False)
    result_e.add_field(name="📅 Date",     value=fmt(now), inline=True)
    result_e.add_field(name="🆔 Sanction", value=f"`#{sid}`", inline=True)
    result_e.set_thumbnail(url=member.display_avatar.url)
    await i.response.edit_message(embed=result_e, view=None)

# ════════════════════════════════════════════════
# BAN PANEL
# ════════════════════════════════════════════════
PANEL_PER_PAGE = 4
CATS = {
    "tempban": ("🔨", "Tempban",    0xFF6600),
    "bl":      ("🚫", "Blacklist",  0xFF0000),
    "tempete": ("🌪️", "Tempête",   0xE74C3C),
    "manuel":  ("⚖️", "Ban manuel", 0x95A5A6),
}

async def collect_bans(guild):
    entries = []
    for uid, d in tempbans.items():
        entries.append({"type": "tempban", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in tempetes.items():
        entries.append({"type": "tempete", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in blacklist.items():
        if uid in tempetes: continue
        entries.append({"type": "bl", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    known = set(tempbans) | set(blacklist) | set(tempetes)
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
        lines += [
            f"🛡️ Par : <@{d['by_id']}> (`{d['by_id']}`)",
            f"⏱️ Durée : `{d['duree_str']}` — Reste : `{fmt_duration(int(remaining))}`",
            f"📅 Banni le : {fmt(d['at'])}",
            f"🔓 Fin : {fmt(d['until'])} ({fmt_rel(d['until'])})",
            f"📝 {cut(d['raison'])}",
        ]
    elif t in ("bl", "tempete"):
        lines += [
            f"🛡️ Par : <@{d['by_id']}> (`{d['by_id']}`)",
            f"📅 {fmt(d['at'])} ({fmt_rel(d['at'])})",
            f"📝 {cut(d['raison'])}",
            f"♾️ Permanent — Ban IP",
        ]
    else:
        lines += [f"📝 {cut(d['raison'])}", "ℹ️ Ban manuel"]
    return "\n".join(lines)[:1024]


class BanPanel(discord.ui.View):
    def __init__(self, author_id, entries):
        super().__init__(timeout=180)
        self.author_id = author_id; self.entries = entries
        self.filter = "all"; self.page = 0; self.message = None

    def filtered(self):
        return self.entries if self.filter == "all" else [e for e in self.entries if e["type"] == self.filter]

    def total_pages(self): return max(1, -(-len(self.filtered()) // PANEL_PER_PAGE))

    async def build(self):
        items = self.filtered(); pages = self.total_pages()
        self.page = max(0, min(self.page, pages - 1))
        chunk  = items[self.page * PANEL_PER_PAGE:(self.page + 1) * PANEL_PER_PAGE]
        counts = {k: sum(1 for e in self.entries if e["type"] == k) for k in CATS}
        e = discord.Embed(
            title="🛡️ Panel des bans — Shotojo",
            description=(
                f"**Total : {len(self.entries)} ban(s)**\n"
                f"🔨 Tempbans : `{counts['tempban']}` · 🚫 Blacklist : `{counts['bl']}`\n"
                f"🌪️ Tempêtes : `{counts['tempete']}` · ⚖️ Bans manuels : `{counts['manuel']}`"
            ),
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc))
        if not chunk:
            e.add_field(name="Aucun résultat", value="Aucun ban dans cette catégorie.", inline=False)
        for en in chunk:
            emoji, label, _ = CATS[en["type"]]
            name = await entry_name(en)
            e.add_field(name=f"{emoji} {label} — {name}"[:256], value=entry_value(en), inline=False)
        filt = "Tous" if self.filter == "all" else CATS[self.filter][1]
        e.set_footer(text=f"Filtre : {filt} · Page {self.page + 1}/{pages}")
        return e

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("❌ Ce panel n'est pas à toi.", ephemeral=True); return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except: pass

    @discord.ui.select(placeholder="Filtrer par type…", options=[
        discord.SelectOption(label="Tous",         value="all",     emoji="📋"),
        discord.SelectOption(label="Tempbans",     value="tempban", emoji="🔨"),
        discord.SelectOption(label="Blacklist",    value="bl",      emoji="🚫"),
        discord.SelectOption(label="Tempêtes",     value="tempete", emoji="🌪️"),
        discord.SelectOption(label="Bans manuels", value="manuel",  emoji="⚖️"),
    ])
    async def filter_select(self, i: discord.Interaction, select: discord.ui.Select):
        self.filter = select.values[0]; self.page = 0
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, i: discord.Interaction, b: discord.ui.Button):
        self.page = (self.page - 1) % self.total_pages()
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, i: discord.Interaction, b: discord.ui.Button):
        self.page = (self.page + 1) % self.total_pages()
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="🔄 Actualiser", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, i: discord.Interaction, b: discord.ui.Button):
        self.entries = await collect_bans(i.guild)
        await i.response.edit_message(embed=await self.build(), view=self)

# ════════════════════════════════════════════════
# COMMANDS — Sys+
# ════════════════════════════════════════════════

# +bl
@bot.command(name="bl")
async def bl_cmd(ctx, user_id: str = None, *, raison: str = "Aucune raison"):
    if not user_id: return await ctx.reply("❌ `+bl <id> <raison>`")
    try: uid_int = int(user_id); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply("❌ ID invalide.")
    uid = str(uid_int); now = now_ts()
    blacklist[uid] = {"raison": raison, "by": str(ctx.author), "by_id": ctx.author.id, "at": now}
    save(BL_FILE, blacklist)
    dm_e = discord.Embed(
        title="🚫 Tu as été blacklisté(e) — Shotojo",
        color=0xFF0000,
        timestamp=datetime.now(timezone.utc))
    dm_e.add_field(name="📋 Raison",  value=raison, inline=False)
    dm_e.add_field(name="📅 Date",    value=fmt(now), inline=True)
    dm_e.add_field(name="🌐 Type",    value="Ban IP permanent", inline=True)
    dm_e.add_field(name="📩 Contact", value=dm_footer_sanctions(), inline=False)
    try: await user.send(embed=dm_e)
    except: pass
    try: await ctx.guild.ban(user, reason=f"[BL — Ban IP] {raison}", delete_message_days=0)
    except discord.Forbidden: return await ctx.reply("❌ Permissions insuffisantes.")

    e = discord.Embed(title="🚫 Blacklist — Ban IP", color=0xFF0000, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre", value=f"`{user}` (`{uid_int}`)", inline=True)
    e.add_field(name="🛡️ Par",   value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    e.add_field(name="🌐 Type",   value="Ban IP permanent", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=user.display_avatar.url)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(
        description=f"🚫 **{user}** (`{uid_int}`) blacklisté · Ban IP\n📝 {raison}",
        color=0xFF0000))


# +ban
@bot.command(name="ban")
async def ban_cmd(ctx, user_id: str = None, duree: str = None, *, raison: str = "Aucune raison"):
    if not user_id or not duree:
        return await ctx.reply("❌ `+ban <id> <durée> <raison>` · ex: `+ban 123456789 1h30m Spam`")
    try: uid_int = int(user_id); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply("❌ ID invalide.")
    seconds = parse_duration(duree)
    if seconds <= 0: return await ctx.reply("❌ Durée invalide. Ex: `1h`, `30m`, `2j`")
    uid = str(uid_int); now = now_ts(); until = now + seconds; duree_str = fmt_duration(seconds)
    tempbans[uid] = {"raison": raison, "by": str(ctx.author), "by_id": ctx.author.id,
                     "at": now, "until": until, "guild_id": ctx.guild.id, "duree_str": duree_str}
    save(TEMPBAN_FILE, tempbans)

    dm_e = discord.Embed(
        title="🔨 Tu as été banni(e) temporairement — Shotojo",
        color=0xFF6600,
        timestamp=datetime.now(timezone.utc))
    dm_e.add_field(name="📋 Raison",   value=raison, inline=False)
    dm_e.add_field(name="⏱️ Durée",   value=f"`{duree_str}`", inline=True)
    dm_e.add_field(name="📅 Banni le", value=fmt(now), inline=True)
    dm_e.add_field(name="🔓 Fin",      value=f"{fmt(until)} ({fmt_rel(until)})", inline=True)
    dm_e.add_field(name="📩 Contact",  value=dm_footer_sanctions(), inline=False)
    try: await user.send(embed=dm_e)
    except: pass

    try: await ctx.guild.ban(user, reason=f"[Tempban {duree_str}] {raison}", delete_message_days=0)
    except discord.Forbidden: return await ctx.reply("❌ Permissions insuffisantes.")

    e = discord.Embed(title="🔨 Tempban", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre",  value=f"`{user}` (`{uid_int}`)", inline=True)
    e.add_field(name="🛡️ Par",    value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    e.add_field(name="⏱️ Durée", value=f"`{duree_str}`", inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    e.add_field(name="🔓 Fin",    value=f"{fmt(until)}\n{fmt_rel(until)}", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=user.display_avatar.url)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(
        description=f"🔨 **{user}** banni **{duree_str}**\n📝 {raison}\n🔓 Fin : {fmt(until)}",
        color=0xFF6600))


# -baninfo
@bot.command(name="baninfo")
async def baninfo_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-baninfo <id>`")
    uid = str(user_id).strip(); data = tempbans.get(uid)
    if not data:
        return await ctx.reply(embed=discord.Embed(description="❌ Aucun tempban pour cet ID.", color=0xFF0000))
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    remaining = max(0, data["until"] - now_ts())
    e = discord.Embed(title="🔍 Infos Tempban", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre",    value=f"`{name}`\n`{uid}`", inline=True)
    e.add_field(name="🛡️ Par",      value=f"<@{data['by_id']}>\n`{data['by_id']}`", inline=True)
    e.add_field(name="⏱️ Durée",    value=f"`{data['duree_str']}`", inline=True)
    e.add_field(name="📅 Banni le", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    e.add_field(name="🔓 Fin",       value=f"{fmt(data['until'])}\n{fmt_rel(data['until'])}", inline=True)
    e.add_field(name="⏳ Reste",     value=f"`{fmt_duration(int(remaining))}`", inline=True)
    e.add_field(name="📝 Raison",    value=data["raison"], inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)


# -blinfo
@bot.command(name="blinfo")
async def blinfo_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-blinfo <id>`")
    uid = str(user_id).strip(); data = blacklist.get(uid)
    if not data:
        return await ctx.reply(embed=discord.Embed(description="❌ Aucune blacklist pour cet ID.", color=0xFF0000))
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    e = discord.Embed(title="🔍 Infos Blacklist — Ban IP", color=0xFF0000, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre", value=f"`{name}`\n`{uid}`", inline=True)
    e.add_field(name="🛡️ Par",   value=f"<@{data['by_id']}>\n`{data['by_id']}`", inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    e.add_field(name="🌐 Type",   value="Ban IP permanent", inline=True)
    e.add_field(name="📝 Raison", value=data["raison"], inline=False)
    e.set_footer(text="Sanction permanente — Ban IP")
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)


# &unbl
@bot.command(name="unbl")
async def unbl_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `&unbl <id>`")
    uid = str(user_id).strip()
    if uid in tempetes:
        return await ctx.reply("🌪️ Cette personne est sous tempête, utilise `/untempete`.")
    if uid not in blacklist:
        return await ctx.reply(embed=discord.Embed(description="❌ Cet ID n'est pas blacklisté.", color=0xFF0000))
    try: user = await bot.fetch_user(int(uid))
    except: return await ctx.reply("❌ ID invalide.")
    try: await ctx.guild.unban(user, reason=f"[UNBL] par {ctx.author}")
    except discord.NotFound: pass
    except discord.Forbidden: return await ctx.reply("❌ Permissions insuffisantes.")
    data = blacklist.pop(uid); save(BL_FILE, blacklist)
    invite = await make_invite(ctx.guild)
    desc = f"Ta blacklist sur **{ctx.guild.name}** a été levée.\nTu peux désormais rejoindre à nouveau le serveur."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(
        title="✅ Blacklist levée — Shotojo",
        description=desc,
        color=0x57F287,
        timestamp=datetime.now(timezone.utc)))
    e = discord.Embed(title="✅ Unbl", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre",          value=f"`{user}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par",            value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    e.add_field(name="📩 MP",              value="✅" if dm_ok else "❌", inline=True)
    e.add_field(name="📝 Raison initiale", value=data["raison"], inline=False)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(
        description=f"✅ **{user}** retiré de la blacklist et débanni.",
        color=0x57F287))


# -banpanel
@bot.command(name="banpanel")
async def banpanel_cmd(ctx):
    msg = await ctx.reply("⏳ Chargement…")
    entries = await collect_bans(ctx.guild)
    view = BanPanel(ctx.author.id, entries); view.message = msg
    await msg.edit(content=None, embed=await view.build(), view=view)


# -maintenance
@bot.command(name="maintenance")
async def maintenance_cmd(ctx, mode: str = None):
    global maintenance
    if mode and mode.lower() in ("on", "oui", "1"):    maintenance = True
    elif mode and mode.lower() in ("off", "non", "0"): maintenance = False
    else:                                               maintenance = not maintenance
    await apply_presence()
    title = "🔧 Maintenance ON" if maintenance else "✅ Maintenance OFF"
    color = 0xED4245 if maintenance else 0x57F287
    desc  = "Bot en Ne pas déranger." if maintenance else "Bot de nouveau en ligne."
    await ctx.reply(embed=discord.Embed(title=title, description=desc, color=color))
    e = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    e.add_field(name="🛡️ Par", value=f"{ctx.author.mention}\n`{ctx.author.id}`")
    await log(ctx.guild, e)

# ════════════════════════════════════════════════
# COMMANDS — Contributeur (Pétale+)
# ════════════════════════════════════════════════

# -tempmute
@bot.command(name="tempmute")
async def tempmute_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-tempmute <id>`")
    try:
        uid_int = int(str(user_id).strip("<@!>"))
        member  = ctx.guild.get_member(uid_int) or await ctx.guild.fetch_member(uid_int)
    except: return await ctx.reply("❌ Membre introuvable.")
    if member.id == ctx.author.id: return await ctx.reply("❌ Tu ne peux pas te muter toi-même.")
    if is_sys_plus(member.id):     return await ctx.reply("❌ Tu ne peux pas muter un Sys+.")
    e = discord.Embed(
        title=f"🔇 Tempmute — {member.display_name}",
        description=f"**Membre :** {member.mention} (`{member.id}`)\nSélectionne une raison :",
        color=0xFF6600,
        timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=member.display_avatar.url)
    view = MuteReasonView(ctx.author.id, member)
    msg  = await ctx.reply(embed=e, view=view)
    view.message = msg


# -warn
@bot.command(name="warn")
async def warn_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-warn <id>`")
    try:
        uid_int = int(str(user_id).strip("<@!>"))
        member  = ctx.guild.get_member(uid_int) or await ctx.guild.fetch_member(uid_int)
    except: return await ctx.reply("❌ Membre introuvable.")
    if member.id == ctx.author.id: return await ctx.reply("❌ Tu ne peux pas te warn toi-même.")
    if is_sys_plus(member.id):     return await ctx.reply("❌ Tu ne peux pas warn un Sys+.")
    e = discord.Embed(
        title=f"⚠️ Warn — {member.display_name}",
        description=f"**Membre :** {member.mention} (`{member.id}`)\nSélectionne une raison :",
        color=0xFFC107,
        timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=member.display_avatar.url)
    view = WarnReasonView(ctx.author.id, member)
    msg  = await ctx.reply(embed=e, view=view)
    view.message = msg


# -unmute
@bot.command(name="unmute")
async def unmute_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-unmute <id>`")
    try:
        uid_int = int(str(user_id).strip("<@!>"))
        member  = ctx.guild.get_member(uid_int) or await ctx.guild.fetch_member(uid_int)
    except: return await ctx.reply("❌ Membre introuvable.")
    muted_role = ctx.guild.get_role(MUTED_ROLE_ID)
    if not muted_role:
        return await ctx.reply("❌ Rôle Muted introuvable. Vérifie l'ID dans la config.")
    try:
        await member.remove_roles(muted_role, reason=f"[UNMUTE] par {ctx.author}")
    except discord.Forbidden:
        return await ctx.reply("❌ Permissions insuffisantes.")

    now = now_ts()
    for sid, s in sanctions_db["sanctions"].items():
        if s["user_id"] == str(uid_int) and s["type"] == "tempmute" and s.get("active"):
            sanctions_db["sanctions"][sid]["active"] = False
    save_sanctions()

    invite = await make_invite(ctx.guild)
    desc = f"Ton mute sur **{ctx.guild.name}** a été levé."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(member, discord.Embed(
        title="✅ Mute levé — Shotojo",
        description=desc,
        color=0x57F287,
        timestamp=datetime.now(timezone.utc)))
    e = discord.Embed(title="✅ Unmute", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
    e.add_field(name="🛡️ Par",   value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    e.add_field(name="📩 MP",     value="✅" if dm_ok else "❌", inline=True)
    e.set_thumbnail(url=member.display_avatar.url)
    await log(ctx.guild, e)
    await ctx.reply(embed=discord.Embed(
        description=f"✅ **{member}** n'est plus muté.",
        color=0x57F287))


# -sanction
@bot.command(name="sanction")
async def sanction_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply("❌ `-sanction <id>`")
    uid = str(user_id).strip()
    sanctions = get_user_sanctions(uid)
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    type_emoji = {"tempmute": "🔇", "warn": "⚠️"}
    e = discord.Embed(
        title=f"📋 Historique des sanctions — {name}",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc))
    if not sanctions:
        e.description = "Aucune sanction enregistrée."
    else:
        lines = []
        for s in sanctions[-15:]:
            em     = type_emoji.get(s["type"], "❓")
            status = "🟢" if s.get("active") else "⬛"
            dur    = f" (`{s['duree_str']}`)" if s.get("duree_str") else ""
            lines.append(
                f"`#{s['id']}` {status} {em} **{s['type'].upper()}**{dur}\n"
                f"╰ {s['raison']} · {fmt_rel(s['at'])}"
            )
        e.description = "\n".join(lines)
        e.set_footer(text=f"Total : {len(sanctions)} sanction(s)")
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)


# -infosanction
@bot.command(name="infosanction")
async def infosanction_cmd(ctx, sanction_id: str = None, user_id: str = None):
    if not sanction_id or not user_id:
        return await ctx.reply("❌ `-infosanction <n°> <id>`")
    s = get_sanction(sanction_id)
    if not s or s["user_id"] != str(user_id).strip():
        return await ctx.reply(embed=discord.Embed(description="❌ Sanction introuvable.", color=0xFF0000))
    try: user = await bot.fetch_user(int(s["user_id"])); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({s['user_id']})"; avatar = None
    type_emoji = {"tempmute": "🔇", "warn": "⚠️"}
    color      = {"tempmute": 0xFF6600, "warn": 0xFFC107}
    e = discord.Embed(
        title=f"{type_emoji.get(s['type'], '❓')} Sanction #{s['id']} — {s['type'].upper()}",
        color=color.get(s["type"], 0x5865F2),
        timestamp=datetime.fromtimestamp(s["at"], timezone.utc))
    e.add_field(name="👤 Membre",  value=f"`{name}`\n`{s['user_id']}`", inline=True)
    e.add_field(name="🛡️ Par",    value=f"<@{s['by_id']}>\n`{s['by_id']}`", inline=True)
    e.add_field(name="🔘 Statut",  value="🟢 Active" if s.get("active") else "⬛ Expirée", inline=True)
    e.add_field(name="📅 Date",    value=f"{fmt(s['at'])}\n{fmt_rel(s['at'])}", inline=True)
    if s.get("duree_str"):
        e.add_field(name="⏱️ Durée", value=f"`{s['duree_str']}`", inline=True)
    if s.get("until"):
        e.add_field(name="🔓 Fin",   value=f"{fmt(s['until'])}\n{fmt_rel(s['until'])}", inline=True)
    e.add_field(name="📝 Raison",  value=s["raison"], inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)


# -delsanction (Sys+ only)
@bot.command(name="delsanction")
async def delsanction_cmd(ctx, sanction_id: str = None, user_id: str = None):
    if not sanction_id or not user_id:
        return await ctx.reply("❌ `-delsanction <n°> <id>`")
    s = get_sanction(sanction_id)
    if not s or s["user_id"] != str(user_id).strip():
        return await ctx.reply(embed=discord.Embed(description="❌ Sanction introuvable.", color=0xFF0000))
    sanctions_db["sanctions"].pop(str(sanction_id))
    save_sanctions()
    await ctx.reply(embed=discord.Embed(
        description=f"🗑️ Sanction `#{sanction_id}` supprimée.",
        color=0x57F287))
    e = discord.Embed(title="🗑️ Sanction supprimée", color=0xFF6600, timestamp=datetime.now(timezone.utc))
    e.add_field(name="🆔 Sanction", value=f"`#{sanction_id}`", inline=True)
    e.add_field(name="📋 Type",     value=s["type"].upper(), inline=True)
    e.add_field(name="🛡️ Par",     value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    await log(ctx.guild, e)

# ════════════════════════════════════════════════
# COMMANDS — Public
# ════════════════════════════════════════════════

@bot.command(name="help")
async def help_cmd(ctx):
    sys_plus = is_sys_plus(ctx.author.id)
    petale   = is_petale_or_plus(ctx.author)
    if sys_plus:
        e = discord.Embed(
            title="📖 Commandes — Sys+",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc))
        e.add_field(name="🚫 Bans & Blacklist", inline=False, value=(
            "`+bl <id> <raison>` — Blacklist + ban IP permanent\n"
            "`&unbl <id>` — Retire une blacklist\n"
            "`-blinfo <id>` — Infos blacklist\n"
            "`+ban <id> <durée> <raison>` — Ban temporaire *(ex: 1h30m)*\n"
            "`-baninfo <id>` — Infos tempban\n"
            "`-banpanel` — Panel de tous les bans"))
        e.add_field(name="🌪️ Tempête", inline=False, value=(
            "`/tempete <id> <raison>` — Ban IP définitif\n"
            "`/tempete-info <id>` — Infos tempête\n"
            "`/untempete <id>` — Retire une tempête\n"
            "`/unban-all` — Déban tout sauf BL & tempêtes"))
        e.add_field(name="🔇 Modération", inline=False, value=(
            "`-tempmute <id>` — Mute temporaire (rôle Muted)\n"
            "`-unmute <id>` — Unmute\n"
            "`-warn <id>` — Avertissement\n"
            "`-sanction <id>` — Historique des sanctions\n"
            "`-infosanction <n°> <id>` — Détails d'une sanction\n"
            "`-delsanction <n°> <id>` — Supprimer une sanction"))
        e.add_field(name="⚙️ Bot", inline=False,
                    value="`-maintenance [on|off]` — Mode maintenance")
    elif petale:
        e = discord.Embed(
            title="📖 Commandes — Contributeur",
            color=0xC0C0C0,
            timestamp=datetime.now(timezone.utc))
        e.add_field(name="🔇 Modération", inline=False, value=(
            "`-tempmute <id>` — Mute temporaire (rôle Muted)\n"
            "`-unmute <id>` — Unmute\n"
            "`-warn <id>` — Avertissement\n"
            "`-sanction <id>` — Historique des sanctions\n"
            "`-infosanction <n°> <id>` — Détails d'une sanction"))
    else:
        e = discord.Embed(
            title="📖 Aide",
            description="Tu n'as accès à aucune commande.",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc))
    e.set_footer(text=f"Demandé par {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=e)

# ════════════════════════════════════════════════
# SLASH COMMANDS — Sys+
# ════════════════════════════════════════════════

@tree.command(name="tempete", description="Tempête un membre — ban IP définitif [Sys+]")
@app_commands.describe(user_id="ID Discord", raison="Raison")
async def tempete_slash(i: discord.Interaction, user_id: str, raison: str = "Aucune raison"):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    try: user = await bot.fetch_user(int(user_id))
    except: return await i.response.send_message("❌ ID invalide.", ephemeral=True)
    uid = str(user_id); now = now_ts()
    tempetes[uid]  = {"raison": raison, "by": str(i.user), "by_id": i.user.id, "at": now}
    blacklist[uid] = {"raison": f"[TEMPÊTE] {raison}", "by": str(i.user), "by_id": i.user.id, "at": now}
    save(TEMPETE_FILE, tempetes); save(BL_FILE, blacklist)

    dm_e = discord.Embed(
        title="🌪️ Tu as été mis(e) sous Tempête — Shotojo",
        color=0xFF0000,
        timestamp=datetime.now(timezone.utc))
    dm_e.add_field(name="📋 Raison",  value=raison, inline=False)
    dm_e.add_field(name="📅 Date",    value=fmt(now), inline=True)
    dm_e.add_field(name="🌐 Type",    value="Ban IP permanent et définitif", inline=True)
    dm_e.add_field(name="📩 Contact", value=dm_footer_sanctions(), inline=False)
    try: await user.send(embed=dm_e)
    except: pass

    try: await i.guild.ban(user, reason=f"[TEMPÊTE — Ban IP] {raison}", delete_message_days=7)
    except discord.Forbidden:
        return await i.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)

    e = discord.Embed(title="🌪️ Tempête — Ban IP", color=0xE74C3C, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre", value=f"`{user}` (`{user_id}`)", inline=True)
    e.add_field(name="🛡️ Par",   value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(now)}\n{fmt_rel(now)}", inline=True)
    e.add_field(name="🌐 Type",   value="Ban IP permanent et définitif", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=user.display_avatar.url)
    await log(i.guild, e)
    await i.response.send_message(embed=discord.Embed(
        title="🌪️ Tempête exécutée",
        description=f"**{user}** (`{user_id}`) mis sous tempête · Ban IP\n📝 {raison}",
        color=0xE74C3C))


@tree.command(name="tempete-info", description="Infos sur une tempête [Sys+]")
@app_commands.describe(user_id="ID Discord")
async def tempete_info_slash(i: discord.Interaction, user_id: str):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    uid = str(user_id).strip(); data = tempetes.get(uid)
    if not data:
        return await i.response.send_message(
            embed=discord.Embed(description="❌ Aucune tempête pour cet ID.", color=0xFF0000), ephemeral=True)
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    e = discord.Embed(title="🌪️ Infos Tempête — Ban IP", color=0xE74C3C, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre", value=f"`{name}`\n`{uid}`", inline=True)
    e.add_field(name="🛡️ Par",   value=f"<@{data['by_id']}>\n`{data['by_id']}`", inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}", inline=True)
    e.add_field(name="🌐 Type",   value="Ban IP permanent et définitif", inline=True)
    e.add_field(name="📝 Raison", value=data["raison"], inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    await i.response.send_message(embed=e)


@tree.command(name="untempete", description="Retire une tempête [Sys+]")
@app_commands.describe(user_id="ID Discord")
async def untempete_slash(i: discord.Interaction, user_id: str):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    uid = str(user_id).strip()
    if uid not in tempetes:
        return await i.response.send_message(
            embed=discord.Embed(description="❌ Aucune tempête pour cet ID.", color=0xFF0000), ephemeral=True)
    try: user = await bot.fetch_user(int(uid))
    except: return await i.response.send_message("❌ ID invalide.", ephemeral=True)
    try: await i.guild.unban(user, reason=f"[UNTEMPÊTE] par {i.user}")
    except discord.NotFound: pass
    except discord.Forbidden:
        return await i.response.send_message("❌ Permissions insuffisantes.", ephemeral=True)
    data = tempetes.pop(uid); blacklist.pop(uid, None)
    save(TEMPETE_FILE, tempetes); save(BL_FILE, blacklist)
    invite = await make_invite(i.guild)
    desc = f"Ta tempête sur **{i.guild.name}** a été levée.\nTu peux désormais rejoindre à nouveau le serveur."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(
        title="✅ Tempête levée — Shotojo",
        description=desc,
        color=0x57F287,
        timestamp=datetime.now(timezone.utc)))
    e = discord.Embed(title="✅ Untempête", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="👤 Membre",          value=f"`{user}` (`{uid}`)", inline=True)
    e.add_field(name="🛡️ Par",            value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    e.add_field(name="📩 MP",              value="✅" if dm_ok else "❌", inline=True)
    e.add_field(name="📝 Raison initiale", value=data["raison"], inline=False)
    await log(i.guild, e)
    await i.response.send_message(embed=discord.Embed(
        title="✅ Tempête retirée",
        description=f"**{user}** n'est plus sous tempête.",
        color=0x57F287))


@tree.command(name="unban-all", description="Déban tout sauf blacklist et tempêtes [Sys+]")
async def unban_all_slash(i: discord.Interaction):
    if not is_sys_plus(i.user.id):
        return await i.response.send_message(await sys_violation(i.user), ephemeral=True)
    await i.response.defer()
    protected = set(blacklist.keys()) | set(tempetes.keys())
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
    e = discord.Embed(title="🔓 Unban-All", color=0x57F287, timestamp=datetime.now(timezone.utc))
    e.add_field(name="🛡️ Par",    value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    e.add_field(name="✅ Débannis", value=str(unbanned), inline=True)
    e.add_field(name="🚫 Ignorés", value=str(skipped),  inline=True)
    if failed: e.add_field(name="⚠️ Échecs", value=str(failed), inline=True)
    await log(i.guild, e)
    await i.followup.send(embed=discord.Embed(
        title="🔓 Unban-All terminé",
        description=(
            f"✅ {unbanned} débanni(s)\n"
            f"🚫 {skipped} ignoré(s) (BL/Tempête)" +
            (f"\n⚠️ {failed} échec(s)" if failed else "")
        ),
        color=0x57F287))

# ════════════════════════════════════════════════
# LANCEMENT
# ════════════════════════════════════════════════
bot.run(os.environ["TOKEN"])
