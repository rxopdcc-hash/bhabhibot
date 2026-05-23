import discord
from discord.ext import commands, tasks
import json
import os
import re
from datetime import timedelta

TOKEN = os.getenv("TOKEN")
PREFIX = "."
DATA_FILE = "/app/data/triggers.json"

DEFAULT_COLOR = 0x2B2D42
ERROR_COLOR = 0xFEE75C

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

MENTION_RE = re.compile(r"<@!?(\d+)>")

DEFAULT_VANITY = {
    "enabled": False,
    "role_id": None,
    "channel_id": None,
    "triggers": [],
    "message": "{user} is repping the server now.",
    "color": "57F287",
    "remove_color": "ED4245",
    "remove_message": "{user} is no longer repping the server."
}

DEFAULT_TAG = {
    "enabled": False,
    "role_id": None,
    "channel_id": None,
    "triggers": [],
    "message": "{user} is repping the server tag now.",
    "color": "57F287",
    "remove_color": "ED4245",
    "remove_message": "{user} is no longer repping the server tag."
}

DEFAULT_TRIGGERS = {
    "ban": [],
    "kick": [],
    "mute": []
}


def fresh_config(default):
    data = default.copy()
    data["triggers"] = default["triggers"].copy()
    return data


def copy_default_value(value):
    return value.copy() if type(value) is list else value

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    for gid in data:
        data[gid].pop("timeout", None)
        for key in DEFAULT_TRIGGERS:
            data[gid].setdefault(key, [])
        data[gid].setdefault("vanity", fresh_config(DEFAULT_VANITY))
        data[gid].setdefault("tag", fresh_config(DEFAULT_TAG))
        for key, value in DEFAULT_VANITY.items():
            data[gid]["vanity"].setdefault(key, copy_default_value(value))
        for key, value in DEFAULT_TAG.items():
            data[gid]["tag"].setdefault(key, copy_default_value(value))

    return data


TRIGGERS = load_data()


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(TRIGGERS, f, indent=4)


def setup_guild(guild_id):
    gid = str(guild_id)

    if gid not in TRIGGERS:
        TRIGGERS[gid] = {
            "ban": [],
            "kick": [],
            "mute": [],
            "vanity": fresh_config(DEFAULT_VANITY),
            "tag": fresh_config(DEFAULT_TAG)
        }

        save_data()

    TRIGGERS[gid].pop("timeout", None)

    for key in DEFAULT_TRIGGERS:
        TRIGGERS[gid].setdefault(key, [])

    TRIGGERS[gid].setdefault("vanity", fresh_config(DEFAULT_VANITY))
    TRIGGERS[gid].setdefault("tag", fresh_config(DEFAULT_TAG))

    for key, value in DEFAULT_VANITY.items():
        TRIGGERS[gid]["vanity"].setdefault(key, copy_default_value(value))

    for key, value in DEFAULT_TAG.items():
        TRIGGERS[gid]["tag"].setdefault(key, copy_default_value(value))

    return gid

def premium_embed(ctx, title=None, desc=None, syntax=None, example=None):
    e = discord.Embed(color=DEFAULT_COLOR)

    if ctx.guild:
        e.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon.url if ctx.guild.icon else discord.Embed.Empty
        )

    text = ""

    if title:
        text += f"**{title}**"

    if desc:
        text += f"\n\n{desc}"

    if syntax:
        text += f"\n\n```Syntax: {syntax}"
        if example:
            text += f"\nExample: {example}"
        text += "```"

    e.description = text
    e.set_footer(text=str(ctx.author), icon_url=ctx.author.display_avatar.url)
    e.timestamp = discord.utils.utcnow()
    return e


def missing_perm_embed(ctx, perm):
    return discord.Embed(
        color=ERROR_COLOR,
        description=f"⚠ {ctx.author.mention}: You're **missing permission**: `{perm}`"
    )


def bot_missing_perm_embed(ctx, perm):
    return discord.Embed(
        color=ERROR_COLOR,
        description=f"⚠ I am **missing permission**: `{perm}`"
    )


def warning_embed(ctx, msg):
    return discord.Embed(
        color=ERROR_COLOR,
        description=f"⚠ {ctx.author.mention}: {msg}"
    )


