import discord
from discord.ext import commands
import asyncio
import ctypes.util
import glob
import json
import logging
import os
import subprocess
import shutil
import traceback
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

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

DEFAULT_TRIGGERS = {
    "ban": [],
    "kick": [],
    "mute": []
}

DEFAULT_RECORDING = {
    "channel_id": None
}

ACTIVE_RECORDINGS = {}


def ensure_opus_loaded():
    if discord.opus.is_loaded():
        return True

    library_paths = []

    for env_name in ["LD_LIBRARY_PATH", "LIBRARY_PATH"]:
        for folder in os.getenv(env_name, "").split(os.pathsep):
            if folder:
                library_paths.extend(glob.glob(os.path.join(folder, "libopus.so*")))

    library_paths.extend(glob.glob("/usr/lib/**/libopus.so*", recursive=True))
    library_paths.extend(glob.glob("/lib/**/libopus.so*", recursive=True))
    library_paths.extend(glob.glob("/nix/store/**/lib/libopus.so*", recursive=True))

    names = [
        ctypes.util.find_library("opus"),
        *library_paths,
        "libopus.so.0",
        "libopus.so",
        "opus",
    ]

    for name in names:
        if not name:
            continue

        try:
            discord.opus.load_opus(name)
            return discord.opus.is_loaded()
        except Exception:
            pass

    return False


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    for gid in data:
        data[gid].pop("timeout", None)
        for key in DEFAULT_TRIGGERS:
            data[gid].setdefault(key, [])
        data[gid].setdefault("recording", DEFAULT_RECORDING.copy())

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
            "vanity": DEFAULT_VANITY.copy(),
            "recording": DEFAULT_RECORDING.copy()
        }

        save_data()

    TRIGGERS[gid].pop("timeout", None)

    for key in DEFAULT_TRIGGERS:
        TRIGGERS[gid].setdefault(key, [])

    TRIGGERS[gid].setdefault("vanity", DEFAULT_VANITY.copy())
    TRIGGERS[gid].setdefault("recording", DEFAULT_RECORDING.copy())

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


def recording_dir():
    base = Path(DATA_FILE).parent
    path = base / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mix_tracks_to_wav(input_paths, output_path):
    if len(input_paths) == 1:
        shutil.copyfile(input_paths[0], output_path)
        return

    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    for input_path in input_paths:
        command.extend(["-i", str(input_path)])

    command.extend([
        "-filter_complex",
        f"amix=inputs={len(input_paths)}:duration=longest:normalize=1",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_path)
    ])

    subprocess.run(command, check=True)


async def pycord_recording_done(sink, ctx):
    state = ACTIVE_RECORDINGS.pop(ctx.guild.id, None) if ctx.guild else None

    if state is None:
        return

    folder = Path(state["folder"])
    output_path = Path(state["output_path"])
    upload_channel = ctx.guild.get_channel(state["upload_channel_id"]) if ctx.guild else None

    try:
        if upload_channel is None:
            return await ctx.reply(embed=warning_embed(ctx, "Upload channel was deleted or not found."), mention_author=False)

        files = []

        for user_id, audio in sink.audio_data.items():
            file_path = folder / f"track-{user_id}.wav"
            audio.file.seek(0)

            with open(file_path, "wb") as f:
                shutil.copyfileobj(audio.file, f)

            if file_path.exists() and file_path.stat().st_size > 1024:
                files.append(file_path)

        print(f"Pycord recording stopped: sources={len(sink.audio_data)}, files={len(files)}", flush=True)

        if not files:
            return await ctx.reply(embed=warning_embed(ctx, "Recording had no usable audio."), mention_author=False)

        mix_tracks_to_wav(files, output_path)

        await upload_channel.send(
            content=f"Recording from **{ctx.guild.name}** stopped by {ctx.author.mention}.",
            file=discord.File(str(output_path), filename=output_path.name)
        )
    except discord.HTTPException:
        await ctx.reply(embed=warning_embed(ctx, "Recording file is too large for Discord upload."), mention_author=False)
    except subprocess.CalledProcessError:
        await ctx.reply(embed=warning_embed(ctx, "Could not mix recording tracks with ffmpeg."), mention_author=False)
    except Exception as e:
        traceback.print_exc()
        await ctx.reply(embed=warning_embed(ctx, f"Recording failed: `{type(e).__name__}`"), mention_author=False)
    finally:
        try:
            if ctx.voice_client:
                await ctx.voice_client.disconnect(force=True)
        except Exception:
            pass

        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass

        try:
            shutil.rmtree(folder)
        except Exception:
            pass


