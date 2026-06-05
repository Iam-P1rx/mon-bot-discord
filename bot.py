"""
╔══════════════════════════════════════════════════════╗
║           BOT DISCORD - MODÉRATION COMPLÈTE          ║
║  Requires: pip install discord.py aiofiles           ║
╚══════════════════════════════════════════════════════╝

CONFIGURATION RAPIDE :
  1. Remplis les variables dans la section CONFIG ci-dessous
  2. Lance : python bot.py

COMMANDES DISPONIBLES :
  !ban @user        → Modal : raison
  !mute @user       → Modal : durée + raison
  !unmute @user     → Retire le mute
  !kick @user       → Modal : raison
  !warn @user       → Modal : raison
  !gs               → Démarre un giveaway (Modal)
  !ge #salon        → Termine un giveaway
  !gr #salon        → Reroll un giveaway
  !help             → Panneau d'aide complet
  !ticket           → Panneau ticket (menu déroulant)
  !setowner @user   → Définit le propriétaire du bot
  !antiraid on/off  → Active/désactive l'anti-raid
  !logs #salon      → Définit le salon des logs
  !transcripts #s   → Définit le salon des transcriptions
  !welcome #salon   → Définit le salon de bienvenue
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
import datetime
import random
import string
from collections import defaultdict

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args):
        pass

threading.Thread(target=lambda: HTTPServer(('', 8080), H).serve_forever(), daemon=True).start()


# ═══════════════════════════════════════════════════
#                     CONFIG
# ═══════════════════════════════════════════════════

BOT_TOKEN = os.getenv("DISCORD_TOKEN")          # Token du bot (Discord Developer Portal)
PREFIX = "!"                          # Préfixe des commandes
DATA_FILE = "bot_data.json"           # Fichier de sauvegarde des données

# ═══════════════════════════════════════════════════
#              CHARGEMENT DES DONNÉES
# ═══════════════════════════════════════════════════

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "owner_id": None,
        "guilds": {}
    }

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_guild(guild_id: int) -> dict:
    gid = str(guild_id)
    if gid not in data["guilds"]:
        data["guilds"][gid] = {
            "log_channel": None,
            "welcome_channel": None,
            "transcript_channel": None,
            "muted_role": None,
            "ticket_counter": 0,
            "tickets": {},
            "giveaways": {},
            "warns": {},
            "antiraid": {
                "enabled": False,
                "join_threshold": 10,
                "join_window": 10,
                "action": "kick"
            }
        }
        save_data()
    return data["guilds"][gid]

data = load_data()

# ═══════════════════════════════════════════════════
#              ANTI-RAID : TRACKING
# ═══════════════════════════════════════════════════

# Dictionnaire : guild_id → liste des timestamps de join
join_tracker: dict[int, list] = defaultdict(list)

# ═══════════════════════════════════════════════════
#              INTENTS & BOT
# ═══════════════════════════════════════════════════

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ═══════════════════════════════════════════════════
#              HELPERS
# ═══════════════════════════════════════════════════

def is_owner_or_admin():
    async def predicate(ctx):
        if ctx.author.id == data.get("owner_id"):
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        raise commands.MissingPermissions(["administrator"])
    return commands.check(predicate)

async def get_or_create_muted_role(guild: discord.Guild) -> discord.Role:
    gd = get_guild(guild.id)
    role_id = gd.get("muted_role")
    if role_id:
        role = guild.get_role(role_id)
        if role:
            return role
    # Crée le rôle Muted
    role = await guild.create_role(name="Muted", color=discord.Color.dark_gray(), reason="Bot: création rôle Muted")
    gd["muted_role"] = role.id
    save_data()
    # Supprime les permissions d'envoi dans tous les salons
    for channel in guild.channels:
        try:
            await channel.set_permissions(role, send_messages=False, speak=False, add_reactions=False)
        except Exception:
            pass
    return role

async def send_log(guild: discord.Guild, embed: discord.Embed):
    gd = get_guild(guild.id)
    ch_id = gd.get("log_channel")
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

def embed_base(title: str, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
    e = discord.Embed(title=title, color=color, timestamp=datetime.datetime.utcnow())
    e.set_footer(text="Système de Modération")
    return e

# ═══════════════════════════════════════════════════
#              MODALS
# ═══════════════════════════════════════════════════

class BanModal(discord.ui.Modal, title="🔨 Bannir un membre"):
    reason = discord.ui.TextInput(
        label="Raison du bannissement",
        placeholder="Ex : Spam, insultes, comportement toxique...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value
        try:
            try:
                await self.member.send(
                    embed=embed_base(f"🔨 Tu as été banni de **{interaction.guild.name}**", discord.Color.red())
                    .add_field(name="Raison", value=reason_text)
                    .add_field(name="Modérateur", value=interaction.user.mention)
                )
            except Exception:
                pass
            await self.member.ban(reason=f"{reason_text} | Mod: {interaction.user}")
            e = embed_base("🔨 Membre Banni", discord.Color.red())
            e.add_field(name="Membre", value=f"{self.member} (`{self.member.id}`)")
            e.add_field(name="Modérateur", value=interaction.user.mention)
            e.add_field(name="Raison", value=reason_text, inline=False)
            await interaction.response.send_message(embed=e)
            await send_log(interaction.guild, e)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission de bannir ce membre.", ephemeral=True)


class MuteModal(discord.ui.Modal, title="🔇 Muter un membre"):
    duration = discord.ui.TextInput(
        label="Durée",
        placeholder="Ex : 10m, 1h, 2d (m=minutes, h=heures, d=jours)",
        max_length=10,
        required=True
    )
    reason = discord.ui.TextInput(
        label="Raison",
        placeholder="Ex : Spam, flood...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        dur_str = self.duration.value.strip().lower()
        reason_text = self.reason.value

        # Parse la durée
        seconds = 0
        try:
            if dur_str.endswith("d"):
                seconds = int(dur_str[:-1]) * 86400
            elif dur_str.endswith("h"):
                seconds = int(dur_str[:-1]) * 3600
            elif dur_str.endswith("m"):
                seconds = int(dur_str[:-1]) * 60
            elif dur_str.endswith("s"):
                seconds = int(dur_str[:-1])
            else:
                seconds = int(dur_str) * 60
        except ValueError:
            await interaction.response.send_message("❌ Durée invalide. Exemples : `10m`, `2h`, `1d`", ephemeral=True)
            return

        muted_role = await get_or_create_muted_role(interaction.guild)
        await self.member.add_roles(muted_role, reason=f"{reason_text} | Mod: {interaction.user}")

        e = embed_base("🔇 Membre Muté", discord.Color.orange())
        e.add_field(name="Membre", value=f"{self.member} (`{self.member.id}`)")
        e.add_field(name="Durée", value=dur_str)
        e.add_field(name="Modérateur", value=interaction.user.mention)
        e.add_field(name="Raison", value=reason_text, inline=False)
        await interaction.response.send_message(embed=e)
        await send_log(interaction.guild, e)

        # Démute automatiquement après la durée
        if seconds > 0:
            await asyncio.sleep(seconds)
            try:
                await self.member.remove_roles(muted_role, reason="Fin du mute automatique")
                e2 = embed_base("🔊 Membre Démuté (auto)", discord.Color.green())
                e2.add_field(name="Membre", value=f"{self.member} (`{self.member.id}`)")
                await send_log(interaction.guild, e2)
            except Exception:
                pass


class KickModal(discord.ui.Modal, title="👢 Expulser un membre"):
    reason = discord.ui.TextInput(
        label="Raison",
        placeholder="Ex : Comportement inapproprié...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value
        try:
            try:
                await self.member.send(
                    embed=embed_base(f"👢 Tu as été expulsé de **{interaction.guild.name}**", discord.Color.orange())
                    .add_field(name="Raison", value=reason_text)
                )
            except Exception:
                pass
            await self.member.kick(reason=f"{reason_text} | Mod: {interaction.user}")
            e = embed_base("👢 Membre Expulsé", discord.Color.orange())
            e.add_field(name="Membre", value=f"{self.member} (`{self.member.id}`)")
            e.add_field(name="Modérateur", value=interaction.user.mention)
            e.add_field(name="Raison", value=reason_text, inline=False)
            await interaction.response.send_message(embed=e)
            await send_log(interaction.guild, e)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Je n'ai pas la permission d'expulser ce membre.", ephemeral=True)


class WarnModal(discord.ui.Modal, title="⚠️ Avertir un membre"):
    reason = discord.ui.TextInput(
        label="Raison de l'avertissement",
        placeholder="Ex : Non-respect des règles...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member

    async def on_submit(self, interaction: discord.Interaction):
        reason_text = self.reason.value
        gd = get_guild(interaction.guild.id)
        uid = str(self.member.id)
        if uid not in gd["warns"]:
            gd["warns"][uid] = []
        gd["warns"][uid].append({
            "reason": reason_text,
            "mod": str(interaction.user),
            "date": datetime.datetime.utcnow().isoformat()
        })
        save_data()
        warn_count = len(gd["warns"][uid])
        try:
            await self.member.send(
                embed=embed_base(f"⚠️ Avertissement sur **{interaction.guild.name}**", discord.Color.yellow())
                .add_field(name="Raison", value=reason_text)
                .add_field(name="Total avertissements", value=str(warn_count))
            )
        except Exception:
            pass
        e = embed_base("⚠️ Avertissement", discord.Color.yellow())
        e.add_field(name="Membre", value=f"{self.member} (`{self.member.id}`)")
        e.add_field(name="Modérateur", value=interaction.user.mention)
        e.add_field(name="Raison", value=reason_text, inline=False)
        e.add_field(name="Total warns", value=str(warn_count))
        await interaction.response.send_message(embed=e)
        await send_log(interaction.guild, e)


# ═══════════════════════════════════════════════════
#              GIVEAWAY
# ═══════════════════════════════════════════════════

class GiveawayModal(discord.ui.Modal, title="🎉 Créer un Giveaway"):
    duration = discord.ui.TextInput(
        label="Durée",
        placeholder="Ex : 10m, 2h, 1d",
        max_length=10,
        required=True
    )
    prize = discord.ui.TextInput(
        label="Prix / Récompense",
        placeholder="Ex : Nitro Discord, 20€ Steam...",
        max_length=200,
        required=True
    )
    host = discord.ui.TextInput(
        label="Organisateur (host)",
        placeholder="Ex : @NomDuStaff ou Auto",
        max_length=100,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        dur_str = self.duration.value.strip().lower()
        prize_text = self.prize.value
        host_text = self.host.value

        seconds = 0
        try:
            if dur_str.endswith("d"):
                seconds = int(dur_str[:-1]) * 86400
            elif dur_str.endswith("h"):
                seconds = int(dur_str[:-1]) * 3600
            elif dur_str.endswith("m"):
                seconds = int(dur_str[:-1]) * 60
            else:
                seconds = int(dur_str) * 60
        except ValueError:
            await interaction.response.send_message("❌ Durée invalide.", ephemeral=True)
            return

        ends_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)

        e = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=(
                f"**Prix :** {prize_text}\n"
                f"**Host :** {host_text}\n"
                f"**Fin :** <t:{int(ends_at.timestamp())}:R>\n\n"
                f"Réagis avec 🎉 pour participer !"
            ),
            color=discord.Color.gold(),
            timestamp=ends_at
        )
        e.set_footer(text=f"Fin le")

        await interaction.response.send_message(embed=e)
        msg = await interaction.original_response()
        await msg.add_reaction("🎉")

        gd = get_guild(interaction.guild.id)
        gd["giveaways"][str(msg.id)] = {
            "channel_id": interaction.channel.id,
            "prize": prize_text,
            "host": host_text,
            "ends_at": ends_at.isoformat(),
            "ended": False
        }
        save_data()

        # Attend la fin et tire un gagnant
        await asyncio.sleep(seconds)
        await end_giveaway(interaction.guild, msg.id)


async def end_giveaway(guild: discord.Guild, msg_id: int, reroll: bool = False):
    gd = get_guild(guild.id)
    entry = gd["giveaways"].get(str(msg_id))
    if not entry:
        return None

    ch = guild.get_channel(entry["channel_id"])
    if not ch:
        return None

    try:
        msg = await ch.fetch_message(msg_id)
    except Exception:
        return None

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if not reaction:
        winner = None
    else:
        users = [u async for u in reaction.users() if not u.bot]
        winner = random.choice(users) if users else None

    if winner:
        if reroll:
            txt = f"🎉 **Reroll !** Le nouveau gagnant est {winner.mention} ! Félicitations pour **{entry['prize']}** !"
        else:
            txt = f"🎉 Félicitations {winner.mention} ! Tu as gagné **{entry['prize']}** !"
            gd["giveaways"][str(msg_id)]["ended"] = True
            save_data()
        await ch.send(txt)
    else:
        await ch.send("❌ Aucun participant valide pour ce giveaway.")

    return winner


# ═══════════════════════════════════════════════════
#              TICKETS - VIEWS
# ═══════════════════════════════════════════════════

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Staff", description="Contacter l'équipe Staff", emoji="🛡️"),
            discord.SelectOption(label="Bugs", description="Signaler un bug ou problème technique", emoji="🐛"),
            discord.SelectOption(label="Owner", description="Contacter le propriétaire du serveur", emoji="👑"),
        ]
        super().__init__(
            placeholder="📋 Choisir le type de ticket...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select"
        )

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        guild = interaction.guild
        gd = get_guild(guild.id)

        # Incrémente le compteur de tickets
        gd["ticket_counter"] += 1
        ticket_num = gd["ticket_counter"]
        save_data()

        # Cherche ou crée la catégorie "Tickets" dans Discord
        ticket_category = discord.utils.get(guild.categories, name="Tickets")
        if not ticket_category:
            ticket_category = await guild.create_category("Tickets")

        # Crée le salon
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        # Ajoute les admins
        for role in guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"ticket-{ticket_num}",
            category=ticket_category,
            overwrites=overwrites,
            topic=f"Ticket #{ticket_num} | Type: {category} | Créé par: {interaction.user}"
        )

        # Sauvegarde le ticket
        gd["tickets"][str(channel.id)] = {
            "number": ticket_num,
            "type": category,
            "creator_id": interaction.user.id,
            "creator_name": str(interaction.user),
            "claimed_by_id": None,
            "claimed_by_name": None,
            "messages": [],
            "opened_at": datetime.datetime.utcnow().isoformat(),
            "closed": False
        }
        save_data()

        # Embed dans le salon ticket
        e = discord.Embed(
            title=f"🎫 Ticket #{ticket_num} — {category}",
            description=(
                f"Bienvenue {interaction.user.mention} !\n\n"
                f"**Type :** {category}\n"
                f"Ton ticket a été créé. Un membre du staff va bientôt te répondre.\n\n"
                f"*Décris ton problème ci-dessous en détail.*"
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.utcnow()
        )
        e.set_footer(text=f"Ticket #{ticket_num}")

        view = TicketControlView(channel.id)
        await channel.send(f"{interaction.user.mention}", embed=e, view=view)
        await interaction.response.send_message(
            f"✅ Ton ticket a été créé : {channel.mention}", ephemeral=True
        )


class TicketControlView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="✅ Claim", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        gd = get_guild(interaction.guild.id)
        ticket = gd["tickets"].get(str(self.channel_id))
        if not ticket:
            await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)
            return
        if ticket["claimed_by_id"]:
            await interaction.response.send_message(
                f"❌ Ce ticket est déjà claim par <@{ticket['claimed_by_id']}>.", ephemeral=True
            )
            return
        ticket["claimed_by_id"] = interaction.user.id
        ticket["claimed_by_name"] = str(interaction.user)
        save_data()
        e = embed_base("✅ Ticket Claim", discord.Color.green())
        e.description = f"{interaction.user.mention} a pris en charge ce ticket."
        await interaction.response.send_message(embed=e)

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        gd = get_guild(interaction.guild.id)
        ticket = gd["tickets"].get(str(self.channel_id))
        if not ticket:
            await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)
            return
        if ticket["closed"]:
            await interaction.response.send_message("❌ Ce ticket est déjà fermé.", ephemeral=True)
            return

        await interaction.response.send_message("🔒 Fermeture du ticket en cours, génération de la transcription...")

        # Collecte les messages
        messages_log = []
        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            if not msg.author.bot:
                messages_log.append({
                    "author": str(msg.author),
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat()
                })

        ticket["messages"] = messages_log
        ticket["closed"] = True
        save_data()

        # Envoie la transcription
        await send_transcript(interaction.guild, ticket, interaction.channel.name)

        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason="Ticket fermé")
        except Exception:
            pass


async def send_transcript(guild: discord.Guild, ticket: dict, channel_name: str):
    gd = get_guild(guild.id)
    ch_id = gd.get("transcript_channel")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return

    # Construction de la transcription en texte
    lines = [
        "═" * 60,
        f"  TRANSCRIPTION — {channel_name.upper()}",
        "═" * 60,
        f"  Ticket #       : {ticket['number']}",
        f"  Type           : {ticket['type']}",
        f"  Créé par       : {ticket['creator_name']} (ID: {ticket['creator_id']})",
        f"  Claim par      : {ticket.get('claimed_by_name') or 'Non claim'} (ID: {ticket.get('claimed_by_id') or 'N/A'})",
        f"  Ouvert le      : {ticket['opened_at']}",
        "═" * 60,
        "",
        "  MESSAGES",
        "─" * 60,
    ]

    for msg in ticket.get("messages", []):
        ts = msg["timestamp"][:19].replace("T", " ")
        lines.append(f"  [{ts}] {msg['author']} : {msg['content']}")

    lines += ["", "═" * 60, "  FIN DE LA TRANSCRIPTION", "═" * 60]
    transcript_text = "\n".join(lines)

    # Envoie en fichier + embed résumé
    import io
    file_content = transcript_text.encode("utf-8")
    file = discord.File(io.BytesIO(file_content), filename=f"transcript-{channel_name}.txt")

    e = embed_base(f"📋 Transcription — {channel_name}", discord.Color.blurple())
    e.add_field(name="Créé par", value=f"{ticket['creator_name']} (`{ticket['creator_id']}`)")
    e.add_field(name="Claim par", value=ticket.get("claimed_by_name") or "Non claim")
    e.add_field(name="Type", value=ticket["type"])
    e.add_field(name="Messages", value=str(len(ticket.get("messages", []))))
    await ch.send(embed=e, file=file)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# ═══════════════════════════════════════════════════
#              HELP VIEW
# ═══════════════════════════════════════════════════

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.page = 0
        self.pages = [
            self._page_moderation(),
            self._page_giveaway(),
            self._page_tickets(),
            self._page_config(),
        ]

    def _page_moderation(self):
        e = embed_base("📖 Aide — Modération", discord.Color.red())
        e.add_field(name="!ban @membre", value="Bannir un membre (modal raison)", inline=False)
        e.add_field(name="!mute @membre", value="Muter un membre (modal durée + raison)", inline=False)
        e.add_field(name="!unmute @membre", value="Retirer le mute d'un membre", inline=False)
        e.add_field(name="!kick @membre", value="Expulser un membre (modal raison)", inline=False)
        e.add_field(name="!warn @membre", value="Avertir un membre (modal raison)", inline=False)
        e.add_field(name="!warns @membre", value="Voir les avertissements d'un membre", inline=False)
        e.set_footer(text="Page 1/4 — Modération")
        return e

    def _page_giveaway(self):
        e = embed_base("🎉 Aide — Giveaway", discord.Color.gold())
        e.add_field(name="!gs", value="Démarrer un giveaway (modal : durée, prix, host)", inline=False)
        e.add_field(name="!ge #salon", value="Terminer le giveaway en cours dans le salon", inline=False)
        e.add_field(name="!gr #salon", value="Reroll le gagnant du dernier giveaway", inline=False)
        e.add_field(name="Durées", value="`10m` = 10 min | `2h` = 2h | `1d` = 1 jour", inline=False)
        e.set_footer(text="Page 2/4 — Giveaway")
        return e

    def _page_tickets(self):
        e = embed_base("🎫 Aide — Tickets", discord.Color.blurple())
        e.add_field(name="!ticket", value="Afficher le panneau de création de ticket", inline=False)
        e.add_field(name="Types", value="Staff 🛡️ | Bugs 🐛 | Owner 👑", inline=False)
        e.add_field(name="Fonctionnement", value="Un salon `ticket-N` est créé automatiquement.\nLe staff peut **claim** et **fermer** le ticket.\nUne transcription est envoyée à la fermeture.", inline=False)
        e.set_footer(text="Page 3/4 — Tickets")
        return e

    def _page_config(self):
        e = embed_base("⚙️ Aide — Configuration", discord.Color.teal())
        e.add_field(name="!setowner @membre", value="Définir le propriétaire du bot", inline=False)
        e.add_field(name="!logs #salon", value="Définir le salon des logs de modération", inline=False)
        e.add_field(name="!transcripts #salon", value="Définir le salon des transcriptions", inline=False)
        e.add_field(name="!welcome #salon", value="Définir le salon de bienvenue", inline=False)
        e.add_field(name="!antiraid on/off", value="Activer/désactiver l'anti-raid", inline=False)
        e.set_footer(text="Page 4/4 — Configuration")
        return e

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)


# ═══════════════════════════════════════════════════
#              EVENTS
# ═══════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user} ({bot.user.id})")
    print(f"   Serveurs : {len(bot.guilds)}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=f"!help | {len(bot.guilds)} serveurs"
    ))


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    gd = get_guild(guild.id)

    # ── Anti-raid ──────────────────────────────────
    ar = gd["antiraid"]
    if ar["enabled"]:
        now = datetime.datetime.utcnow().timestamp()
        join_tracker[guild.id].append(now)
        # Nettoie les entrées hors fenêtre
        join_tracker[guild.id] = [t for t in join_tracker[guild.id] if now - t <= ar["join_window"]]
        if len(join_tracker[guild.id]) >= ar["join_threshold"]:
            # Raid détecté
            e_raid = embed_base("🚨 ANTI-RAID DÉCLENCHÉ", discord.Color.red())
            e_raid.description = (
                f"**{len(join_tracker[guild.id])} membres** ont rejoint en **{ar['join_window']}s** !\n"
                f"Action : **{ar['action'].upper()}**"
            )
            await send_log(guild, e_raid)
            # Kick/ban les nouveaux membres récents
            for t in join_tracker[guild.id]:
                for m in guild.members:
                    if m.joined_at and abs(m.joined_at.timestamp() - t) < 2:
                        try:
                            if ar["action"] == "ban":
                                await m.ban(reason="Anti-Raid automatique")
                            else:
                                await m.kick(reason="Anti-Raid automatique")
                        except Exception:
                            pass
            join_tracker[guild.id].clear()
            return

    # ── Message de bienvenue ───────────────────────
    ch_id = gd.get("welcome_channel")
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            e = discord.Embed(
                title=f"👋 Bienvenue sur **{guild.name}** !",
                description=(
                    f"Salut {member.mention}, bienvenue parmi nous ! 🎉\n\n"
                    f"Tu es le **{guild.member_count}ème** membre du serveur.\n"
                    f"N'oublie pas de lire les règles et de te présenter !"
                ),
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            if member.display_avatar:
                e.set_thumbnail(url=member.display_avatar.url)
            e.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
            try:
                await ch.send(embed=e)
            except Exception:
                pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.", delete_after=5)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Membre introuvable.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant : `{error.param.name}`.", delete_after=5)
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Tu n'as pas accès à cette commande.", delete_after=5)


# ═══════════════════════════════════════════════════
#              COMMANDES — MODÉRATION
# ═══════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member):
    """Bannir un membre via un modal."""
    await ctx.message.delete()
    modal = BanModal(member)
    # On ne peut pas ouvrir un modal via ctx directement, on utilise un bouton
    view = _ModalTriggerView(modal, f"🔨 Bannir {member.display_name}", discord.ButtonStyle.danger)
    await ctx.send(f"Clique pour ouvrir le formulaire de bannissement de **{member}** :", view=view, delete_after=30)


@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member):
    """Muter un membre via un modal."""
    await ctx.message.delete()
    modal = MuteModal(member)
    view = _ModalTriggerView(modal, f"🔇 Muter {member.display_name}", discord.ButtonStyle.primary)
    await ctx.send(f"Clique pour ouvrir le formulaire de mute de **{member}** :", view=view, delete_after=30)


@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    """Retirer le mute d'un membre."""
    gd = get_guild(ctx.guild.id)
    role_id = gd.get("muted_role")
    muted_role = ctx.guild.get_role(role_id) if role_id else None
    if not muted_role:
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if muted_role and muted_role in member.roles:
        await member.remove_roles(muted_role, reason=f"Démute par {ctx.author}")
        e = embed_base("🔊 Membre Démuté", discord.Color.green())
        e.add_field(name="Membre", value=f"{member} (`{member.id}`)")
        e.add_field(name="Modérateur", value=ctx.author.mention)
        await ctx.send(embed=e)
        await send_log(ctx.guild, e)
    else:
        await ctx.send(f"❌ {member.mention} n'est pas muté.", delete_after=5)


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member):
    """Expulser un membre via un modal."""
    await ctx.message.delete()
    modal = KickModal(member)
    view = _ModalTriggerView(modal, f"👢 Expulser {member.display_name}", discord.ButtonStyle.danger)
    await ctx.send(f"Clique pour ouvrir le formulaire d'expulsion de **{member}** :", view=view, delete_after=30)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member):
    """Avertir un membre via un modal."""
    await ctx.message.delete()
    modal = WarnModal(member)
    view = _ModalTriggerView(modal, f"⚠️ Avertir {member.display_name}", discord.ButtonStyle.primary)
    await ctx.send(f"Clique pour ouvrir le formulaire d'avertissement de **{member}** :", view=view, delete_after=30)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warns(ctx, member: discord.Member):
    """Voir les avertissements d'un membre."""
    gd = get_guild(ctx.guild.id)
    uid = str(member.id)
    warn_list = gd["warns"].get(uid, [])
    e = embed_base(f"⚠️ Avertissements de {member}", discord.Color.yellow())
    if not warn_list:
        e.description = "Aucun avertissement."
    else:
        for i, w in enumerate(warn_list, 1):
            e.add_field(
                name=f"Warn #{i} — {w['date'][:10]}",
                value=f"**Raison :** {w['reason']}\n**Par :** {w['mod']}",
                inline=False
            )
    await ctx.send(embed=e)