def parse_duration(raw):
    if not raw:
        return timedelta(minutes=10)

    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}

    try:
        num = int(raw[:-1])
        unit = raw[-1].lower()

        if unit not in units:
            return None

        return timedelta(seconds=num * units[unit])
    except Exception:
        return None


def hierarchy_ok(ctx, member):
    if member == ctx.guild.owner:
        return False, "You cannot moderate the server owner."

    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        return False, "You cannot moderate someone with an equal/higher role."

    if member.top_role >= ctx.guild.me.top_role:
        return False, "My role is too low to moderate this user."

    return True, None


async def run_ban(ctx, member=None, *, reason="No reason provided"):
    if not ctx.author.guild_permissions.ban_members:
        return await ctx.reply(embed=missing_perm_embed(ctx, "ban_members"), mention_author=False)

    if not ctx.guild.me.guild_permissions.ban_members:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "ban_members"), mention_author=False)

    if member is None:
        return await ctx.reply(
            embed=premium_embed(ctx, "ban", "Ban a member from the server", ".ban (member) [reason]", ".ban @user spam"),
            mention_author=False
        )

    ok, msg = hierarchy_ok(ctx, member)
    if not ok:
        return await ctx.reply(embed=warning_embed(ctx, msg), mention_author=False)

    await member.ban(reason=f"{ctx.author} | {reason}")
    await ctx.reply(
        embed=premium_embed(ctx, "banned", f"**{member}** has been banned.\nReason: `{reason}`"),
        mention_author=False
    )


async def run_kick(ctx, member=None, *, reason="No reason provided"):
    if not ctx.author.guild_permissions.kick_members:
        return await ctx.reply(embed=missing_perm_embed(ctx, "kick_members"), mention_author=False)

    if not ctx.guild.me.guild_permissions.kick_members:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "kick_members"), mention_author=False)

    if member is None:
        return await ctx.reply(
            embed=premium_embed(ctx, "kick", "Kick a member from the server", ".kick (member) [reason]", ".kick @user spam"),
            mention_author=False
        )

    ok, msg = hierarchy_ok(ctx, member)
    if not ok:
        return await ctx.reply(embed=warning_embed(ctx, msg), mention_author=False)

    await member.kick(reason=f"{ctx.author} | {reason}")
    await ctx.reply(
        embed=premium_embed(ctx, "kicked", f"**{member}** has been kicked.\nReason: `{reason}`"),
        mention_author=False
    )


async def run_mute(ctx, member=None, duration="10m", *, reason="No reason provided"):
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.reply(embed=missing_perm_embed(ctx, "timeout_members"), mention_author=False)

    if not ctx.guild.me.guild_permissions.moderate_members:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "timeout_members"), mention_author=False)

    if member is None:
        return await ctx.reply(
            embed=premium_embed(ctx, "mute", "Timeout a member from the server", ".mute (member) [time] [reason]", ".mute @user 10m spam"),
            mention_author=False
        )

    ok, msg = hierarchy_ok(ctx, member)
    if not ok:
        return await ctx.reply(embed=warning_embed(ctx, msg), mention_author=False)

    time = parse_duration(duration)

    if time is None:
        reason = f"{duration} {reason}"
        duration = "10m"
        time = timedelta(minutes=10)

    await member.timeout(time, reason=f"{ctx.author} | {reason}")
    await ctx.reply(
        embed=premium_embed(ctx, "muted", f"**{member}** has been muted.\nDuration: `{duration}`\nReason: `{reason}`"),
        mention_author=False
    )


@bot.command()
async def ban(ctx, member: discord.Member = None, *, reason="No reason provided"):
    await run_ban(ctx, member, reason=reason)


@bot.command()
async def kick(ctx, member: discord.Member = None, *, reason="No reason provided"):
    await run_kick(ctx, member, reason=reason)


@bot.command(aliases=["timeout"])
async def mute(ctx, member: discord.Member = None, duration="10m", *, reason="No reason provided"):
    await run_mute(ctx, member, duration, reason=reason)


@bot.command()
async def unmute(ctx, member: discord.Member = None):
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.reply(embed=missing_perm_embed(ctx, "timeout_members"), mention_author=False)

    if not ctx.guild.me.guild_permissions.moderate_members:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "timeout_members"), mention_author=False)

    if member is None:
        return await ctx.reply(
            embed=premium_embed(ctx, "unmute", "Remove timeout from a member", ".unmute (member)", ".unmute @user"),
            mention_author=False
        )

    await member.timeout(None, reason=f"{ctx.author} removed timeout")
    await ctx.reply(embed=premium_embed(ctx, "unmuted", f"**{member}** has been unmuted."), mention_author=False)