@bot.command(aliases=["setrecordchannel", "recchannel"])
async def recordchannel(ctx, channel: discord.TextChannel = None):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.reply(embed=missing_perm_embed(ctx, "manage_server"), mention_author=False)

    if channel is None:
        return await ctx.reply(
            embed=premium_embed(ctx, "recordchannel", "Set the channel where recordings are sent", ".recordchannel (channel)", ".recordchannel #admin"),
            mention_author=False
        )

    gid = setup_guild(ctx.guild.id)
    TRIGGERS[gid]["recording"]["channel_id"] = channel.id
    save_data()

    await ctx.reply(
        embed=premium_embed(ctx, "recording channel updated", f"Recordings will be sent to {channel.mention}."),
        mention_author=False
    )


@bot.command(aliases=["recsettings"])
async def recordsettings(ctx):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.reply(embed=missing_perm_embed(ctx, "manage_server"), mention_author=False)

    gid = setup_guild(ctx.guild.id)
    channel_id = TRIGGERS[gid]["recording"].get("channel_id")
    channel = ctx.guild.get_channel(channel_id) if channel_id else None
    status = "recording" if ctx.guild.id in ACTIVE_RECORDINGS else "not recording"

    text = (
        f"**upload channel**: {channel.mention if channel else '`not set`'}\n"
        f"**status**: `{status}`\n"
        f"**format**: `wav, 48khz stereo`"
    )

    await ctx.reply(embed=premium_embed(ctx, "recording settings", text), mention_author=False)


@bot.command(aliases=["rec"])
async def record(ctx):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.reply(embed=missing_perm_embed(ctx, "manage_server"), mention_author=False)

    if not hasattr(discord, "sinks") or not hasattr(discord.sinks, "WaveSink"):
        return await ctx.reply(
            embed=warning_embed(ctx, "Pycord voice recording is not available. Check `py-cord[voice]` install."),
            mention_author=False
        )

    if not ensure_opus_loaded():
        return await ctx.reply(
            embed=warning_embed(ctx, "Opus audio library is not loaded on the host."),
            mention_author=False
        )

    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.reply(embed=warning_embed(ctx, "Join a voice channel first."), mention_author=False)

    if ctx.guild.id in ACTIVE_RECORDINGS:
        return await ctx.reply(embed=warning_embed(ctx, "A recording is already running."), mention_author=False)

    gid = setup_guild(ctx.guild.id)
    channel_id = TRIGGERS[gid]["recording"].get("channel_id")
    upload_channel = ctx.guild.get_channel(channel_id) if channel_id else None

    if upload_channel is None:
        return await ctx.reply(
            embed=warning_embed(ctx, "Set an upload channel first with `.recordchannel #channel`."),
            mention_author=False
        )

    voice_channel = ctx.author.voice.channel
    permissions = voice_channel.permissions_for(ctx.guild.me)

    if not permissions.connect:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "connect"), mention_author=False)

    if not permissions.speak:
        return await ctx.reply(embed=bot_missing_perm_embed(ctx, "speak"), mention_author=False)

    if ctx.voice_client:
        await ctx.voice_client.disconnect(force=True)

    session_id = f"recording-{ctx.guild.id}-{uuid4().hex}"
    folder = recording_dir() / session_id
    output_path = recording_dir() / f"{session_id}.wav"
    folder.mkdir(parents=True, exist_ok=True)
    sink = discord.sinks.WaveSink()

    try:
        vc = await voice_channel.connect()
        vc.start_recording(
            sink,
            pycord_recording_done,
            ctx,
            sync_start=True
        )
    except Exception as e:
        traceback.print_exc()

        try:
            shutil.rmtree(folder)
        except Exception:
            pass

        return await ctx.reply(
            embed=warning_embed(ctx, f"Could not start voice recording: `{type(e).__name__}`"),
            mention_author=False
        )

    ACTIVE_RECORDINGS[ctx.guild.id] = {
        "folder": folder,
        "output_path": output_path,
        "voice_channel_id": voice_channel.id,
        "upload_channel_id": upload_channel.id,
        "started_by": ctx.author.id
    }

    print(f"Recording started in guild={ctx.guild.id}, channel={voice_channel.id}", flush=True)

    await ctx.reply(
        embed=premium_embed(
            ctx,
            "recording started",
            f"Now recording {voice_channel.mention}.\nEveryone in the voice channel should know this is being recorded."
        ),
        mention_author=False
    )


