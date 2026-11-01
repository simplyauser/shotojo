import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import re
from datetime import datetime, timezone, timedelta

# ════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════
SYS_PLUS_IDS         = {1419320803199029402, 1514099294611701842}
CONTRIBUTOR_ROLE_IDS = {1556148445041926174}
GUILD_ID             = int(os.getenv("GUILD_ID"))
LOGS_ID              = int(os.getenv("LOGS_CHANNEL_ID", "0"))
MUTED_ROLE_ID        = 1560089046842216450
CIVILE_ROLE_ID       = 1564722577060929546
SUPPORT_CONTACT_ID   = 1558327588710121554
SUPPORT_INVITE       = "https://discord.gg/rAjayCuyyu"

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
    "unban":        "+",
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
#  PALETTE DA
# ════════════════════════════════════════════════
C = {
    "bl":      0xFF2D55,
    "ban":     0xFF6B2B,
    "tempete": 0xC0392B,
    "warn":    0xF1C40F,
    "mute":    0xE67E22,
    "ok":      0x2ECC71,
    "info":    0x5865F2,
    "sys":     0xFF73FA,
    "dark":    0x1A1A2E,
    "log":     0x2C2F33,
    "maint":   0xFFB347,
    "panel":   0x4F46E5,
    "sanc":    0x7C3AED,
}

SEP = "┄" * 32

def _ts():    return datetime.now(timezone.utc)
def now_ts(): return _ts().timestamp()

# ════════════════════════════════════════════════
#  EMBED FACTORY
# ════════════════════════════════════════════════
def _b(color: int) -> discord.Embed:
    return discord.Embed(color=color, timestamp=_ts())

def emb_ok(desc=None, title=None):
    e = _b(C["ok"])
    e.title       = f"✦  {title}" if title else "✦  Succès"
    e.description = desc
    return e

def emb_err(desc=None, title=None):
    e = _b(C["bl"])
    e.title       = f"✗  {title}" if title else "✗  Erreur"
    e.description = desc
    return e

def emb_warn_ui(desc=None, title=None):
    e = _b(C["warn"])
    e.title       = f"◈  {title}" if title else "◈  Attention"
    e.description = desc
    return e

def emb_info(desc=None, title=None, color=None):
    e = _b(color or C["info"])
    if title: e.title = title
    if desc:  e.description = desc
    return e

def emb_log(title: str, color: int) -> discord.Embed:
    e = _b(color)
    e.title = title
    return e

def set_footer(e: discord.Embed, user=None):
    now = _ts().strftime("%d/%m/%Y  %H:%M")
    if user:
        icon = user.display_avatar.url if hasattr(user, "display_avatar") else discord.utils.MISSING
        e.set_footer(text=f"Shotojo  ·  {now}  ·  {user}", icon_url=icon)
    else:
        e.set_footer(text=f"Shotojo  ·  {now}")
    return e

# ════════════════════════════════════════════════
#  STORAGE
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
    entry = {
        "id": int(sid), "user_id": str(user_id), "type": type_,
        "raison": raison, "by": by, "by_id": by_id, "at": at, "active": True,
    }
    entry.update(kwargs)
    sanctions_db["sanctions"][sid] = entry
    save_sanctions()
    return int(sid)

def get_user_sanctions(user_id):
    uid = str(user_id)
    return sorted(
        [s for s in sanctions_db["sanctions"].values() if s["user_id"] == uid],
        key=lambda x: x["at"],
    )

def get_sanction(sid):
    return sanctions_db["sanctions"].get(str(sid))

# ════════════════════════════════════════════════
#  BOT
# ════════════════════════════════════════════════
async def get_prefix(bot, message): return ["+", "-", "&"]

def make_activity():
    return discord.Activity(
        type=discord.ActivityType.watching,
        name="Shotojo 🌸  #🇯🇵",
        state="Nous vous préparons de grandes choses",
    )

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=get_prefix, intents=intents,
    help_command=None, status=discord.Status.online, activity=make_activity(),
)
tree        = bot.tree
maintenance = False

async def apply_presence():
    if maintenance:
        await bot.change_presence(
            status=discord.Status.dnd,
            activity=discord.Game(name="🔧  Maintenance en cours"),
        )
    else:
        await bot.change_presence(status=discord.Status.online, activity=make_activity())

# ════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════
def is_sys_plus(uid): return uid in SYS_PLUS_IDS

def is_petale_or_plus(member):
    if is_sys_plus(member.id): return True
    if not hasattr(member, "roles"): return False
    return any(r.id in CONTRIBUTOR_ROLE_IDS for r in member.roles)

# Discord timestamps are capped at year ~3000 (Unix ts 32503680000)
TS_MAX = 32503680000

def fmt(ts):
    ts = int(ts)
    if ts > TS_MAX: return "♾️  Permanent"
    return f"<t:{ts}:F>"

def fmt_rel(ts):
    ts = int(ts)
    if ts > TS_MAX: return "♾️"
    return f"<t:{ts}:R>"

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
    text = str(text)
    return text if len(text) <= n else text[:n - 1] + "..."

async def log(guild, embed):
    if not LOGS_ID: return
    ch = guild.get_channel(LOGS_ID)
    if ch:
        try: await ch.send(embed=embed)
        except Exception: pass

async def try_dm(user, embed):
    try: await user.send(embed=embed); return True
    except: return False

async def try_dm_text(user, content: str):
    try: await user.send(content=content); return True
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

def dm_text_bl(raison: str, guild_name: str) -> str:
    return (
        f"Tu as été blacklisté(e) de **{guild_name}** définitivement pour la raison suivante : `{raison}`.\n\n"
        f"Si tu veux demander pardon viens ici : {SUPPORT_INVITE}"
    )

def dm_text_tempete(raison: str, guild_name: str) -> str:
    return (
        f"Tu as été mis(e) sous Tempête de **{guild_name}** définitivement pour la raison suivante : `{raison}`.\n\n"
        f"Si tu veux demander pardon viens ici : {SUPPORT_INVITE}"
    )

def dm_text_ban(raison: str, guild_name: str, duree_str: str, until: float) -> str:
    return (
        f"Tu as été banni(e) temporairement de **{guild_name}** pour la raison suivante : `{raison}`.\n"
        f"Durée : **{duree_str}** · Fin : {fmt(until)}\n\n"
        f"Si tu veux demander pardon viens ici : {SUPPORT_INVITE}"
    )

def dm_text_mute(raison: str, guild_name: str, duree_str: str, until: float) -> str:
    return (
        f"Tu as été réduit(e) au silence sur **{guild_name}**.\n"
        f"Raison : `{raison}`  ·  Durée : **{duree_str}**  ·  Fin : {fmt(until)}\n\n"
        f"Si tu estimes que c'est un abus, envoie un MP à <@{SUPPORT_CONTACT_ID}>."
    )

def dm_text_warn(raison: str, guild_name: str) -> str:
    return (
        f"Tu as reçu un avertissement sur **{guild_name}** pour la raison suivante : `{raison}`.\n\n"
        f"Si tu veux contester, viens ici : {SUPPORT_INVITE}"
    )