@bot.command()
async def unban(ctx, user_id: int = None):
    if not ctx.author.guild_permissions.ban_members:
        return await ctx.reply(embed=missing_perm_embed(ctx, "ban_members"), mention_author=False)

    if not ctx.guild.me.guild_permissions.ban_members:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "ban_members"), mention_author=False)

    if user_id is None:
        return await ctx.reply(
            embed=premium_embed(ctx, "unban", "Unban a user by ID", ".unban (user_id)", ".unban 123456789"),
            mention_author=False
        )

    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user, reason=f"{ctx.author} unbanned user")
    await ctx.reply(embed=premium_embed(ctx, "unbanned", f"**{user}** has been unbanned."), mention_author=False)


@bot.command()
async def trigger(ctx, action=None, command=None, name=None):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.reply(embed=missing_perm_embed(ctx, "manage_server"), mention_author=False)

    gid = setup_guild(ctx.guild.id)

    if action is None:
        return await ctx.reply(
            embed=premium_embed(
                ctx,
                "trigger",
                "Manage custom moderation triggers",
                ".trigger add/clean/list (command) (trigger)",
                ".trigger add mute m"
            ),
            mention_author=False
        )

    action = action.lower()

    if action == "list":
        text = ""

        for cmd in ["ban", "kick", "mute"]:
            aliases = TRIGGERS[gid][cmd]
            formatted = " ".join(f"`{a}`" for a in aliases) if aliases else "`none`"
            text += f"**{cmd}**: {formatted}\n"

        return await ctx.reply(
            embed=premium_embed(ctx, "triggers", text.strip()),
            mention_author=False
        )

    if command not in ["ban", "kick", "mute"]:
        return await ctx.reply(
            embed=warning_embed(ctx, "Command must be `ban`, `kick`, or `mute`."),
            mention_author=False
        )

    if not name:
        return await ctx.reply(embed=warning_embed(ctx, "Give a trigger name."), mention_author=False)

    command = command.lower()
    name = name.lower().replace(PREFIX, "")

    blocked = [
        "help", "trigger", "unban", "unmute", "ban", "kick", "mute",
        "timeout", "settings", "role", "server", "purge", "clear", "clean"
    ]

    if name in blocked:
        return await ctx.reply(embed=warning_embed(ctx, "That trigger is blocked."), mention_author=False)

    exists_anywhere = any(name in aliases for aliases in TRIGGERS[gid].values())

    if action == "add":
        if exists_anywhere:
            return await ctx.reply(embed=warning_embed(ctx, "This trigger already exists."), mention_author=False)

        TRIGGERS[gid][command].append(name)
        save_data()

        return await ctx.reply(
            embed=premium_embed(ctx, "trigger added", f"`.{name}` now works as **{command}**."),
            mention_author=False
        )

    if action == "clean":
        if name not in TRIGGERS[gid][command]:
            return await ctx.reply(
                embed=warning_embed(ctx, "That trigger does not exist for this command."),
                mention_author=False
            )

        TRIGGERS[gid][command].remove(name)
        save_data()

        return await ctx.reply(
            embed=premium_embed(ctx, "trigger cleaned", f"`.{name}` removed from **{command}**."),
            mention_author=False
        )

    return await ctx.reply(embed=warning_embed(ctx, "Use `add`, `clean`, or `list`."), mention_author=False)

@bot.group(invoke_without_command=True)
async def vanity(ctx):
    await ctx.reply(
        embed=premium_embed(
            ctx,
            "vanity",
            ".vanity setup system",
            ".vanity <subcommand>",
            ".vanity add bhabhi"
        ),
        mention_author=False
    )


@vanity.command()
async def enable(ctx):
    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["vanity"]["enabled"] = True
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "vanity enabled", "Vanity system is now enabled."),
        mention_author=False
    )


@vanity.command()
async def disable(ctx):
    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["vanity"]["enabled"] = False
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "vanity disabled", "Vanity system is now disabled."),
        mention_author=False
    )