# ═══════════════════════════════════════════════════
#              COMMANDES — GIVEAWAY
# ═══════════════════════════════════════════════════

@bot.command(name="gs")
@commands.has_permissions(manage_guild=True)
async def giveaway_start(ctx):
    """Démarrer un giveaway via modal."""
    await ctx.message.delete()
    modal = GiveawayModal()
    view = _ModalTriggerView(modal, "🎉 Créer un Giveaway", discord.ButtonStyle.success)
    await ctx.send("Clique pour créer un giveaway :", view=view, delete_after=30)


@bot.command(name="ge")
@commands.has_permissions(manage_guild=True)
async def giveaway_end(ctx, channel: discord.TextChannel = None):
    """Terminer le giveaway actif dans un salon."""
    ch = channel or ctx.channel
    gd = get_guild(ctx.guild.id)
    # Cherche le dernier giveaway non terminé dans ce salon
    target_id = None
    for msg_id, gaw in gd["giveaways"].items():
        if gaw["channel_id"] == ch.id and not gaw["ended"]:
            target_id = int(msg_id)
    if not target_id:
        await ctx.send("❌ Aucun giveaway actif trouvé dans ce salon.", delete_after=5)
        return
    winner = await end_giveaway(ctx.guild, target_id)
    if winner:
        await ctx.send(f"✅ Giveaway terminé ! Gagnant : {winner.mention}")
    else:
        await ctx.send("✅ Giveaway terminé, aucun participant.")


