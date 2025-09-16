"""
Exonian Article Workflow Bot (safe version)
- /setup               : create categories + Editors role
- /sync_here           : force-publish commands to this server
- /ping                : quick test
- /new_article         : create private channel for an article
- /archive             : archive a channel (read-only for all but Editors)
- /list_articles       : list active articles + deadlines
- Auto-sweeper (5 min) : auto-archive past deadline (safety net)

Requires:
  pip3 install -U discord.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import tasks

# -------------------- CONFIG --------------------

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

CONFIG_PATH = Path("exonian_config.json")

@dataclass
class BotConfig:
    guild_id: Optional[int] = None
    active_category_name: str = "Active Articles"
    archived_category_name: str = "Archived Articles"
    editors_role_name: str = "Editors"

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))

    @staticmethod
    def load() -> "BotConfig":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return BotConfig(**data)
            except Exception:
                pass
        return BotConfig()

config = BotConfig.load()

# -------------------- UTILITIES --------------------

def slugify(title: str) -> str:
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in title).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:90] if s else "article"

_DATE_FORMATS = [
    "%Y-%m-%d %H:%M",      # 2025-09-07 23:00
    "%Y-%m-%d",            # 2025-09-07
    "%b %d %Y %H:%M",      # Sep 7 2025 23:00
    "%b %d %H:%M",         # Sep 7 23:00  (assumes current year)
]

def parse_when(s: str) -> Optional[datetime]:
    s = s.strip()
    now = datetime.now()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=now.year)
            return dt
        except ValueError:
            continue
    return None

DEADLINE_TAG = "[deadline: "

def extract_deadline_from_topic(topic: Optional[str]) -> Optional[datetime]:
    if not topic or DEADLINE_TAG not in topic:
        return None
    try:
        start = topic.index(DEADLINE_TAG) + len(DEADLINE_TAG)
        end = topic.index("]", start)
        return datetime.fromisoformat(topic[start:end])
    except Exception:
        return None

async def ensure_categories(guild: discord.Guild) -> tuple[discord.CategoryChannel, discord.CategoryChannel]:
    active = discord.utils.get(guild.categories, name=config.active_category_name)
    archived = discord.utils.get(guild.categories, name=config.archived_category_name)
    if active is None:
        active = await guild.create_category(config.active_category_name, reason="Setup Active Articles")
    if archived is None:
        archived = await guild.create_category(config.archived_category_name, reason="Setup Archived Articles")
    return active, archived

async def get_or_create_role(guild: discord.Guild, name: str) -> discord.Role:
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, reason="Exonian workflow bot setup")
    return role

# -------------------- BOT --------------------

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

class ExonianBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # If we know the guild, sync faster there; otherwise global sync will settle in ~1 min
        if config.guild_id:
            guild = discord.Object(id=config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        sweeper.start()

bot = ExonianBot()

# -------------------- COMMANDS --------------------

@bot.tree.command(name="ping", description="Test if bot is alive")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!", ephemeral=True)

@bot.tree.command(name="sync_here", description="Force-sync commands to this server (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def sync_here(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await bot.tree.sync(guild=interaction.guild)
    await interaction.followup.send("Commands synced to this server.", ephemeral=True)

@bot.tree.command(description="Initialize categories and set this guild as default.")
async def setup(interaction: discord.Interaction):
    # Acknowledge fast so Discord doesn't time out
    await interaction.response.defer(ephemeral=True, thinking=True)

    config.guild_id = interaction.guild_id
    active, archived = await ensure_categories(interaction.guild)
    editors = await get_or_create_role(interaction.guild, config.editors_role_name)
    config.save()

    msg = (
        f"Setup complete.\n"
        f"Active: {active.name}\n"
        f"Archived: {archived.name}\n"
        f"Editors role: {editors.mention}"
    )
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="list_articles", description="List active article channels and deadlines")
async def list_articles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return

    active_cat, _ = await ensure_categories(guild)
    lines: List[str] = []
    for ch in active_cat.text_channels:
        dl = extract_deadline_from_topic(ch.topic)
        if dl:
            lines.append(f"• {ch.mention} — deadline <t:{int(dl.timestamp())}:R>")
        else:
            lines.append(f"• {ch.mention} — no deadline")
    if not lines:
        await interaction.followup.send("No active article channels.", ephemeral=True)
    else:
        await interaction.followup.send("\n".join(lines), ephemeral=True)

@bot.tree.command(name="new_article", description="Create a private channel for an article")
@app_commands.describe(
    title="Article title",
    deadline="Deadline (e.g., '2025-09-07 23:00' or 'Sep 7 23:00')",
    writers="Mention users separated by spaces",
)
async def new_article(
    interaction: discord.Interaction,
    title: str,
    deadline: str,
    writers: Optional[str] = None,
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("This command must be used in a server.", ephemeral=True)
            return

        dt = parse_when(deadline)
        if not dt:
            await interaction.followup.send("Couldn't parse the deadline. Use `YYYY-MM-DD HH:MM` (24-hour).", ephemeral=True)
            return

        active_cat, _ = await ensure_categories(guild)
        editors_role = discord.utils.get(guild.roles, name=config.editors_role_name)

        channel_name = slugify(title)
        overwrites: dict = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        if editors_role:
            overwrites[editors_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
            )

        user_ids: List[int] = []
        if writers:
            for mention in writers.split():
                if mention.startswith("<@") and mention.endswith(">"):
                    stripped = mention.strip("<@!>")
                    if stripped.isdigit():
                        user_ids.append(int(stripped))

        allowed_users: List[discord.Member] = []
        for uid in set(user_ids):
            member = guild.get_member(uid) or await guild.fetch_member(uid)
            if member:
                allowed_users.append(member)
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        topic = f"Article: {title} | {DEADLINE_TAG}{dt.isoformat()}]"
        channel = await guild.create_text_channel(
            name=channel_name,
            category=active_cat,
            overwrites=overwrites,
            topic=topic,
            reason=f"Article channel for '{title}'",
        )

        checklist = (
            f"**Article:** {title}\n"
            f"**Writers:** {' '.join(writers.split()) if writers else '—'}\n"
            f"**Deadline:** <t:{int(dt.timestamp())}:F> (<t:{int(dt.timestamp())}:R>)\n\n"
            f"**Checklist**\n- [ ] Angle approved\n- [ ] Sources identified\n- [ ] Draft complete\n- [ ] Edited by section\n- [ ] Copy edit\n- [ ] Final publish\n"
        )
        msg = await channel.send(checklist)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass

        await interaction.followup.send(
            f"Created {channel.mention} for **{title}**. Writers added: {', '.join(m.mention for m in allowed_users) if allowed_users else 'None'}",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "Missing permissions: the bot needs Manage Channels & Manage Roles, and its role must be above section roles.",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Error while creating channel: {e.__class__.__name__}", ephemeral=True)

@bot.tree.command(name="archive", description="Archive an article channel (defaults to current channel)")
@app_commands.describe(channel="Channel to archive (optional)")
async def archive_channel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("This command must be used in a server.", ephemeral=True)
            return

        _, archived_cat = await ensure_categories(guild)
        ch = channel or interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await interaction.followup.send("Choose a text channel to archive.", ephemeral=True)
            return

        # Move channel
        await ch.edit(category=archived_cat, reason="Article archived")

        # Lock posting: default role can view but not send; only Editors can post
        editors_role = discord.utils.get(guild.roles, name=config.editors_role_name)
        overwrites = ch.overwrites

        # Ensure @everyone cannot send
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=False, read_message_history=True
        )

        # Remove per-member send permissions and non-editor role sends
        cleaned = {}
        for target, _perms in overwrites.items():
            if isinstance(target, discord.Member):
                cleaned[target] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=False, read_message_history=True
                )
            elif isinstance(target, discord.Role):
                if editors_role and target.id == editors_role.id:
                    cleaned[target] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
                else:
                    cleaned[target] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, read_message_history=True
                    )
            else:
                cleaned[target] = discord.PermissionOverwrite(view_channel=True, send_messages=False)

        await ch.edit(overwrites=cleaned)
        await interaction.followup.send(f"Archived {ch.mention} (posting locked; Editors can still post).", ephemeral=True)

    except discord.Forbidden:
        await interaction.followup.send(
            "Missing permissions: need Manage Channels, and bot role must be above section roles.",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Error while archiving: {e.__class__.__name__}", ephemeral=True)

# -------------------- BACKGROUND TASKS --------------------

@tasks.loop(minutes=5)
async def sweeper():
    await bot.wait_until_ready()
    if config.guild_id is None:
        return
    guild = bot.get_guild(config.guild_id)
    if not guild:
        return
    active_cat, archived_cat = await ensure_categories(guild)
    editors_role = discord.utils.get(guild.roles, name=config.editors_role_name)
    now = datetime.now()
    for ch in list(active_cat.text_channels):
        dl = extract_deadline_from_topic(ch.topic)
        if dl and dl < now:
            try:
                await ch.send("⏰ Deadline passed — archiving channel.")
                await ch.edit(category=archived_cat, reason="Auto-archive past deadline")
                # Lock posting similar to manual archive
                overwrites = ch.overwrites
                overwrites[guild.default_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=False, read_message_history=True
                )
                cleaned = {}
                for target, _perms in overwrites.items():
                    if isinstance(target, discord.Member):
                        cleaned[target] = discord.PermissionOverwrite(
                            view_channel=True, send_messages=False, read_message_history=True
                        )
                    elif isinstance(target, discord.Role):
                        if editors_role and target.id == editors_role.id:
                            cleaned[target] = discord.PermissionOverwrite(
                                view_channel=True, send_messages=True, read_message_history=True
                            )
                        else:
                            cleaned[target] = discord.PermissionOverwrite(
                                view_channel=True, send_messages=False, read_message_history=True
                            )
                    else:
                        cleaned[target] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
                await ch.edit(overwrites=cleaned)
            except Exception:
                continue

# -------------------- RUN --------------------

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Please set the DISCORD_BOT_TOKEN environment variable.")
    bot.run(TOKEN)
