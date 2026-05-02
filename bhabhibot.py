import discord
from discord.ext import commands
import json
import os
from datetime import timedelta

TOKEN = os.getenv("TOKEN")
PREFIX = "."
DATA_FILE = "triggers.json"

DEFAULT_COLOR = 0x2B2D42
ERROR_COLOR = 0xFEE75C

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

DEFAULT_TRIGGERS = {
    "ban": [],
    "kick": [],
    "mute": []
}


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    for gid in data:
        data[gid].pop("timeout", None)
        for key in DEFAULT_TRIGGERS:
            data[gid].setdefault(key, [])

    return data


TRIGGERS = load_data()


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(TRIGGERS, f, indent=4)


def setup_guild(guild_id):
    gid = str(guild_id)

    if gid not in TRIGGERS:
        TRIGGERS[gid] = {"ban": [], "kick": [], "mute": []}
        save_data()

    TRIGGERS[gid].pop("timeout", None)

    for key in DEFAULT_TRIGGERS:
        TRIGGERS[gid].setdefault(key, [])

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
    member = message.mentions[0] if message.mentions else None

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
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)