# ════════════════════════════════════════════════
#  VIOLATIONS
# ════════════════════════════════════════════════
async def sys_violation(member):
    try:
        await member.timeout(timedelta(minutes=1), reason="Tentative de commande non autorisée")
        msg = "🔇  Accès refusé. Tu viens d'être timeout 1 minute."
        ok  = True
    except Exception:
        msg = "🔇  Accès refusé."
        ok  = False
    guild = getattr(member, "guild", None)
    if guild:
        e = emb_log("🔇  Timeout automatique", C["mute"])
        e.description = f"{member.mention} a tenté d'utiliser une commande non autorisée."
        e.add_field(name="👤 Membre",  value=f"{member.mention}\n`{member.id}`", inline=True)
        e.add_field(name="⏱️ Durée",  value="`1 minute`" if ok else "Échec timeout", inline=True)
        e.add_field(name="📋 Raison", value="Commande non autorisée", inline=False)
        try: await log(guild, e)
        except Exception: pass
    return msg

async def not_sys_plus(ctx):
    msg = await sys_violation(ctx.author)
    await ctx.reply(msg)

# ════════════════════════════════════════════════
#  MIDDLEWARE
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
            await ctx.reply(embed=emb_err("Tu n'as pas les permissions nécessaires."))
            raise commands.CheckFailure()
        return
    if not is_sys_plus(ctx.author.id):
        await not_sys_plus(ctx)
        raise commands.CheckFailure()

# ════════════════════════════════════════════════
#  EVENTS
# ════════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    await apply_presence()
    if not check_tempbans.is_running(): check_tempbans.start()
    if not check_mutes.is_running():    check_mutes.start()
    print(f"OK  {bot.user} connecte (ID: {bot.user.id})")

@bot.event
async def on_member_join(member):
    uid = str(member.id)
    if uid in blacklist:
        data = blacklist[uid]
        try:
            await member.send(dm_text_bl(data["raison"], member.guild.name))
        except Exception:
            pass
        try:
            await member.ban(reason=f"[Blacklist · Ban IP]  {data['raison']}", delete_message_days=0)
        except Exception:
            pass

# ════════════════════════════════════════════════
#  TASKS
# ════════════════════════════════════════════════
@tasks.loop(seconds=30)
async def check_tempbans():
    now = now_ts()
    for uid, data in [(u, d) for u, d in list(tempbans.items()) if d["until"] <= now]:
        guild = bot.get_guild(data["guild_id"])
        if not guild: continue
        try:
            user   = await bot.fetch_user(int(uid))
            await guild.unban(user, reason="Tempban expiré")
            invite = await make_invite(guild)
            desc   = f"Ton ban temporaire sur **{guild.name}** est expiré.\nTu peux désormais rejoindre le serveur."
            if invite: desc += f"\n\n🔗 {invite}"
            dm_e = discord.Embed(
                title="✅  Ban expiré  ·  Shotojo",
                description=desc,
                color=C["ok"],
                timestamp=_ts(),
            )
            dm_ok = await try_dm(user, dm_e)
            e = emb_log("✅  Unban automatique", C["ok"])
            e.add_field(name="👤 Membre", value=f"`{user}` (`{uid}`)", inline=True)
            e.add_field(name="⏱️ Durée",  value=f"`{data['duree_str']}`", inline=True)
            e.add_field(name="📩 MP",      value="✅" if dm_ok else "❌", inline=True)
            await log(guild, e)
        except Exception:
            pass
        tempbans.pop(uid, None)
        save(TEMPBAN_FILE, tempbans)


@tasks.loop(minutes=1)
async def check_mutes():
    now     = now_ts()
    changed = False
    guild   = bot.get_guild(GUILD_ID)
    for sid, s in list(sanctions_db["sanctions"].items()):
        if s["type"] == "tempmute" and s.get("active") and s.get("until", 0) <= now:
            sanctions_db["sanctions"][sid]["active"] = False
            changed = True
            if guild:
                try:
                    member     = guild.get_member(int(s["user_id"])) or await guild.fetch_member(int(s["user_id"]))
                    muted_role = guild.get_role(MUTED_ROLE_ID)
                    civile_role = guild.get_role(CIVILE_ROLE_ID)
                    if muted_role and muted_role in member.roles:
                        await member.remove_roles(muted_role, reason="Mute expiré automatiquement")
                    if civile_role and civile_role not in member.roles:
                        await member.add_roles(civile_role, reason="Mute expiré automatiquement")
                    await try_dm_text(member, "Vous avez de nouveau la permission de parler sur Shotojo 🌸 !")
                except Exception:
                    pass
    if changed: save_sanctions()