@bot.command(aliases=["stoprec", "stoprecording"])
async def stoprecord(ctx):
    if not ctx.author.guild_permissions.manage_guild:
        return await ctx.reply(embed=missing_perm_embed(ctx, "manage_server"), mention_author=False)

    state = ACTIVE_RECORDINGS.get(ctx.guild.id)

    if state is None:
        return await ctx.reply(embed=warning_embed(ctx, "No recording is running."), mention_author=False)

    upload_channel = ctx.guild.get_channel(state["upload_channel_id"])

    if upload_channel is None:
        return await ctx.reply(embed=warning_embed(ctx, "Upload channel was deleted or not found."), mention_author=False)

    vc = ctx.voice_client

    if not vc:
        return await ctx.reply(embed=warning_embed(ctx, "Voice client was not found."), mention_author=False)

    try:
        vc.stop_recording()
    except Exception as e:
        traceback.print_exc()

        return await ctx.reply(
            embed=warning_embed(ctx, f"Could not stop recording: `{type(e).__name__}`"),
            mention_author=False
        )

    await ctx.reply(embed=premium_embed(ctx, "recording stopped", f"Processing and sending recording to {upload_channel.mention}."), mention_author=False)


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
async def on_presence_update(before, after):
    if after.bot or not after.guild:
        return

    gid = setup_guild(after.guild.id)

    vanity = TRIGGERS[gid]["vanity"]

    if not vanity["enabled"]:
        return

    role_id = vanity["role_id"]
    channel_id = vanity["channel_id"]

    if not role_id:
        return

    role = after.guild.get_role(role_id)

    if not role:
        return

    triggers = vanity["triggers"]

    if not triggers:
        return

    status_text = ""

    for activity in after.activities:
        if isinstance(activity, discord.CustomActivity):
            if activity.name:
                status_text += f" {activity.name.lower()}"

            if activity.state:
                status_text += f" {activity.state.lower()}"

    matched = any(trigger in status_text for trigger in triggers)

    has_role = role in after.roles

    channel = after.guild.get_channel(channel_id) if channel_id else None

    if matched and not has_role:
        try:
            await after.add_roles(role, reason="Vanity detected")

            if channel:
                msg = vanity["message"]

                msg = msg.replace("{user}", after.mention)
                msg = msg.replace("{server}", after.guild.name)
                msg = msg.replace("{role}", role.mention)

                embed = discord.Embed(
                    description=msg,
                    color=int(vanity["color"], 16)
                )

                await channel.send(embed=embed)

        except:
            pass

    elif not matched and has_role:
        try:
            await after.remove_roles(role, reason="Vanity removed")

            if channel:
                embed = discord.Embed(
                    description=vanity["remove_message"].replace("{user}", after.mention),
                    color=int(vanity["remove_color"], 16)
                )

                await channel.send(embed=embed)

        except:
            pass

@bot.event
async def on_ready():
    print(f"discord library version: {discord.__version__}", flush=True)

    try:
        import davey
        print(f"davey loaded: {getattr(davey, '__version__', 'installed')}", flush=True)
    except Exception:
        print("davey not loaded; Discord DAVE voice may sound corrupted", flush=True)

    if ensure_opus_loaded():
        print("Opus loaded for voice recording", flush=True)
    else:
        print("Opus not loaded; voice recording will not work", flush=True)

    print(f"Logged in as {bot.user}", flush=True)


bot.run(TOKEN)