@vanity.command()
async def role(ctx, role: discord.Role = None):
    if role is None:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a role."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["vanity"]["role_id"] = role.id
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "role updated", f"Vanity role set to {role.mention}."),
        mention_author=False
    )


@vanity.command()
async def channel(ctx, channel: discord.TextChannel = None):
    if channel is None:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a channel."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["vanity"]["channel_id"] = channel.id
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "channel updated", f"Vanity channel set to {channel.mention}."),
        mention_author=False
    )


@vanity.command()
async def add(ctx, *, trigger=None):
    if not trigger:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a trigger."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    trigger = trigger.lower()

    if trigger in TRIGGERS[gid]["vanity"]["triggers"]:
        return await ctx.reply(
            embed=warning_embed(ctx, "That trigger already exists."),
            mention_author=False
        )

    TRIGGERS[gid]["vanity"]["triggers"].append(trigger)
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "trigger added", f"`{trigger}` added."),
        mention_author=False
    )


@vanity.command()
async def remove(ctx, *, trigger=None):
    if not trigger:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a trigger."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    trigger = trigger.lower()

    if trigger not in TRIGGERS[gid]["vanity"]["triggers"]:
        return await ctx.reply(
            embed=warning_embed(ctx, "Trigger not found."),
            mention_author=False
        )

    TRIGGERS[gid]["vanity"]["triggers"].remove(trigger)
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "trigger removed", f"`{trigger}` removed."),
        mention_author=False
    )


@vanity.command()
async def message(ctx, *, message=None):
    if not message:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a message."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["vanity"]["message"] = message
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "message updated", "Vanity message updated."),
        mention_author=False
    )


@vanity.command()
async def color(ctx, color=None):
    if not color:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a hex color."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    color = color.replace("#", "")

    TRIGGERS[gid]["vanity"]["color"] = color
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "color updated", f"Color set to `{color}`."),
        mention_author=False
    )


@vanity.command()
async def removecolor(ctx, color=None):
    if not color:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a hex color."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    color = color.replace("#", "")

    TRIGGERS[gid]["vanity"]["remove_color"] = color
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "remove color updated", f"Remove color set to `{color}`."),
        mention_author=False
    )


@vanity.command()
async def removemessage(ctx, *, message=None):
    if not message:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a message."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["vanity"]["remove_message"] = message
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "remove message updated", "Vanity remove message updated."),
        mention_author=False
    )


@vanity.command()
async def list(ctx):
    gid = setup_guild(ctx.guild.id)

    vanity = TRIGGERS[gid]["vanity"]

    triggers = vanity["triggers"]

    formatted = " ".join(f"`{t}`" for t in triggers) if triggers else "`none`"

    text = (
        f"**enabled**: `{vanity['enabled']}`\n"
        f"**triggers**: {formatted}"
    )

    await ctx.reply(
        embed=premium_embed(ctx, "vanity config", text),
        mention_author=False
    )


@bot.group(invoke_without_command=True)
async def tag(ctx):
    await ctx.reply(
        embed=premium_embed(
            ctx,
            "tag",
            ".tag setup system",
            ".tag <subcommand>",
            ".tag enable"
        ),
        mention_author=False
    )


@tag.command(name="enable")
async def tag_enable(ctx):
    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["tag"]["enabled"] = True
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "tag enabled", "Server tag system is now enabled."),
        mention_author=False
    )


@tag.command(name="disable")
async def tag_disable(ctx):
    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["tag"]["enabled"] = False
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "tag disabled", "Server tag system is now disabled."),
        mention_author=False
    )


@tag.command(name="role")
async def tag_role(ctx, role: discord.Role = None):
    if role is None:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a role."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["tag"]["role_id"] = role.id
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "role updated", f"Tag role set to {role.mention}."),
        mention_author=False
    )


@tag.command(name="channel")
async def tag_channel(ctx, channel: discord.TextChannel = None):
    if channel is None:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a channel."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["tag"]["channel_id"] = channel.id
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "channel updated", f"Tag channel set to {channel.mention}."),
        mention_author=False
    )


@tag.command(name="add")
async def tag_add(ctx, *, trigger=None):
    if not trigger:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a server tag."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)
    trigger = trigger.lower().replace("#", "").strip()

    if trigger in TRIGGERS[gid]["tag"]["triggers"]:
        return await ctx.reply(
            embed=warning_embed(ctx, "That tag already exists."),
            mention_author=False
        )

    TRIGGERS[gid]["tag"]["triggers"].append(trigger)
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "tag added", f"`{trigger}` added."),
        mention_author=False
    )


