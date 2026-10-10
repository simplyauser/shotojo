import discord
from discord import app_commands
import asyncio
import io
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
CATEGORY_ID = int(os.getenv("TICKETS_CATEGORY_ID", "0"))
LOGS_CHANNEL_ID = 1558332887000948757

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

open_tickets = {}
maintenance = False


def now() -> datetime:
    return datetime.now(timezone.utc)


def fmt(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y à %H:%M:%S UTC")


@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    print("✅ Slash commands synchronisées")


async def handle_dm(message):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    user_id = message.author.id

    # Ticket déjà ouvert → relay
    if user_id in open_tickets:
        channel = guild.get_channel(open_tickets[user_id]["channel_id"])
        if channel:
            embed = discord.Embed(
                description=message.content or "*[fichier joint]*",
                color=0x5865F2,
            )
            embed.set_author(
                name=str(message.author),
                icon_url=message.author.display_avatar.url,
            )
            if message.attachments:
                embed.set_image(url=message.attachments[0].url)
            await channel.send(embed=embed)
            open_tickets[user_id]["messages"].append({
                "time": now(),
                "author": str(message.author),
                "role": "Membre",
                "content": message.content or "[fichier joint]",
            })
        return

    # Nouveau ticket
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True
        ),
    }
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True
            )

    category = guild.get_channel(CATEGORY_ID) if CATEGORY_ID else None
    channel_name = f"ticket-{message.author.name}".lower()[:32]

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=f"{message.author} | {user_id}",
    )

    opened_at = now()
    open_tickets[user_id] = {
        "channel_id": channel.id,
        "opened_at": opened_at,
        "member": str(message.author),
        "member_id": user_id,
        "messages": [{
            "time": opened_at,
            "author": str(message.author),
            "role": "Membre",
            "content": message.content or "[fichier joint]",
        }],
        "mods": set(),
    }

    embed = discord.Embed(
        title="📩 Nouveau ticket",
        description=message.content or "*[fichier joint]*",
        color=0x5865F2,
    )
    embed.set_author(
        name=f"{message.author} ({user_id})",
        icon_url=message.author.display_avatar.url,
    )
    embed.set_footer(text="Répondez ici · /fermer pour clore le ticket")
    if message.attachments:
        embed.set_image(url=message.attachments[0].url)

    await channel.send("@here", embed=embed)
    await message.author.send(
        "✅ Ton message a bien été reçu ! Un membre du staff va te répondre dès que possible. 🙏"
    )


async def relay_to_user(message: discord.Message):
    user_id = next(
        (uid for uid, data in open_tickets.items() if data["channel_id"] == message.channel.id),
        None,
    )
    if user_id is None:
        return

    open_tickets[user_id]["mods"].add(str(message.author))
    open_tickets[user_id]["messages"].append({
        "time": now(),
        "author": str(message.author),
        "role": "Staff",
        "content": message.content or "[fichier joint]",
    })

    try:
        await message.delete()
    except discord.Forbidden:
        pass

    user = bot.get_user(user_id)
    if not user:
        return

    try:
        embed = discord.Embed(
            description=message.content or "*[fichier joint]*",
            color=0x57F287,
        )
        embed.set_author(name="Support", icon_url=bot.user.display_avatar.url)
        if message.attachments:
            embed.set_image(url=message.attachments[0].url)
        await user.send(embed=embed)
    except discord.Forbidden:
        await message.channel.send("⚠️ Impossible d'envoyer le message, l'utilisateur a ses DMs fermés.")


# Intercepter les messages dans les salons tickets
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        if maintenance:
            await message.author.send(
                "🔧 Le support est actuellement en **maintenance**.\n"
                "Reviens un peu plus tard, on sera de retour rapidement ! 🙏"
            )
            return
        await handle_dm(message)
    else:
        # Vérifier si c'est un salon ticket
        is_ticket = any(data["channel_id"] == message.channel.id for data in open_tickets.values())
        if is_ticket:
            await relay_to_user(message)


def ts(dt: datetime) -> str:
    """Timestamp Discord cliquable format long."""
    return f"<t:{int(dt.timestamp())}:F>"


def ts_relative(dt: datetime) -> str:
    """Timestamp Discord relatif (il y a X minutes)."""
    return f"<t:{int(dt.timestamp())}:R>"


def duration_str(opened: datetime, closed: datetime) -> str:
    delta = closed - opened
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}min {s}s"
    elif m:
        return f"{m}min {s}s"
    else:
        return f"{s}s"


def build_transcript(data: dict, closed_at: datetime, closed_by: str) -> str:
    dur = duration_str(data["opened_at"], closed_at)
    mods = ", ".join(data["mods"]) if data["mods"] else "Aucun"
    lines = []
    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║               📋  TRANSCRIPT DE TICKET                  ║")
    lines.append("╚══════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  👤  Membre       : {data['member']}  (ID : {data['member_id']})")
    lines.append(f"  🕐  Ouvert le    : {fmt(data['opened_at'])}")
    lines.append(f"  🔒  Fermé le     : {fmt(closed_at)}")
    lines.append(f"  ⏱️   Durée        : {dur}")
    lines.append(f"  🛡️   Fermé par    : {closed_by}")
    lines.append(f"  👥  Staff actif  : {mods}")
    lines.append(f"  💬  Messages     : {len(data['messages'])}")
    lines.append("")
    lines.append("┌──────────────────────────────────────────────────────────┐")
    lines.append("│                        MESSAGES                          │")
    lines.append("└──────────────────────────────────────────────────────────┘")
    lines.append("")
    for msg in data["messages"]:
        icon = "👤" if msg["role"] == "Membre" else "🛡️"
        lines.append(f"{icon}  [{msg['role']}] {msg['author']}")
        lines.append(f"    🕐 {fmt(msg['time'])}")
        lines.append(f"    💬 {msg['content']}")
        lines.append("")
    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║                    FIN DU TRANSCRIPT                     ║")
    lines.append("╚══════════════════════════════════════════════════════════╝")
    return "\n".join(lines)