# ════════════════════════════════════════════════
#  PANEL VIEWS
# ════════════════════════════════════════════════
class MuteReasonView(discord.ui.View):
    def __init__(self, author_id, target):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target    = target
        self.message   = None

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message(embed=emb_err("Ce panel ne t'appartient pas."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except Exception: pass

    @discord.ui.select(
        placeholder="Choisir une raison...",
        options=[discord.SelectOption(label=r, value=r, emoji=d["emoji"]) for r, d in MUTE_REASONS.items()],
    )
    async def reason_select(self, i: discord.Interaction, select: discord.ui.Select):
        raison = select.values[0]
        view   = MuteDurationView(self.author_id, self.target, raison)
        view.message = self.message
        e = discord.Embed(
            title=f"🔇  Tempmute  ·  {self.target.display_name}",
            description=f"`{SEP}`\n**Raison :** {raison}\n\nChoisis la durée :",
            color=C["mute"],
            timestamp=_ts(),
        )
        e.set_thumbnail(url=self.target.display_avatar.url)
        await i.response.edit_message(embed=e, view=view)


class DurationButton(discord.ui.Button):
    def __init__(self, duree, raison, author_id, target):
        super().__init__(label=duree, style=discord.ButtonStyle.primary)
        self.duree     = duree
        self.raison    = raison
        self.author_id = author_id
        self.target    = target

    async def callback(self, i: discord.Interaction):
        if i.user.id != self.author_id:
            return await i.response.send_message(embed=emb_err("Ce panel ne t'appartient pas."), ephemeral=True)
        await apply_tempmute(i, self.target, self.raison, self.duree)


class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Annuler", style=discord.ButtonStyle.danger)

    async def callback(self, i: discord.Interaction):
        await i.response.edit_message(content="Annulé.", embed=None, view=None)


class MuteDurationView(discord.ui.View):
    def __init__(self, author_id, target, raison):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target    = target
        self.raison    = raison
        self.message   = None
        for duree in MUTE_REASONS[raison]["durees"]:
            self.add_item(DurationButton(duree, raison, author_id, target))
        self.add_item(CancelButton())

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message(embed=emb_err("Ce panel ne t'appartient pas."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except Exception: pass


class WarnReasonView(discord.ui.View):
    def __init__(self, author_id, target):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.target    = target
        self.message   = None

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message(embed=emb_err("Ce panel ne t'appartient pas."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except Exception: pass

    @discord.ui.select(
        placeholder="Choisir une raison...",
        options=[discord.SelectOption(label=r, value=r, emoji=d["emoji"]) for r, d in MUTE_REASONS.items()],
    )
    async def reason_select(self, i: discord.Interaction, select: discord.ui.Select):
        await apply_warn(i, self.target, select.values[0])

# ════════════════════════════════════════════════
#  APPLY FUNCTIONS
# ════════════════════════════════════════════════
async def apply_tempmute(i: discord.Interaction, member: discord.Member, raison: str, duree_str: str):
    seconds = parse_dur_str(duree_str)
    now     = now_ts()
    until   = now + seconds

    muted_role  = i.guild.get_role(MUTED_ROLE_ID)
    civile_role = i.guild.get_role(CIVILE_ROLE_ID)
    if not muted_role:
        return await i.response.edit_message(embed=emb_err("Rôle Muted introuvable. Vérifie la config."), view=None)
    try:
        roles_to_remove = [muted_role] if muted_role not in member.roles else []
        roles_to_add    = [muted_role]
        if civile_role and civile_role in member.roles:
            roles_to_remove.append(civile_role)
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f"[Mute]  {raison}")
        await member.add_roles(muted_role, reason=f"[Mute]  {raison}")
    except discord.Forbidden:
        return await i.response.edit_message(embed=emb_err("Permissions insuffisantes."), view=None)
    except Exception as exc:
        return await i.response.edit_message(embed=emb_err(f"Erreur : {exc}"), view=None)

    sid = add_sanction(
        user_id=str(member.id), type_="tempmute", raison=raison,
        duree_str=duree_str, duree_s=seconds, until=until,
        by=str(i.user), by_id=i.user.id, at=now,
    )

    dm_ok = await try_dm_text(member, dm_text_mute(raison, i.guild.name, duree_str, until))

    log_e = emb_log("🔇  Tempmute", C["mute"])
    log_e.add_field(name="👤 Membre",    value=f"{member.mention}\n`{member.id}`",    inline=True)
    log_e.add_field(name="🛡️ Par",      value=f"{i.user.mention}\n`{i.user.id}`",    inline=True)
    log_e.add_field(name="⏱️ Durée",    value=f"`{duree_str}`",                       inline=True)
    log_e.add_field(name="📅 Appliqué", value=f"{fmt(now)}\n{fmt_rel(now)}",          inline=True)
    log_e.add_field(name="🔓 Fin",       value=f"{fmt(until)}\n{fmt_rel(until)}",     inline=True)
    log_e.add_field(name="📩 MP",        value="✅" if dm_ok else "❌",              inline=True)
    log_e.add_field(name="📝 Raison",    value=raison,                                inline=False)
    log_e.add_field(name="🆔 Sanction", value=f"`#{sid}`",                            inline=True)
    log_e.set_thumbnail(url=member.display_avatar.url)
    await log(i.guild, log_e)

    result_e = discord.Embed(
        title="✦  Mute appliqué",
        description=f"`{SEP}`",
        color=C["mute"],
        timestamp=_ts(),
    )
    result_e.add_field(name="👤 Membre",   value=f"{member.mention}\n`{member.id}`", inline=False)
    result_e.add_field(name="📝 Raison",   value=raison,                              inline=False)
    result_e.add_field(name="⏱️ Durée",   value=f"`{duree_str}`",                    inline=True)
    result_e.add_field(name="🔓 Fin",      value=fmt(until),                          inline=True)
    result_e.add_field(name="🆔 Sanction", value=f"`#{sid}`",                         inline=True)
    result_e.set_thumbnail(url=member.display_avatar.url)
    set_footer(result_e, i.user)
    await i.response.edit_message(embed=result_e, view=None)


async def apply_warn(i: discord.Interaction, member: discord.Member, raison: str):
    now = now_ts()
    sid = add_sanction(
        user_id=str(member.id), type_="warn", raison=raison,
        by=str(i.user), by_id=i.user.id, at=now,
    )

    dm_ok = await try_dm_text(member, dm_text_warn(raison, i.guild.name))

    log_e = emb_log("⚠️  Warn", C["warn"])
    log_e.add_field(name="👤 Membre",    value=f"{member.mention}\n`{member.id}`", inline=True)
    log_e.add_field(name="🛡️ Par",      value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    log_e.add_field(name="📅 Date",      value=f"{fmt(now)}\n{fmt_rel(now)}",      inline=True)
    log_e.add_field(name="📝 Raison",    value=raison,                              inline=False)
    log_e.add_field(name="📩 MP",        value="✅" if dm_ok else "❌",            inline=True)
    log_e.add_field(name="🆔 Sanction", value=f"`#{sid}`",                         inline=True)
    log_e.set_thumbnail(url=member.display_avatar.url)
    await log(i.guild, log_e)

    result_e = discord.Embed(
        title="✦  Warn appliqué",
        description=f"`{SEP}`",
        color=C["warn"],
        timestamp=_ts(),
    )
    result_e.add_field(name="👤 Membre",   value=f"{member.mention}\n`{member.id}`", inline=False)
    result_e.add_field(name="📝 Raison",   value=raison,                              inline=False)
    result_e.add_field(name="📅 Date",     value=fmt(now),                            inline=True)
    result_e.add_field(name="🆔 Sanction", value=f"`#{sid}`",                         inline=True)
    result_e.set_thumbnail(url=member.display_avatar.url)
    set_footer(result_e, i.user)
    await i.response.edit_message(embed=result_e, view=None)

# ════════════════════════════════════════════════
#  BAN PANEL
# ════════════════════════════════════════════════
PANEL_PER_PAGE = 4
CATS = {
    "tempban": ("🔨", "Tempban",    C["ban"]),
    "bl":      ("🚫", "Blacklist",  C["bl"]),
    "tempete": ("🌪️", "Tempête",   C["tempete"]),
    "manuel":  ("⚖️", "Ban manuel", C["log"]),
}

async def collect_bans(guild):
    entries = []
    for uid, d in tempbans.items():
        entries.append({"type": "tempban", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in tempetes.items():
        entries.append({"type": "tempete", "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    for uid, d in blacklist.items():
        if uid in tempetes: continue
        entries.append({"type": "bl",      "uid": uid, "data": d, "at": d.get("at", 0), "user": None})
    known = set(tempbans) | set(blacklist) | set(tempetes)
    try:
        async for e in guild.bans(limit=None):
            uid = str(e.user.id)
            if uid in known: continue
            entries.append({"type": "manuel", "uid": uid, "data": {"raison": e.reason or "Aucune raison"}, "at": None, "user": e.user})
    except Exception:
        pass
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
            f"⏱️ Durée : `{d['duree_str']}`  ·  Reste : `{fmt_duration(int(remaining))}`",
            f"📅 Banni le : {fmt(d['at'])}",
            f"🔓 Fin : {fmt(d['until'])} ({fmt_rel(d['until'])})",
            f"📝 {cut(d['raison'])}",
        ]
    elif t in ("bl", "tempete"):
        lines += [
            f"🛡️ Par : <@{d['by_id']}> (`{d['by_id']}`)",
            f"📅 {fmt(d['at'])} ({fmt_rel(d['at'])})",
            f"📝 {cut(d['raison'])}",
            "♾️ Permanent  ·  Ban IP",
        ]
    else:
        lines += [f"📝 {cut(d['raison'])}", "ℹ️ Ban manuel"]
    return "\n".join(lines)[:1024]


class BanPanel(discord.ui.View):
    def __init__(self, author_id, entries):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.entries   = entries
        self.filter    = "all"
        self.page      = 0
        self.message   = None

    def filtered(self):
        return self.entries if self.filter == "all" else [e for e in self.entries if e["type"] == self.filter]

    def total_pages(self): return max(1, -(-len(self.filtered()) // PANEL_PER_PAGE))

    async def build(self):
        items  = self.filtered()
        pages  = self.total_pages()
        self.page = max(0, min(self.page, pages - 1))
        chunk  = items[self.page * PANEL_PER_PAGE:(self.page + 1) * PANEL_PER_PAGE]
        counts = {k: sum(1 for e in self.entries if e["type"] == k) for k in CATS}
        e = discord.Embed(
            title="🛡️  Panel des bans  ·  Shotojo",
            description=(
                f"`{SEP}`\n"
                f"**Total : {len(self.entries)} ban(s)**\n"
                f"🔨 Tempbans  ·  `{counts['tempban']}`\n"
                f"🚫 Blacklist  ·  `{counts['bl']}`\n"
                f"🌪️ Tempêtes  ·  `{counts['tempete']}`\n"
                f"⚖️ Bans manuels  ·  `{counts['manuel']}`"
            ),
            color=C["panel"],
            timestamp=_ts(),
        )
        if not chunk:
            e.add_field(name="Aucun résultat", value="Aucun ban dans cette catégorie.", inline=False)
        for en in chunk:
            emoji, label, _ = CATS[en["type"]]
            name = await entry_name(en)
            e.add_field(name=f"{emoji}  {label}  ·  {name}"[:256], value=entry_value(en), inline=False)
        filt = "Tous" if self.filter == "all" else CATS[self.filter][1]
        e.set_footer(text=f"Filtre : {filt}  ·  Page {self.page + 1}/{pages}")
        return e

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message(embed=emb_err("Ce panel ne t'appartient pas."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        if self.message:
            try: await self.message.edit(view=self)
            except Exception: pass

    @discord.ui.select(
        placeholder="Filtrer par type...",
        options=[
            discord.SelectOption(label="Tous",         value="all",     emoji="📋"),
            discord.SelectOption(label="Tempbans",     value="tempban", emoji="🔨"),
            discord.SelectOption(label="Blacklist",    value="bl",      emoji="🚫"),
            discord.SelectOption(label="Tempêtes",     value="tempete", emoji="🌪️"),
            discord.SelectOption(label="Bans manuels", value="manuel",  emoji="⚖️"),
        ],
    )
    async def filter_select(self, i: discord.Interaction, select: discord.ui.Select):
        self.filter = select.values[0]; self.page = 0
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, i: discord.Interaction, b):
        self.page = (self.page - 1) % self.total_pages()
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, i: discord.Interaction, b):
        self.page = (self.page + 1) % self.total_pages()
        await i.response.edit_message(embed=await self.build(), view=self)

    @discord.ui.button(label="🔄  Actualiser", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, i: discord.Interaction, b):
        self.entries = await collect_bans(i.guild)
        await i.response.edit_message(embed=await self.build(), view=self)

# ════════════════════════════════════════════════
#  COMMANDS  ·  Sys+
# ════════════════════════════════════════════════

@bot.command(name="bl")
async def bl_cmd(ctx, user_id: str = None, *, raison: str = "Aucune raison"):
    if not user_id: return await ctx.reply(embed=emb_err("`+bl <id> <raison>`"))
    try: uid_int = int(user_id); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply(embed=emb_err("ID invalide."))
    uid = str(uid_int); now = now_ts()
    blacklist[uid] = {"raison": raison, "by": str(ctx.author), "by_id": ctx.author.id, "at": now}
    save(BL_FILE, blacklist)

    await try_dm_text(user, dm_text_bl(raison, ctx.guild.name))

    try: await ctx.guild.ban(user, reason=f"[BL · Ban IP]  {raison}", delete_message_days=0)
    except discord.Forbidden: return await ctx.reply(embed=emb_err("Permissions insuffisantes."))

    log_e = emb_log("🚫  Blacklist  ·  Ban IP", C["bl"])
    log_e.add_field(name="👤 Membre", value=f"`{user}` (`{uid_int}`)",                     inline=True)
    log_e.add_field(name="🛡️ Par",   value=f"{ctx.author.mention}\n`{ctx.author.id}`",     inline=True)
    log_e.add_field(name="📅 Date",   value=f"{fmt(now)}\n{fmt_rel(now)}",                  inline=True)
    log_e.add_field(name="🌐 Type",   value="Ban IP permanent",                              inline=True)
    log_e.add_field(name="📝 Raison", value=raison,                                          inline=False)
    log_e.set_thumbnail(url=user.display_avatar.url)
    await log(ctx.guild, log_e)

    result_e = discord.Embed(
        title="✦  Blacklist ajoutée",
        description=f"🚫  **{user}** (`{uid_int}`) blacklisté  ·  Ban IP\n📝 {raison}",
        color=C["bl"], timestamp=_ts(),
    )
    set_footer(result_e, ctx.author)
    await ctx.reply(embed=result_e)


@bot.command(name="ban")
async def ban_cmd(ctx, user_id: str = None, duree: str = None, *, raison: str = "Aucune raison"):
    if not user_id or not duree:
        return await ctx.reply(embed=emb_err("`+ban <id> <durée> <raison>`  ·  ex : `+ban 123456789 1h30m Spam`"))
    try: uid_int = int(user_id); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply(embed=emb_err("ID invalide."))
    seconds = parse_duration(duree)
    if seconds <= 0: return await ctx.reply(embed=emb_err("Durée invalide.  ·  Ex : `1h`, `30m`, `2j`"))
    uid = str(uid_int); now = now_ts(); until = now + seconds; duree_str = fmt_duration(seconds)
    tempbans[uid] = {
        "raison": raison, "by": str(ctx.author), "by_id": ctx.author.id,
        "at": now, "until": until, "guild_id": ctx.guild.id, "duree_str": duree_str,
    }
    save(TEMPBAN_FILE, tempbans)

    await try_dm_text(user, dm_text_ban(raison, ctx.guild.name, duree_str, until))

    try: await ctx.guild.ban(user, reason=f"[Tempban  {duree_str}]  {raison}", delete_message_days=0)
    except discord.Forbidden: return await ctx.reply(embed=emb_err("Permissions insuffisantes."))

    log_e = emb_log("🔨  Tempban", C["ban"])
    log_e.add_field(name="👤 Membre",  value=f"`{user}` (`{uid_int}`)",                     inline=True)
    log_e.add_field(name="🛡️ Par",    value=f"{ctx.author.mention}\n`{ctx.author.id}`",     inline=True)
    log_e.add_field(name="⏱️ Durée",  value=f"`{duree_str}`",                               inline=True)
    log_e.add_field(name="📅 Date",    value=f"{fmt(now)}\n{fmt_rel(now)}",                  inline=True)
    log_e.add_field(name="🔓 Fin",     value=f"{fmt(until)}\n{fmt_rel(until)}",              inline=True)
    log_e.add_field(name="📝 Raison",  value=raison,                                          inline=False)
    log_e.set_thumbnail(url=user.display_avatar.url)
    await log(ctx.guild, log_e)

    result_e = discord.Embed(
        title="✦  Tempban appliqué",
        description=f"🔨  **{user}** banni **{duree_str}**\n📝 {raison}\n🔓 Fin : {fmt(until)}",
        color=C["ban"], timestamp=_ts(),
    )
    set_footer(result_e, ctx.author)
    await ctx.reply(embed=result_e)


@bot.command(name="unban")
async def unban_cmd(ctx, user_id: str = None, *, raison: str = "Aucune raison"):
    if not user_id: return await ctx.reply(embed=emb_err("`+unban <id> [raison]`"))
    uid = str(user_id).strip()

    if uid in blacklist:
        return await ctx.reply(embed=emb_warn_ui(
            "Cet utilisateur est **blacklisté**. Utilise `&unbl` pour lever la blacklist d'abord.",
            "Unban bloqué"
        ))
    if uid in tempetes:
        return await ctx.reply(embed=emb_warn_ui(
            "Cet utilisateur est sous **Tempête**. Utilise `/untempete` pour la lever d'abord.",
            "Unban bloqué"
        ))

    try: uid_int = int(uid); user = await bot.fetch_user(uid_int)
    except: return await ctx.reply(embed=emb_err("ID invalide."))

    try:
        await ctx.guild.unban(user, reason=f"[UNBAN]  {raison}  par {ctx.author}")
    except discord.NotFound:
        return await ctx.reply(embed=emb_err("Cet utilisateur n'est pas banni."))
    except discord.Forbidden:
        return await ctx.reply(embed=emb_err("Permissions insuffisantes."))

    was_tempban = uid in tempbans
    tempbans.pop(uid, None)
    if was_tempban: save(TEMPBAN_FILE, tempbans)

    invite = await make_invite(ctx.guild)
    desc   = f"Tu as été débanni(e) de **{ctx.guild.name}**.\nTu peux désormais rejoindre le serveur."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(
        title="✅  Tu as été débanni(e)  ·  Shotojo",
        description=desc,
        color=C["ok"], timestamp=_ts(),
    ))

    now = now_ts()
    log_e = emb_log("✅  Unban", C["ok"])
    log_e.add_field(name="👤 Membre",  value=f"`{user}` (`{uid_int}`)",                     inline=True)
    log_e.add_field(name="🛡️ Par",    value=f"{ctx.author.mention}\n`{ctx.author.id}`",     inline=True)
    log_e.add_field(name="📩 MP",      value="✅" if dm_ok else "❌",                       inline=True)
    log_e.add_field(name="📅 Date",    value=f"{fmt(now)}\n{fmt_rel(now)}",                  inline=True)
    log_e.add_field(name="📝 Raison",  value=raison,                                          inline=False)
    if was_tempban: log_e.add_field(name="🔨 Tempban", value="Supprimé du fichier",           inline=True)
    log_e.set_thumbnail(url=user.display_avatar.url)
    await log(ctx.guild, log_e)

    result_e = discord.Embed(
        title="✦  Unban effectué",
        description=f"✅  **{user}** (`{uid_int}`) a été débanni.\n📝 {raison}",
        color=C["ok"], timestamp=_ts(),
    )
    set_footer(result_e, ctx.author)
    await ctx.reply(embed=result_e)


@bot.command(name="baninfo")
async def baninfo_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`-baninfo <id>`"))
    uid  = str(user_id).strip()
    data = tempbans.get(uid)
    if not data:
        return await ctx.reply(embed=emb_err("Aucun tempban pour cet ID."))
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    remaining = max(0, data["until"] - now_ts())
    e = discord.Embed(title="🔍  Infos Tempban", color=C["ban"], timestamp=_ts())
    e.description = f"`{SEP}`"
    e.add_field(name="👤 Membre",    value=f"`{name}`\n`{uid}`",                                 inline=True)
    e.add_field(name="🛡️ Par",      value=f"<@{data['by_id']}>\n`{data['by_id']}`",             inline=True)
    e.add_field(name="⏱️ Durée",    value=f"`{data['duree_str']}`",                              inline=True)
    e.add_field(name="📅 Banni le", value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}",           inline=True)
    e.add_field(name="🔓 Fin",       value=f"{fmt(data['until'])}\n{fmt_rel(data['until'])}",    inline=True)
    e.add_field(name="⏳ Reste",     value=f"`{fmt_duration(int(remaining))}`",                   inline=True)
    e.add_field(name="📝 Raison",    value=data["raison"],                                         inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    set_footer(e, ctx.author)
    await ctx.reply(embed=e)


@bot.command(name="blinfo")
async def blinfo_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`-blinfo <id>`"))
    uid  = str(user_id).strip()
    data = blacklist.get(uid)
    if not data:
        return await ctx.reply(embed=emb_err("Aucune blacklist pour cet ID."))
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    e = discord.Embed(title="🔍  Infos Blacklist  ·  Ban IP", color=C["bl"], timestamp=_ts())
    e.description = f"`{SEP}`"
    e.add_field(name="👤 Membre", value=f"`{name}`\n`{uid}`",                                inline=True)
    e.add_field(name="🛡️ Par",   value=f"<@{data['by_id']}>\n`{data['by_id']}`",            inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}",          inline=True)
    e.add_field(name="🌐 Type",   value="Ban IP permanent",                                    inline=True)
    e.add_field(name="📝 Raison", value=data["raison"],                                         inline=False)
    e.set_footer(text="Sanction permanente  ·  Ban IP")
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)


@bot.command(name="unbl")
async def unbl_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`&unbl <id>`"))
    uid = str(user_id).strip()
    if uid in tempetes:
        return await ctx.reply(embed=emb_warn_ui("Cette personne est sous tempête, utilise `/untempete`."))
    if uid not in blacklist:
        return await ctx.reply(embed=emb_err("Cet ID n'est pas blacklisté."))
    try: user = await bot.fetch_user(int(uid))
    except: return await ctx.reply(embed=emb_err("ID invalide."))
    try: await ctx.guild.unban(user, reason=f"[UNBL]  par {ctx.author}")
    except discord.NotFound: pass
    except discord.Forbidden: return await ctx.reply(embed=emb_err("Permissions insuffisantes."))
    data = blacklist.pop(uid)
    save(BL_FILE, blacklist)
    invite = await make_invite(ctx.guild)
    desc   = f"Ta blacklist sur **{ctx.guild.name}** a été levée.\nTu peux désormais rejoindre le serveur."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(
        title="✅  Blacklist levée  ·  Shotojo",
        description=desc,
        color=C["ok"], timestamp=_ts(),
    ))
    log_e = emb_log("✅  Unbl", C["ok"])
    log_e.add_field(name="👤 Membre",          value=f"`{user}` (`{uid}`)",                     inline=True)
    log_e.add_field(name="🛡️ Par",            value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    log_e.add_field(name="📩 MP",              value="✅" if dm_ok else "❌",                   inline=True)
    log_e.add_field(name="📝 Raison initiale", value=data["raison"],                              inline=False)
    await log(ctx.guild, log_e)
    result_e = emb_ok(f"✅  **{user}** retiré de la blacklist et débanni.")
    set_footer(result_e, ctx.author)
    await ctx.reply(embed=result_e)


@bot.command(name="banpanel")
async def banpanel_cmd(ctx):
    msg = await ctx.reply(embed=emb_info("Chargement en cours..."))
    entries = await collect_bans(ctx.guild)
    view = BanPanel(ctx.author.id, entries)
    view.message = msg
    await msg.edit(content=None, embed=await view.build(), view=view)


@bot.command(name="maintenance")
async def maintenance_cmd(ctx, mode: str = None):
    global maintenance
    if   mode and mode.lower() in ("on", "oui", "1"):  maintenance = True
    elif mode and mode.lower() in ("off", "non", "0"): maintenance = False
    else:                                               maintenance = not maintenance
    await apply_presence()
    if maintenance:
        e = emb_warn_ui("Bot en statut Ne pas déranger.", "Maintenance ON")
    else:
        e = emb_ok("Bot de nouveau en ligne.", "Maintenance OFF")
    set_footer(e, ctx.author)
    await ctx.reply(embed=e)
    log_e = emb_log(f"🔧  Maintenance {'ON' if maintenance else 'OFF'}", C["maint"])
    log_e.add_field(name="🛡️ Par", value=f"{ctx.author.mention}\n`{ctx.author.id}`")
    await log(ctx.guild, log_e)

# ════════════════════════════════════════════════
#  COMMANDS  ·  Contributeur
# ════════════════════════════════════════════════

@bot.command(name="tempmute")
async def tempmute_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`-tempmute <id>`"))
    try:
        uid_int = int(str(user_id).strip("<@!>"))
        member  = ctx.guild.get_member(uid_int) or await ctx.guild.fetch_member(uid_int)
    except: return await ctx.reply(embed=emb_err("Membre introuvable."))
    if member.id == ctx.author.id: return await ctx.reply(embed=emb_err("Tu ne peux pas te muter toi-même."))
    if is_sys_plus(member.id):     return await ctx.reply(embed=emb_err("Tu ne peux pas muter un Sys+."))
    e = discord.Embed(
        title=f"🔇  Tempmute  ·  {member.display_name}",
        description=f"`{SEP}`\n**Membre :** {member.mention} (`{member.id}`)\nSélectionne une raison :",
        color=C["mute"], timestamp=_ts(),
    )
    e.set_thumbnail(url=member.display_avatar.url)
    view = MuteReasonView(ctx.author.id, member)
    msg  = await ctx.reply(embed=e, view=view)
    view.message = msg


@bot.command(name="warn")
async def warn_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`-warn <id>`"))
    try:
        uid_int = int(str(user_id).strip("<@!>"))
        member  = ctx.guild.get_member(uid_int) or await ctx.guild.fetch_member(uid_int)
    except: return await ctx.reply(embed=emb_err("Membre introuvable."))
    if member.id == ctx.author.id: return await ctx.reply(embed=emb_err("Tu ne peux pas te warn toi-même."))
    if is_sys_plus(member.id):     return await ctx.reply(embed=emb_err("Tu ne peux pas warn un Sys+."))
    e = discord.Embed(
        title=f"⚠️  Warn  ·  {member.display_name}",
        description=f"`{SEP}`\n**Membre :** {member.mention} (`{member.id}`)\nSélectionne une raison :",
        color=C["warn"], timestamp=_ts(),
    )
    e.set_thumbnail(url=member.display_avatar.url)
    view = WarnReasonView(ctx.author.id, member)
    msg  = await ctx.reply(embed=e, view=view)
    view.message = msg


@bot.command(name="unmute")
async def unmute_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`-unmute <id>`"))
    try:
        uid_int = int(str(user_id).strip("<@!>"))
        member  = ctx.guild.get_member(uid_int) or await ctx.guild.fetch_member(uid_int)
    except: return await ctx.reply(embed=emb_err("Membre introuvable."))
    muted_role  = ctx.guild.get_role(MUTED_ROLE_ID)
    civile_role = ctx.guild.get_role(CIVILE_ROLE_ID)
    if not muted_role:
        return await ctx.reply(embed=emb_err("Rôle Muted introuvable. Vérifie la config."))
    try:
        await member.remove_roles(muted_role, reason=f"[UNMUTE]  par {ctx.author}")
        if civile_role and civile_role not in member.roles:
            await member.add_roles(civile_role, reason=f"[UNMUTE]  rôle Civile redonné")
    except discord.Forbidden:
        return await ctx.reply(embed=emb_err("Permissions insuffisantes."))

    now = now_ts()
    for sid, s in sanctions_db["sanctions"].items():
        if s["user_id"] == str(uid_int) and s["type"] == "tempmute" and s.get("active"):
            sanctions_db["sanctions"][sid]["active"] = False
    save_sanctions()

    dm_ok = await try_dm_text(member, "Vous avez de nouveau la permission de parler sur Shotojo 🌸 !")

    log_e = emb_log("✅  Unmute", C["ok"])
    log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`",        inline=True)
    log_e.add_field(name="🛡️ Par",   value=f"{ctx.author.mention}\n`{ctx.author.id}`", inline=True)
    log_e.add_field(name="📩 MP",     value="✅" if dm_ok else "❌",                   inline=True)
    log_e.set_thumbnail(url=member.display_avatar.url)
    await log(ctx.guild, log_e)
    result_e = emb_ok(f"✅  **{member}** n'est plus muté.")
    set_footer(result_e, ctx.author)
    await ctx.reply(embed=result_e)


@bot.command(name="sanction")
async def sanction_cmd(ctx, user_id: str = None):
    if not user_id: return await ctx.reply(embed=emb_err("`-sanction <id>`"))
    uid      = str(user_id).strip()
    slist    = get_user_sanctions(uid)
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None

    TYPE_EMOJI = {"tempmute": "🔇", "warn": "⚠️"}
    e = discord.Embed(
        title=f"📋  Historique des sanctions  ·  {name}",
        color=C["sanc"], timestamp=_ts(),
    )
    if not slist:
        e.description = f"`{SEP}`\nAucune sanction enregistrée."
    else:
        lines = []
        for s in slist[-15:]:
            em     = TYPE_EMOJI.get(s["type"], "❓")
            status = "🟢" if s.get("active") else "⬛"
            dur    = f" (`{s['duree_str']}`)" if s.get("duree_str") else ""
            lines.append(
                f"`#{s['id']}` {status} {em} **{s['type'].upper()}**{dur}\n"
                f"╰ {s['raison']}  ·  {fmt_rel(s['at'])}"
            )
        e.description = f"`{SEP}`\n" + "\n".join(lines)
        e.set_footer(text=f"Total : {len(slist)} sanction(s)")
    if avatar: e.set_thumbnail(url=avatar)
    await ctx.reply(embed=e)


@bot.command(name="infosanction")
async def infosanction_cmd(ctx, sanction_id: str = None, user_id: str = None):
    if not sanction_id or not user_id:
        return await ctx.reply(embed=emb_err("`-infosanction <n°> <id>`"))
    s = get_sanction(sanction_id)
    if not s or s["user_id"] != str(user_id).strip():
        return await ctx.reply(embed=emb_err("Sanction introuvable."))
    try: user = await bot.fetch_user(int(s["user_id"])); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({s['user_id']})"; avatar = None
    TYPE_EMOJI = {"tempmute": "🔇", "warn": "⚠️"}
    COLORS     = {"tempmute": C["mute"], "warn": C["warn"]}
    e = discord.Embed(
        title=f"{TYPE_EMOJI.get(s['type'], '❓')}  Sanction #{s['id']}  ·  {s['type'].upper()}",
        description=f"`{SEP}`",
        color=COLORS.get(s["type"], C["sanc"]),
        timestamp=_ts(),
    )
    e.add_field(name="👤 Membre",  value=f"`{name}`\n`{s['user_id']}`",                           inline=True)
    e.add_field(name="🛡️ Par",    value=f"<@{s['by_id']}>\n`{s['by_id']}`",                      inline=True)
    e.add_field(name="🔘 Statut",  value="🟢  Active" if s.get("active") else "⬛  Expirée",      inline=True)
    e.add_field(name="📅 Date",    value=f"{fmt(s['at'])}\n{fmt_rel(s['at'])}",                    inline=True)
    if s.get("duree_str"):
        e.add_field(name="⏱️ Durée", value=f"`{s['duree_str']}`",                                 inline=True)
    if s.get("until"):
        e.add_field(name="🔓 Fin",   value=f"{fmt(s['until'])}\n{fmt_rel(s['until'])}",            inline=True)
    e.add_field(name="📝 Raison",  value=s["raison"],                                               inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    set_footer(e, ctx.author)
    await ctx.reply(embed=e)


@bot.command(name="delsanction")
async def delsanction_cmd(ctx, sanction_id: str = None, user_id: str = None):
    if not sanction_id or not user_id:
        return await ctx.reply(embed=emb_err("`-delsanction <n°> <id>`"))
    s = get_sanction(sanction_id)
    if not s or s["user_id"] != str(user_id).strip():
        return await ctx.reply(embed=emb_err("Sanction introuvable."))
    sanctions_db["sanctions"].pop(str(sanction_id))
    save_sanctions()
    result_e = emb_ok(f"🗑️  Sanction `#{sanction_id}` supprimée.")
    set_footer(result_e, ctx.author)
    await ctx.reply(embed=result_e)
    log_e = emb_log("🗑️  Sanction supprimée", C["ban"])
    log_e.add_field(name="🆔 Sanction", value=f"`#{sanction_id}`",                            inline=True)
    log_e.add_field(name="📋 Type",     value=s["type"].upper(),                              inline=True)
    log_e.add_field(name="🛡️ Par",     value=f"{ctx.author.mention}\n`{ctx.author.id}`",     inline=True)
    await log(ctx.guild, log_e)

# ════════════════════════════════════════════════
#  COMMANDS  ·  Public
# ════════════════════════════════════════════════

@bot.command(name="help")
async def help_cmd(ctx):
    sys_plus = is_sys_plus(ctx.author.id)
    petale   = is_petale_or_plus(ctx.author)

    if sys_plus:
        e = discord.Embed(
            title="⬡  Commandes  ·  Sys+",
            description=f"`{SEP}`",
            color=C["sys"], timestamp=_ts(),
        )
        e.add_field(name="🚫  Bans  ·  Blacklist", inline=False, value=(
            "`+bl <id> <raison>`  ·  Blacklist  +  ban IP permanent\n"
            "`&unbl <id>`  ·  Retire une blacklist\n"
            "`-blinfo <id>`  ·  Infos blacklist\n"
            "`+ban <id> <durée> <raison>`  ·  Ban temporaire\n"
            "`+unban <id> [raison]`  ·  Déban un utilisateur\n"
            "`-baninfo <id>`  ·  Infos tempban\n"
            "`-banpanel`  ·  Panel de tous les bans"
        ))
        e.add_field(name="🌪️  Tempête", inline=False, value=(
            "`/tempete <id> <raison>`  ·  Ban IP définitif\n"
            "`/tempete-info <id>`  ·  Infos tempête\n"
            "`/untempete <id>`  ·  Retire une tempête\n"
            "`/unban-all`  ·  Déban tout sauf BL et tempêtes"
        ))
        e.add_field(name="🔇  Modération", inline=False, value=(
            "`-tempmute <id>`  ·  Mute temporaire\n"
            "`-unmute <id>`  ·  Unmute\n"
            "`-warn <id>`  ·  Avertissement\n"
            "`-sanction <id>`  ·  Historique des sanctions\n"
            "`-infosanction <n°> <id>`  ·  Détails d'une sanction\n"
            "`-delsanction <n°> <id>`  ·  Supprimer une sanction"
        ))
        e.add_field(name="⚙️  Bot", inline=False,
                    value="`-maintenance [on|off]`  ·  Mode maintenance")
    elif petale:
        e = discord.Embed(
            title="⬡  Commandes  ·  Contributeur",
            description=f"`{SEP}`",
            color=C["info"], timestamp=_ts(),
        )
        e.add_field(name="🔇  Modération", inline=False, value=(
            "`-tempmute <id>`  ·  Mute temporaire\n"
            "`-unmute <id>`  ·  Unmute\n"
            "`-warn <id>`  ·  Avertissement\n"
            "`-sanction <id>`  ·  Historique des sanctions\n"
            "`-infosanction <n°> <id>`  ·  Détails d'une sanction"
        ))
    else:
        e = discord.Embed(
            title="⬡  Aide",
            description="Tu n'as accès à aucune commande.",
            color=C["dark"], timestamp=_ts(),
        )
    e.set_footer(text=f"Demandé par {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.reply(embed=e)

# ════════════════════════════════════════════════
#  SLASH  ·  Sys+
# ════════════════════════════════════════════════

@tree.command(name="tempete", description="Tempête un membre  ·  ban IP définitif [Sys+]")
@app_commands.describe(user_id="ID Discord", raison="Raison")
async def tempete_slash(i: discord.Interaction, user_id: str, raison: str = "Aucune raison"):
    if not is_sys_plus(i.user.id):
        msg = await sys_violation(i.user)
        return await i.response.send_message(msg, ephemeral=True)
    try: user = await bot.fetch_user(int(user_id))
    except: return await i.response.send_message(embed=emb_err("ID invalide."), ephemeral=True)
    uid = str(user_id); now = now_ts()
    tempetes[uid]  = {"raison": raison, "by": str(i.user), "by_id": i.user.id, "at": now}
    blacklist[uid] = {"raison": f"[TEMPÊTE]  {raison}", "by": str(i.user), "by_id": i.user.id, "at": now}
    save(TEMPETE_FILE, tempetes); save(BL_FILE, blacklist)

    await try_dm_text(user, dm_text_tempete(raison, i.guild.name))

    try: await i.guild.ban(user, reason=f"[TEMPÊTE · Ban IP]  {raison}", delete_message_days=7)
    except discord.Forbidden:
        return await i.response.send_message(embed=emb_err("Permissions insuffisantes."), ephemeral=True)

    log_e = emb_log("🌪️  Tempête  ·  Ban IP", C["tempete"])
    log_e.add_field(name="👤 Membre", value=f"`{user}` (`{user_id}`)",                    inline=True)
    log_e.add_field(name="🛡️ Par",   value=f"{i.user.mention}\n`{i.user.id}`",           inline=True)
    log_e.add_field(name="📅 Date",   value=f"{fmt(now)}\n{fmt_rel(now)}",                inline=True)
    log_e.add_field(name="🌐 Type",   value="Ban IP permanent et définitif",              inline=True)
    log_e.add_field(name="📝 Raison", value=raison,                                        inline=False)
    log_e.set_thumbnail(url=user.display_avatar.url)
    await log(i.guild, log_e)

    result_e = discord.Embed(
        title="✦  Tempête exécutée",
        description=f"🌪️  **{user}** (`{user_id}`) mis sous tempête  ·  Ban IP\n📝 {raison}",
        color=C["tempete"], timestamp=_ts(),
    )
    set_footer(result_e, i.user)
    await i.response.send_message(embed=result_e)


@tree.command(name="tempete-info", description="Infos sur une tempête [Sys+]")
@app_commands.describe(user_id="ID Discord")
async def tempete_info_slash(i: discord.Interaction, user_id: str):
    if not is_sys_plus(i.user.id):
        msg = await sys_violation(i.user)
        return await i.response.send_message(msg, ephemeral=True)
    uid  = str(user_id).strip()
    data = tempetes.get(uid)
    if not data:
        return await i.response.send_message(embed=emb_err("Aucune tempête pour cet ID."), ephemeral=True)
    try: user = await bot.fetch_user(int(uid)); name = str(user); avatar = user.display_avatar.url
    except: name = f"Inconnu ({uid})"; avatar = None
    e = discord.Embed(title="🌪️  Infos Tempête  ·  Ban IP", color=C["tempete"], timestamp=_ts())
    e.description = f"`{SEP}`"
    e.add_field(name="👤 Membre", value=f"`{name}`\n`{uid}`",                               inline=True)
    e.add_field(name="🛡️ Par",   value=f"<@{data['by_id']}>\n`{data['by_id']}`",           inline=True)
    e.add_field(name="📅 Date",   value=f"{fmt(data['at'])}\n{fmt_rel(data['at'])}",         inline=True)
    e.add_field(name="🌐 Type",   value="Ban IP permanent et définitif",                     inline=True)
    e.add_field(name="📝 Raison", value=data["raison"],                                       inline=False)
    if avatar: e.set_thumbnail(url=avatar)
    await i.response.send_message(embed=e)


@tree.command(name="untempete", description="Retire une tempête [Sys+]")
@app_commands.describe(user_id="ID Discord")
async def untempete_slash(i: discord.Interaction, user_id: str):
    if not is_sys_plus(i.user.id):
        msg = await sys_violation(i.user)
        return await i.response.send_message(msg, ephemeral=True)
    uid = str(user_id).strip()
    if uid not in tempetes:
        return await i.response.send_message(embed=emb_err("Aucune tempête pour cet ID."), ephemeral=True)
    try: user = await bot.fetch_user(int(uid))
    except: return await i.response.send_message(embed=emb_err("ID invalide."), ephemeral=True)
    try: await i.guild.unban(user, reason=f"[UNTEMPÊTE]  par {i.user}")
    except discord.NotFound: pass
    except discord.Forbidden:
        return await i.response.send_message(embed=emb_err("Permissions insuffisantes."), ephemeral=True)
    data = tempetes.pop(uid)
    blacklist.pop(uid, None)
    save(TEMPETE_FILE, tempetes); save(BL_FILE, blacklist)
    invite = await make_invite(i.guild)
    desc   = f"Ta tempête sur **{i.guild.name}** a été levée.\nTu peux désormais rejoindre le serveur."
    if invite: desc += f"\n\n🔗 {invite}"
    dm_ok = await try_dm(user, discord.Embed(
        title="✅  Tempête levée  ·  Shotojo",
        description=desc,
        color=C["ok"], timestamp=_ts(),
    ))
    log_e = emb_log("✅  Untempête", C["ok"])
    log_e.add_field(name="👤 Membre",          value=f"`{user}` (`{uid}`)",                     inline=True)
    log_e.add_field(name="🛡️ Par",            value=f"{i.user.mention}\n`{i.user.id}`",         inline=True)
    log_e.add_field(name="📩 MP",              value="✅" if dm_ok else "❌",                    inline=True)
    log_e.add_field(name="📝 Raison initiale", value=data["raison"],                              inline=False)
    await log(i.guild, log_e)
    result_e = discord.Embed(
        title="✦  Tempête retirée",
        description=f"✅  **{user}** n'est plus sous tempête.",
        color=C["ok"], timestamp=_ts(),
    )
    set_footer(result_e, i.user)
    await i.response.send_message(embed=result_e)


@tree.command(name="unban-all", description="Déban tout sauf blacklist et tempêtes [Sys+]")
async def unban_all_slash(i: discord.Interaction):
    if not is_sys_plus(i.user.id):
        msg = await sys_violation(i.user)
        return await i.response.send_message(msg, ephemeral=True)
    await i.response.defer()
    protected = set(blacklist.keys()) | set(tempetes.keys())
    unbanned = skipped = failed = 0
    async for entry in i.guild.bans(limit=None):
        uid = str(entry.user.id)
        if uid in protected: skipped += 1; continue
        try:
            await i.guild.unban(entry.user, reason=f"[UNBAN-ALL]  par {i.user}")
            tempbans.pop(uid, None); unbanned += 1
        except Exception: failed += 1
        await asyncio.sleep(0.5)
    save(TEMPBAN_FILE, tempbans)
    log_e = emb_log("🔓  Unban-All", C["ok"])
    log_e.add_field(name="🛡️ Par",     value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
    log_e.add_field(name="✅ Débannis", value=str(unbanned),                       inline=True)
    log_e.add_field(name="🚫 Ignorés", value=str(skipped),                         inline=True)
    if failed: log_e.add_field(name="⚠️ Echecs", value=str(failed), inline=True)
    await log(i.guild, log_e)
    result_e = discord.Embed(
        title="✦  Unban-All terminé",
        description=(
            f"✅  {unbanned} débanni(s)\n"
            f"🚫  {skipped} ignoré(s) (BL  ·  Tempête)" +
            (f"\n⚠️  {failed} échec(s)" if failed else "")
        ),
        color=C["ok"], timestamp=_ts(),
    )
    set_footer(result_e, i.user)
    await i.followup.send(embed=result_e)

# ════════════════════════════════════════════════
#  LANCEMENT
# ════════════════════════════════════════════════
bot.run(os.environ["TOKEN"])