@tag.command(name="remove")
async def tag_remove(ctx, *, trigger=None):
    if not trigger:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a server tag."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)
    trigger = trigger.lower().replace("#", "").strip()

    if trigger not in TRIGGERS[gid]["tag"]["triggers"]:
        return await ctx.reply(
            embed=warning_embed(ctx, "Tag not found."),
            mention_author=False
        )

    TRIGGERS[gid]["tag"]["triggers"].remove(trigger)
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "tag removed", f"`{trigger}` removed."),
        mention_author=False
    )


@tag.command(name="message")
async def tag_message(ctx, *, message=None):
    if not message:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a message."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["tag"]["message"] = message
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "message updated", "Tag message updated."),
        mention_author=False
    )


@tag.command(name="color")
async def tag_color(ctx, color=None):
    if not color:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a hex color."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)
    color = color.replace("#", "")

    TRIGGERS[gid]["tag"]["color"] = color
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "color updated", f"Color set to `{color}`."),
        mention_author=False
    )


@tag.command(name="removecolor")
async def tag_removecolor(ctx, color=None):
    if not color:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a hex color."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)
    color = color.replace("#", "")

    TRIGGERS[gid]["tag"]["remove_color"] = color
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "remove color updated", f"Remove color set to `{color}`."),
        mention_author=False
    )


@tag.command(name="removemessage")
async def tag_removemessage(ctx, *, message=None):
    if not message:
        return await ctx.reply(
            embed=warning_embed(ctx, "Provide a message."),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)

    TRIGGERS[gid]["tag"]["remove_message"] = message
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "remove message updated", "Tag remove message updated."),
        mention_author=False
    )


@tag.command(name="list")
async def tag_list(ctx):
    gid = setup_guild(ctx.guild.id)
    tag_config = TRIGGERS[gid]["tag"]

    triggers = tag_config["triggers"]
    formatted = " ".join(f"`{t}`" for t in triggers) if triggers else "`current server tag`"

    text = (
        f"**enabled**: `{tag_config['enabled']}`\n"
        f"**tags**: {formatted}"
    )

    await ctx.reply(
        embed=premium_embed(ctx, "tag config", text),
        mention_author=False
    )


def status_text_for(member):
    status_text = ""

    for activity in member.activities:
        if isinstance(activity, discord.CustomActivity):
            if activity.name:
                status_text += f" {activity.name.lower()}"

            if activity.state:
                status_text += f" {activity.state.lower()}"

    return status_text


def format_rep_message(message, member, role):
    msg = message.replace("{user}", member.mention)
    msg = msg.replace("{server}", member.guild.name)
    msg = msg.replace("{role}", role.mention)
    return msg


def explicit_mentioned_member(message):
    match = MENTION_RE.search(message.content)

    if not match:
        return None

    return message.guild.get_member(int(match.group(1)))


async def update_rep_role(member, config, matched, add_reason, remove_reason):
    role_id = config["role_id"]
    channel_id = config["channel_id"]

    if not role_id:
        return

    role = member.guild.get_role(role_id)

    if not role:
        return

    has_role = role in member.roles
    channel = member.guild.get_channel(channel_id) if channel_id else None

    if matched and not has_role:
        try:
            await member.add_roles(role, reason=add_reason)

            if channel:
                embed = discord.Embed(
                    description=format_rep_message(config["message"], member, role),
                    color=int(config["color"], 16)
                )
                await channel.send(embed=embed)

        except:
            pass

    elif not matched and has_role:
        try:
            await member.remove_roles(role, reason=remove_reason)

            if channel:
                embed = discord.Embed(
                    description=format_rep_message(config["remove_message"], member, role),
                    color=int(config["remove_color"], 16)
                )
                await channel.send(embed=embed)

        except:
            pass


def primary_value(primary_guild, key):
    if isinstance(primary_guild, dict):
        return primary_guild.get(key)

    return getattr(primary_guild, key, None)