CLOSING_FRAMES = [
    "🔒 Fermeture du ticket dans **5**... ⏳",
    "🔒 Fermeture du ticket dans **4**... ⌛",
    "🔒 Fermeture du ticket dans **3**... ⏳",
    "🔒 Fermeture du ticket dans **2**... ⌛",
    "🔒 Fermeture du ticket dans **1**... ⏳",
    "💥 Fermeture en cours... 🔐",
    "🗑️ Suppression du salon... 🚨",
]


@tree.command(name="fermer", description="Ferme et supprime le ticket actuel")
@app_commands.checks.has_permissions(administrator=True)
async def fermer(interaction: discord.Interaction):
    user_id = next(
        (uid for uid, data in open_tickets.items() if data["channel_id"] == interaction.channel.id),
        None,
    )
    if user_id is None:
        await interaction.response.send_message("❌ Ce salon n'est pas un ticket.", ephemeral=True)
        return

    data = open_tickets.pop(user_id)
    closed_at = now()

    await interaction.response.send_message(CLOSING_FRAMES[0])
    msg = await interaction.original_response()

    for frame in CLOSING_FRAMES[1:]:
        await asyncio.sleep(1)
        await msg.edit(content=frame)

    # Notifier le membre
    user = bot.get_user(user_id)
    if user:
        try:
            await user.send(
                "🔒 Ton ticket a été **fermé** par le staff.\n"
                "➡️ N'hésite pas à revenir si tu as besoin d'aide ! 👋"
            )
        except discord.Forbidden:
            pass

    # Logs + transcript
    logs_channel = interaction.guild.get_channel(LOGS_CHANNEL_ID)
    if logs_channel:
        transcript = build_transcript(data, closed_at, str(interaction.user))
        filename = f"transcript-{data['member'].replace('#', '').replace(' ', '_')}-{closed_at.strftime('%Y%m%d-%H%M%S')}.txt"
        file = discord.File(fp=io.BytesIO(transcript.encode("utf-8")), filename=filename)

        dur = duration_str(data["opened_at"], closed_at)
        mods = "\n".join(f"• {m}" for m in data["mods"]) if data["mods"] else "*Aucun*"
        nb_msg_membre = sum(1 for m in data["messages"] if m["role"] == "Membre")
        nb_msg_staff  = sum(1 for m in data["messages"] if m["role"] == "Staff")

        embed = discord.Embed(
            title="🔒 Ticket fermé",
            color=0xED4245,
            timestamp=closed_at,
        )
        embed.add_field(
            name="👤 Membre",
            value=f"<@{data['member_id']}>\n`{data['member']}` • `{data['member_id']}`",
            inline=True,
        )
        embed.add_field(
            name="🛡️ Fermé par",
            value=f"{interaction.user.mention}\n`{interaction.user}`",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        embed.add_field(
            name="🕐 Ouvert",
            value=f"{ts(data['opened_at'])}\n{ts_relative(data['opened_at'])}",
            inline=True,
        )
        embed.add_field(
            name="🔒 Fermé",
            value=f"{ts(closed_at)}\n{ts_relative(closed_at)}",
            inline=True,
        )
        embed.add_field(
            name="⏱️ Durée",
            value=f"`{dur}`",
            inline=True,
        )
        embed.add_field(
            name="💬 Messages",
            value=f"👤 Membre : **{nb_msg_membre}**\n🛡️ Staff : **{nb_msg_staff}**\n📊 Total : **{len(data['messages'])}**",
            inline=True,
        )
        embed.add_field(
            name="👥 Staff ayant répondu",
            value=mods,
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        embed.set_thumbnail(url=f"https://cdn.discordapp.com/avatars/{data['member_id']}/avatar.png")
        embed.set_footer(text=f"ID ticket : {data['channel_id']} • Transcript en pièce jointe")

        await logs_channel.send(embed=embed, file=file)

    await asyncio.sleep(1)
    await interaction.channel.delete()


@tree.command(name="maintenance", description="Active ou désactive le mode maintenance")
@app_commands.checks.has_permissions(administrator=True)
async def toggle_maintenance(interaction: discord.Interaction):
    global maintenance
    maintenance = not maintenance
    if maintenance:
        await bot.change_presence(
            status=discord.Status.do_not_disturb,
            activity=discord.Game("🔧 Maintenance en cours")
        )
        await interaction.response.send_message("🔧 Maintenance **activée** — le bot ne répond plus aux DMs.", ephemeral=True)
    else:
        await bot.change_presence(status=discord.Status.online, activity=None)
        await interaction.response.send_message("✅ Maintenance **désactivée** — le bot est de retour.", ephemeral=True)


@fermer.error
@toggle_maintenance.error
async def on_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)


bot.run(TOKEN)