@bot.command(name="gr")
@commands.has_permissions(manage_guild=True)
async def giveaway_reroll(ctx, channel: discord.TextChannel = None):
    """Reroll le dernier giveaway terminé dans un salon."""
    ch = channel or ctx.channel
    gd = get_guild(ctx.guild.id)
    target_id = None
    for msg_id, gaw in gd["giveaways"].items():
        if gaw["channel_id"] == ch.id:
            target_id = int(msg_id)
    if not target_id:
        await ctx.send("❌ Aucun giveaway trouvé dans ce salon.", delete_after=5)
        return
    winner = await end_giveaway(ctx.guild, target_id, reroll=True)
    if winner:
        await ctx.send(f"🔄 Reroll ! Nouveau gagnant : {winner.mention}")
    else:
        await ctx.send("❌ Aucun participant valide pour le reroll.")


# ═══════════════════════════════════════════════════
#              COMMANDES — TICKETS
# ═══════════════════════════════════════════════════

@bot.command()
@commands.has_permissions(manage_channels=True)
async def ticket(ctx):
    """Afficher le panneau de création de ticket."""
    await ctx.message.delete()
    e = discord.Embed(
        title="🎫 Système de Tickets",
        description=(
            "Besoin d'aide ? Ouvre un ticket en sélectionnant la catégorie appropriée ci-dessous.\n\n"
            "🛡️ **Staff** — Questions générales, demandes au staff\n"
            "🐛 **Bugs** — Signaler un bug ou problème technique\n"
            "👑 **Owner** — Contacter directement le propriétaire\n\n"
            "*Un salon privé sera créé pour ta demande.*"
        ),
        color=discord.Color.blurple(),
        timestamp=datetime.datetime.utcnow()
    )
    view = TicketPanelView()
    await ctx.send(embed=e, view=view)