def member_has_server_tag(member, tag_config, user=None, primary_guild=None):
    source = user or member
    primary_guild = primary_guild or getattr(source, "primary_guild", None)

    if not primary_guild:
        return False

    if primary_value(primary_guild, "identity_enabled") is not True:
        return False

    identity_guild_id = primary_value(primary_guild, "identity_guild_id")
    tag_text = primary_value(primary_guild, "tag")

    if identity_guild_id and int(identity_guild_id) == member.guild.id:
        return True

    configured_tags = tag_config["triggers"]

    if tag_text and configured_tags:
        return tag_text.lower() in configured_tags

    return False


async def process_tag_member(member, user=None, primary_guild=None):
    if member.bot or not member.guild:
        return

    gid = setup_guild(member.guild.id)
    tag_config = TRIGGERS[gid]["tag"]

    if not tag_config["enabled"]:
        return

    await update_rep_role(
        member,
        tag_config,
        member_has_server_tag(member, tag_config, user, primary_guild),
        "Server tag detected",
        "Server tag removed"
    )


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    if not message.content.startswith(PREFIX):
        return

    ctx = await bot.get_context(message)

    if ctx.command:
        await bot.process_commands(message)
        return

    gid = setup_guild(message.guild.id)
    raw = message.content[len(PREFIX):].strip()
    parts = raw.split()

    if not parts:
        return

    trigger_name = parts[0].lower()
    member = explicit_mentioned_member(message)

    args = parts[1:]
    args = [a for a in args if not a.startswith("<@") and not a.startswith("<@!")]

    if trigger_name in TRIGGERS[gid]["ban"]:
        reason = " ".join(args) if args else "No reason provided"
        return await run_ban(ctx, member, reason=reason)

    if trigger_name in TRIGGERS[gid]["kick"]:
        reason = " ".join(args) if args else "No reason provided"
        return await run_kick(ctx, member, reason=reason)

    if trigger_name in TRIGGERS[gid]["mute"]:
        duration = args[0] if args else "10m"
        reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided"
        return await run_mute(ctx, member, duration, reason=reason)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.reply(embed=warning_embed(ctx, "Missing required argument."), mention_author=False)

    if isinstance(error, commands.MemberNotFound):
        return await ctx.reply(embed=warning_embed(ctx, "Member not found."), mention_author=False)

    if isinstance(error, commands.BadArgument):
        return await ctx.reply(embed=warning_embed(ctx, "Invalid argument."), mention_author=False)

    raise error

@bot.event
async def on_presence_update(before, after):
    if after.bot or not after.guild:
        return

    gid = setup_guild(after.guild.id)
    vanity = TRIGGERS[gid]["vanity"]

    if not vanity["enabled"]:
        return

    triggers = vanity["triggers"]

    if not triggers:
        return

    before_status_text = status_text_for(before)
    after_status_text = status_text_for(after)

    before_matched = any(trigger in before_status_text for trigger in triggers)
    after_matched = any(trigger in after_status_text for trigger in triggers)
    went_offline = after.status == discord.Status.offline

    if after_matched:
        return await update_rep_role(after, vanity, True, "Vanity detected", "Vanity removed")

    if before_matched and not went_offline:
        return await update_rep_role(after, vanity, False, "Vanity detected", "Vanity removed")


@bot.event
async def on_member_update(before, after):
    await process_tag_member(after)


@bot.event
async def on_user_update(before, after):
    for guild in bot.guilds:
        member = guild.get_member(after.id)

        if member:
            await process_tag_member(member, after)


@bot.event
async def on_member_join(member):
    await process_tag_member(member)


@bot.listen("on_socket_response")
async def on_socket_response(payload):
    if payload.get("t") != "GUILD_MEMBER_UPDATE":
        return

    data = payload.get("d", {})
    user_data = data.get("user", {})
    primary_guild = user_data.get("primary_guild")

    if not primary_guild:
        return

    guild_id = data.get("guild_id")
    user_id = user_data.get("id")

    if not guild_id or not user_id:
        return

    guild = bot.get_guild(int(guild_id))

    if not guild:
        return

    member = guild.get_member(int(user_id))

    if member:
        await process_tag_member(member, primary_guild=primary_guild)


@tasks.loop(minutes=5)
async def tag_scan():
    for guild in bot.guilds:
        gid = setup_guild(guild.id)

        if not TRIGGERS[gid]["tag"]["enabled"]:
            continue

        for member in guild.members:
            await process_tag_member(member)

@bot.event
async def on_ready():
    if not tag_scan.is_running():
        tag_scan.start()

    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
