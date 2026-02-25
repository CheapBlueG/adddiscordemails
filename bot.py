import discord
from discord import app_commands
import json
import os
from datetime import datetime
from dotenv import load_dotenv
import platform
import random
import string

# Load environment variables from .env file
load_dotenv()

# Initialize Discord client
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ==================== CONFIGURATION ====================
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1399288304767074404"))
DISPENSE_CHANNEL_ID = int(os.getenv("DISPENSE_CHANNEL_ID", "1399288331270885456"))
RESTRICTED_ROLE_ID = int(os.getenv("RESTRICTED_ROLE_ID", "1399298671627079791"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))  # Set in .env

# Use a 'data' folder relative to the script for portability
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)

EMAIL_STORAGE_FILE = os.path.join(DATA_DIR, "emails.json")
EMAIL_SOURCE_FILE = os.path.join(DATA_DIR, "emailstouse.txt")
# =====================================================


# ---------- Cross-platform file locking ----------
def _lock_file(f, length):
    """Acquire a non-blocking lock on an open file."""
    if platform.system() == "Windows":
        import msvcrt
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, max(length, 1))
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(f, length):
    """Release the lock on an open file."""
    if platform.system() == "Windows":
        import msvcrt
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, max(length, 1))
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# ---------- Email helpers ----------
def load_emails_from_txt():
    emails = []
    try:
        if os.path.exists(EMAIL_SOURCE_FILE):
            with open(EMAIL_SOURCE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        emails.append(line)
    except Exception as e:
        print(f"Error reading emailstouse.txt: {e}")
    return emails


def _default_data():
    return {
        "group_k": {"emails": load_emails_from_txt(), "token_emails": [], "dispensed": {}},
        "group_j": {"emails": [], "token_emails": [], "dispensed": {}},
        "user_groups": {},
    }


def load_emails():
    try:
        if os.path.exists(EMAIL_STORAGE_FILE):
            if os.path.getsize(EMAIL_STORAGE_FILE) == 0:
                default_data = _default_data()
                save_emails(default_data)
                return default_data

            with open(EMAIL_STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Migrate old structure if needed
            for g in ("group_k", "group_j"):
                if g not in data:
                    data[g] = {"emails": [], "token_emails": [], "dispensed": {}}
                if "token_emails" not in data[g]:
                    data[g]["token_emails"] = []
            if "user_groups" not in data:
                data["user_groups"] = {}

            save_emails(data)  # save migrated version
            return data
        else:
            default_data = _default_data()
            save_emails(default_data)
            return default_data
    except Exception as e:
        print(f"Error loading emails.json: {e}")
        default_data = _default_data()
        save_emails(default_data)
        return default_data


def save_emails(data):
    try:
        with open(EMAIL_STORAGE_FILE, "w", encoding="utf-8") as f:
            size = os.path.getsize(EMAIL_STORAGE_FILE) if os.path.exists(EMAIL_STORAGE_FILE) else 1
            _lock_file(f, size)
            json.dump(data, f, indent=4)
            f.flush()
            _unlock_file(f, os.path.getsize(EMAIL_STORAGE_FILE))
    except Exception as e:
        print(f"Error saving emails.json: {e}")


def split_message(content, max_length=2000):
    if len(content) <= max_length:
        return [content]
    messages = []
    current = ""
    for line in content.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            messages.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        messages.append(current)
    return messages


# ====================== COMMANDS ======================

@tree.command(name="gettoken", description="Dispense email:pass:token:clientid (one per line in DM)")
@app_commands.describe(amount="Number of token emails to dispense")
async def get_token(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)

    if interaction.channel_id != DISPENSE_CHANNEL_ID:
        await interaction.followup.send("This command can only be used in the dispense channel.", ephemeral=True)
        return

    email_data = load_emails()
    user_id = str(interaction.user.id)
    if user_id not in email_data["user_groups"]:
        await interaction.followup.send("You are not assigned to any group. Contact an admin.", ephemeral=True)
        return

    group = email_data["user_groups"][user_id]
    group_key = "group_" + group.lower()
    group_data = email_data[group_key]

    if amount < 1:
        await interaction.followup.send("Amount must be at least 1.", ephemeral=True)
        return
    if amount > len(group_data["token_emails"]):
        await interaction.followup.send(
            f"Only {len(group_data['token_emails'])} token emails left in group {group}.",
            ephemeral=True,
        )
        return

    dispensed = group_data["token_emails"][:amount]
    group_data["token_emails"] = group_data["token_emails"][amount:]

    # Build DM message
    dm_lines = ["**Here are your email-with-token details:**\n"]
    for full in dispensed:
        parts = full.split(":", 2)
        if len(parts) == 3:
            email, password, token_client = parts
            dm_lines.append(f"**Email:** {email}")
            dm_lines.append(f"**Password:** {password}")
            dm_lines.append(f"**Token + Client ID:** {token_client}\n")
        else:
            dm_lines.append(f"**Full string:** {full}\n")

    await interaction.user.send("\n".join(dm_lines))

    await interaction.followup.send(
        f"{interaction.user.mention} has taken {amount} email-with-token from group {group}. "
        f"{len(group_data['token_emails'])} remain.",
        ephemeral=False,
    )

    log_channel = client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(
            f"User: {interaction.user.name}, Group: {group}, Took: {amount} email-with-token, "
            f"Remaining: {len(group_data['token_emails'])}, Time: {datetime.now().isoformat()}"
        )

    save_emails(email_data)


@tree.command(name="addtoken", description="Add email:pass:token:clientid (admin chooses group)")
@app_commands.describe(entry="Full string: email:pass:token:clientid", group="Group K or J")
@app_commands.choices(
    group=[
        app_commands.Choice(name="K", value="K"),
        app_commands.Choice(name="J", value="J"),
    ]
)
async def add_token(interaction: discord.Interaction, entry: str, group: str):
    await interaction.response.defer(ephemeral=True)

    if interaction.channel_id != DISPENSE_CHANNEL_ID:
        await interaction.followup.send("Wrong channel.", ephemeral=True)
        return
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.followup.send("Admin only.", ephemeral=True)
        return

    # Validate format (must have at least 2 colons → 3 parts)
    if entry.count(":") < 2:
        await interaction.followup.send("Invalid format. Must be email:pass:token:clientid", ephemeral=True)
        return

    email_data = load_emails()
    group_key = "group_" + group.lower()
    group_data = email_data[group_key]

    if entry in group_data["token_emails"]:
        await interaction.followup.send("Already exists in this group.", ephemeral=True)
        return

    group_data["token_emails"].append(entry)
    save_emails(email_data)

    await interaction.followup.send(f"Added 1 token email to group {group}.", ephemeral=True)

    log_channel = client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"Admin {interaction.user.name} added token email to group {group}")


# ====================== BOT STARTUP ======================

@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")


# Run the bot — token is read from the DISCORD_TOKEN environment variable
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set. Add it to your .env file.")
client.run(TOKEN)