# ═══════════════════════════════════════════════════
#              COMMANDES — HELP
# ═══════════════════════════════════════════════════

@bot.command()
async def help(ctx):
    """Afficher le panneau d'aide."""
    view = HelpView()
    await ctx.send(embed=view.pages[0], view=view)


# ═══════════════════════════════════════════════════
#              COMMANDES — CONFIGURATION
# ═══════════════════════════════════════════════════

@bot.command()
@is_owner_or_admin()
async def setowner(ctx, member: discord.Member):
    """Définir le propriétaire du bot."""
    data["owner_id"] = member.id
    save_data()
    await ctx.send(f"✅ **{member}** est maintenant le propriétaire du bot.", delete_after=10)


@bot.command()
@is_owner_or_admin()
async def logs(ctx, channel: discord.TextChannel):
    """Définir le salon des logs."""
    gd = get_guild(ctx.guild.id)
    gd["log_channel"] = channel.id
    save_data()
    await ctx.send(f"✅ Salon des logs défini sur {channel.mention}.", delete_after=10)


@bot.command()
@is_owner_or_admin()
async def transcripts(ctx, channel: discord.TextChannel):
    """Définir le salon des transcriptions de tickets."""
    gd = get_guild(ctx.guild.id)
    gd["transcript_channel"] = channel.id
    save_data()
    await ctx.send(f"✅ Salon des transcriptions défini sur {channel.mention}.", delete_after=10)


@bot.command()
@is_owner_or_admin()
async def welcome(ctx, channel: discord.TextChannel):
    """Définir le salon de bienvenue."""
    gd = get_guild(ctx.guild.id)
    gd["welcome_channel"] = channel.id
    save_data()
    await ctx.send(f"✅ Salon de bienvenue défini sur {channel.mention}.", delete_after=10)


@bot.command()
@is_owner_or_admin()
async def antiraid(ctx, state: str):
    """Activer ou désactiver l'anti-raid."""
    gd = get_guild(ctx.guild.id)
    if state.lower() in ("on", "true", "1", "oui"):
        gd["antiraid"]["enabled"] = True
        save_data()
        await ctx.send("✅ Anti-raid **activé**. (Seuil : 10 joins en 10s → kick automatique)", delete_after=10)
    elif state.lower() in ("off", "false", "0", "non"):
        gd["antiraid"]["enabled"] = False
        save_data()
        await ctx.send("✅ Anti-raid **désactivé**.", delete_after=10)
    else:
        await ctx.send("❌ Usage : `!antiraid on` ou `!antiraid off`", delete_after=5)


# ═══════════════════════════════════════════════════
#              HELPER : BOUTON POUR OUVRIR UN MODAL
# ═══════════════════════════════════════════════════

class _ModalTriggerView(discord.ui.View):
    """Vue temporaire avec un bouton qui ouvre un modal."""
    def __init__(self, modal: discord.ui.Modal, label: str, style: discord.ButtonStyle):
        super().__init__(timeout=30)
        self._modal = modal
        self._label = label
        self._style = style
        btn = discord.ui.Button(label=label, style=style)
        btn.callback = self._callback
        self.add_item(btn)

    async def _callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self._modal)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ═══════════════════════════════════════════════════
#              LANCEMENT
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("⚠️  ATTENTION : Tu n'as pas renseigné ton token !")
        print("   Ouvre bot.py et remplace TON_TOKEN_ICI par ton vrai token Discord.")
    else:
        bot.run(BOT_TOKEN)
