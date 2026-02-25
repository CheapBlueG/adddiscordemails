import discord
from discord import app_commands
import json
import os
from datetime import datetime
import re
import platform
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Discord client with necessary intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ==================== CONFIGURATION ====================
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1399288304767074404"))
DISPENSE_CHANNEL_ID = int(os.getenv("DISPENSE_CHANNEL_ID", "1399288331270885456"))
RESTRICTED_ROLE_ID = int(os.getenv("RESTRICTED_ROLE_ID", "1399298671627079791"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))  # Set in .env
GUILD_ID = int(os.getenv("GUILD_ID", "1399288278066270218"))

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
    """Read email:password pairs from emailstouse.txt, skipping invalid lines."""
    emails = []
    try:
        if os.path.exists(EMAIL_SOURCE_FILE):
            with open(EMAIL_SOURCE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line:
                        emails.append(line)
                    else:
                        print(f"Skipping invalid line in {EMAIL_SOURCE_FILE}: '{line}'")
        else:
            print(f"Error: {EMAIL_SOURCE_FILE} does not exist.")
        return emails
    except Exception as e:
        print(f"Error reading {EMAIL_SOURCE_FILE}: {e}")
        return emails


def _default_data():
    """Return default data structure, loading emails from txt if available."""
    return {
        "group_k": {"emails": load_emails_from_txt(), "token_emails": [], "dispensed": {}},
        "group_j": {"emails": [], "token_emails": [], "dispensed": {}},
        "user_groups": {},
    }


def load_emails():
    """Load emails from emails.json, or initialize from emailstouse.txt if missing or invalid."""
    try:
        if os.path.exists(EMAIL_STORAGE_FILE):
            if os.path.getsize(EMAIL_STORAGE_FILE) == 0:
                print(f"Error: {EMAIL_STORAGE_FILE} is empty. Initializing with default structure.")
                default_data = _default_data()
                save_emails(default_data)
                return default_data

            with open(EMAIL_STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Add token_emails support if missing (backward compatibility)
            for g in ["group_k", "group_j"]:
                if g in data and "token_emails" not in data[g]:
                    data[g]["token_emails"] = []

            if not all(key in data for key in ["group_k", "group_j", "user_groups"]):
                print(f"Error: Invalid structure in {EMAIL_STORAGE_FILE}. Reinitializing.")
                default_data = _default_data()
                save_emails(default_data)
                return default_data

            return data
        else:
            print(f"Error: {EMAIL_STORAGE_FILE} does not exist. Creating with emails from {EMAIL_SOURCE_FILE}.")
            default_data = _default_data()
            save_emails(default_data)
            return default_data
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {EMAIL_STORAGE_FILE}: {e}. Initializing with emails from {EMAIL_SOURCE_FILE}.")
        default_data = _default_data()
        save_emails(default_data)
        return default_data
    except Exception as e:
        print(f"Error reading {EMAIL_STORAGE_FILE}: {e}. Initializing with emails from {EMAIL_SOURCE_FILE}.")
        default_data = _default_data()
        save_emails(default_data)
        return default_data


def save_emails(data):
    """Save email data to emails.json with file locking."""
    try:
        if not all(key in data for key in ["group_k", "group_j", "user_groups"]):
            print(f"Error: Invalid data structure when saving to {EMAIL_STORAGE_FILE}. Skipping save.")
            return
        with open(EMAIL_STORAGE_FILE, "w", encoding="utf-8") as f:
            size = os.path.getsize(EMAIL_STORAGE_FILE) if os.path.exists(EMAIL_STORAGE_FILE) else 1
            _lock_file(f, size)
            print(
                f"Saving data to {EMAIL_STORAGE_FILE}: "
                f"group_k {len(data['group_k']['emails'])}, "
                f"group_j {len(data['group_j']['emails'])}, "
                f"token emails K:{len(data['group_k'].get('token_emails', []))}, "
                f"J:{len(data['group_j'].get('token_emails', []))}"
            )
            json.dump(data, f, indent=4)
            f.flush()
            _unlock_file(f, os.path.getsize(EMAIL_STORAGE_FILE))
    except Exception as e:
        print(f"Error writing to {EMAIL_STORAGE_FILE}: {e}")


def split_message(content, max_length=2000):
    """Split a message into chunks under max_length characters."""
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


# ====================== BOT STARTUP ======================

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    try:
        # Copy commands to guild first (instant sync)
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        print(f"Slash commands synced instantly to guild {GUILD_ID}")

        # Then clear old global commands (removes duplicates)
        tree.clear_commands(guild=None)
        await tree.sync()
        print("Cleared global commands")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")
    print("------")


# ====================== ORIGINAL COMMANDS ======================

@tree.command(name="get", description="Dispense email:password pairs to a user")
@app_commands.describe(name="Name for logging", amount="Number of email:password pairs to dispense")
async def get_emails(interaction: discord.Interaction, name: str, amount: int):
    try:
        await interaction.response.defer(ephemeral=True)
        if interaction.channel_id != DISPENSE_CHANNEL_ID:
            await interaction.followup.send("This command can only be used in the designated dispense channel.", ephemeral=True)
            return
        email_data = load_emails()
        user_id = str(interaction.user.id)
        if user_id not in email_data["user_groups"]:
            await interaction.followup.send("You are not assigned to any group. Contact an admin.", ephemeral=True)
            return
        group = email_data["user_groups"][user_id]
        group_key = "group_" + group.lower()
        if group_key not in email_data:
            await interaction.followup.send("Invalid group assignment. Contact an admin.", ephemeral=True)
            return
        group_data = email_data[group_key]
        print(f"Loaded {len(group_data['emails'])} emails for group {group} before dispensing: {group_data['emails'][:5] + ['...'] if len(group_data['emails']) > 5 else group_data['emails']}")
        if amount < 1:
            await interaction.followup.send("Please request at least 1 email:password pair.", ephemeral=True)
            return
        if amount > len(group_data["emails"]):
            await interaction.followup.send(f"Not enough email:password pairs available in your group. Only {len(group_data['emails'])} pairs remain.", ephemeral=True)
            return
        dispensed_emails = group_data["emails"][:amount]
        group_data["emails"] = group_data["emails"][amount:] if len(group_data["emails"]) > amount else []
        print(f"Dispensing {len(dispensed_emails)} emails for group {group}: {dispensed_emails}, {len(group_data['emails'])} remain: {group_data['emails'][:5] + ['...'] if len(group_data['emails']) > 5 else group_data['emails']}")
        if user_id not in group_data["dispensed"]:
            group_data["dispensed"][user_id] = []
        group_data["dispensed"][user_id].extend([(name, email, datetime.now().isoformat()) for email in dispensed_emails])
        save_emails(email_data)
        email_message = "\n".join(dispensed_emails)
        await interaction.user.send(f"Here are your {amount} email:password pair(s) from group {group}:\n{email_message}")
        await interaction.followup.send(f"{interaction.user.mention} has taken {amount} email:password pair(s) from group {group}. {len(group_data['emails'])} pair(s) remain.", ephemeral=False)
        log_channel = client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            log_message = f"User: {interaction.user.name} ({name}), Group: {group}, Took: {amount} email:password pair(s), Remaining: {len(group_data['emails'])}, Time: {datetime.now().isoformat()}"
            await log_channel.send(log_message)
        else:
            print(f"Error: Log channel {LOG_CHANNEL_ID} not found or inaccessible.")
    except Exception as e:
        print(f"Error in /get command: {e}")
        try:
            await interaction.followup.send("An error occurred while processing your request. Please try again later.", ephemeral=True)
        except discord.errors.HTTPException as followup_error:
            print(f"Error sending followup in /get: {followup_error}")


@tree.command(name="addemail", description="Add email:password pairs to the database")
@app_commands.describe(email="Email:password pairs (e.g., email1:pass1 email2:pass2 or email1:pass1,email2:pass2)", group="Group to add to (K or J)")
@app_commands.choices(group=[app_commands.Choice(name="K", value="K"), app_commands.Choice(name="J", value="J")])
async def add_email(interaction: discord.Interaction, email: str, group: str):
    try:
        await interaction.response.defer(ephemeral=True)
        if interaction.channel_id != DISPENSE_CHANNEL_ID:
            await interaction.followup.send("This command can only be used in the designated dispense channel.", ephemeral=True)
            return
        email_list = re.split(r"[,\s\n]+", email.strip())
        email_list = [e.strip() for e in email_list if e.strip()]
        if not email_list:
            await interaction.followup.send("No valid email:password pairs provided.", ephemeral=True)
            return
        email_data = load_emails()
        group_key = "group_" + group.lower()
        if group_key not in email_data:
            await interaction.followup.send("Invalid group specified.", ephemeral=True)
            return
        group_data = email_data[group_key]
        print(f"Loaded {len(group_data['emails'])} emails for group {group} before adding: {group_data['emails'][:5] + ['...'] if len(group_data['emails']) > 5 else group_data['emails']}")
        added_emails = []
        skipped_emails = []
        for email_entry in email_list:
            if ":" not in email_entry:
                skipped_emails.append((email_entry, "Invalid format (missing colon)"))
                continue
            if email_entry in group_data["emails"]:
                skipped_emails.append((email_entry, "Already in database for this group"))
                continue
            group_data["emails"].append(email_entry)
            added_emails.append(email_entry)
        if added_emails:
            print(f"Adding {len(added_emails)} emails to group {group}: {', '.join(added_emails[:5]) + (', ...' if len(added_emails) > 5 else '')}")
            save_emails(email_data)
            print(f"After adding to group {group}, {len(group_data['emails'])} emails in stock: {group_data['emails'][:5] + ['...'] if len(group_data['emails']) > 5 else group_data['emails']}")
        response = []
        if added_emails:
            response.append(f"Successfully added {len(added_emails)} email:password pair(s) to group {group}:\n" + "\n".join(added_emails[:10]) + (f"\n...and {len(added_emails)-10} more" if len(added_emails) > 10 else ""))
        if skipped_emails:
            response.append("Skipped:\n" + "\n".join([f"{e}: {reason}" for e, reason in skipped_emails[:10]]) + (f"\n...and {len(skipped_emails)-10} more" if len(skipped_emails) > 10 else ""))
        response_text = "\n".join(response) or "No emails added."
        for message in split_message(response_text):
            await interaction.followup.send(message, ephemeral=True)
        log_channel = client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            if added_emails:
                log_message = f"User: {interaction.user.name}, Added {len(added_emails)} email:password pair(s) to group {group}: {', '.join(added_emails[:5]) + (', ...' if len(added_emails) > 5 else '')}, Time: {datetime.now().isoformat()}"
                for log_part in split_message(log_message):
                    await log_channel.send(log_part)
            if skipped_emails:
                log_message = f"User: {interaction.user.name}, Skipped {len(skipped_emails)} email:password pair(s) for group {group}: {', '.join([f'{e} ({reason})' for e, reason in skipped_emails[:5]]) + (', ...' if len(skipped_emails) > 5 else '')}, Time: {datetime.now().isoformat()}"
                for log_part in split_message(log_message):
                    await log_channel.send(log_part)
        else:
            print(f"Error: Log channel {LOG_CHANNEL_ID} not found or inaccessible.")
    except Exception as e:
        print(f"Error in /addemail command: {e}")
        try:
            await interaction.followup.send("An error occurred while adding the emails. Please try again later.", ephemeral=True)
        except discord.errors.HTTPException as followup_error:
            print(f"Error sending followup in /addemail: {followup_error}")


@tree.command(name="assigngroup", description="Assign a user to a group (admin only)")
@app_commands.describe(user="User to assign", group="Group K or J")
@app_commands.choices(group=[app_commands.Choice(name="K", value="K"), app_commands.Choice(name="J", value="J")])
async def assign_group(interaction: discord.Interaction, user: discord.Member, group: str):
    try:
        await interaction.response.defer(ephemeral=True)
        if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return
        email_data = load_emails()
        user_id = str(user.id)
        old_group = email_data["user_groups"].get(user_id, None)
        email_data["user_groups"][user_id] = group.upper()
        save_emails(email_data)
        if old_group:
            await interaction.followup.send(f"✅ {user.mention} has been reassigned from group **{old_group}** to group **{group.upper()}**.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ {user.mention} has been assigned to group **{group.upper()}**.", ephemeral=True)
        log_channel = client.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"Admin: {interaction.user.name} assigned {user.name} to Group {group.upper()}, Time: {datetime.now().isoformat()}")
    except Exception as e:
        print(f"Error in /assigngroup command: {e}")
        try:
            await interaction.followup.send("An error occurred while assigning the group.", ephemeral=True)
        except discord.errors.HTTPException as followup_error:
            print(f"Error sending followup in /assigngroup: {followup_error}")


@tree.command(name="viewstock", description="View current email stock for your group")
async def view_stock(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
        if interaction.channel_id != DISPENSE_CHANNEL_ID:
            await interaction.followup.send("This command can only be used in the designated dispense channel.", ephemeral=True)
            return
        has_permission = any(role.id in (RESTRICTED_ROLE_ID, ADMIN_ROLE_ID) for role in interaction.user.roles)
        if not has_permission:
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return
        email_data = load_emails()
        lines = ["📦 **Current Email Stock:**\n"]
        for group_name, group_key in [("K", "group_k"), ("J", "group_j")]:
            group_data = email_data.get(group_key, {})
            email_count = len(group_data.get("emails", []))
            token_count = len(group_data.get("token_emails", []))
            lines.append(f"**Group {group_name}:**")
            lines.append(f"  • Email:Pass — {email_count}")
            lines.append(f"  • Token Emails — {token_count}")
            lines.append("")
        await interaction.followup.send("\n".join(lines), ephemeral=True)
    except Exception as e:
        print(f"Error in /viewstock command: {e}")
        try:
            await interaction.followup.send("An error occurred while viewing stock.", ephemeral=True)
        except discord.errors.HTTPException as followup_error:
            print(f"Error sending followup in /viewstock: {followup_error}")


@tree.command(name="stockcount", description="Quick stock count for all groups")
async def stock_count(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
        if interaction.channel_id != DISPENSE_CHANNEL_ID:
            await interaction.followup.send("This command can only be used in the designated dispense channel.", ephemeral=True)
            return
        email_data = load_emails()
        k_emails = len(email_data.get("group_k", {}).get("emails", []))
        k_tokens = len(email_data.get("group_k", {}).get("token_emails", []))
        j_emails = len(email_data.get("group_j", {}).get("emails", []))
        j_tokens = len(email_data.get("group_j", {}).get("token_emails", []))
        total = k_emails + k_tokens + j_emails + j_tokens
        await interaction.followup.send(
            f"📊 **Stock Count:**\n"
            f"Group K: {k_emails} emails, {k_tokens} tokens\n"
            f"Group J: {j_emails} emails, {j_tokens} tokens\n"
            f"**Total: {total}**",
            ephemeral=True,
        )
    except Exception as e:
        print(f"Error in /stockcount command: {e}")
        try:
            await interaction.followup.send("An error occurred while counting stock.", ephemeral=True)
        except discord.errors.HTTPException as followup_error:
            print(f"Error sending followup in /stockcount: {followup_error}")


# ====================== TOKEN COMMANDS ======================

@tree.command(name="addtoken", description="Add email:pass:token:clientid (admin only)")
@app_commands.describe(entry="Full string: email:pass:token:clientid", group="Group to add to (K or J)")
@app_commands.choices(group=[app_commands.Choice(name="K", value="K"), app_commands.Choice(name="J", value="J")])
async def add_token(interaction: discord.Interaction, entry: str, group: str):
    await interaction.response.defer(ephemeral=True)
    if interaction.channel_id != DISPENSE_CHANNEL_ID:
        await interaction.followup.send("This command can only be used in the designated dispense channel.", ephemeral=True)
        return
    if not any(role.id == ADMIN_ROLE_ID for role in interaction.user.roles):
        await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
        return
    if entry.count(":") < 2:
        await interaction.followup.send("Invalid format. Must be email:pass:token:clientid", ephemeral=True)
        return
    email_data = load_emails()
    group_key = "group_" + group.lower()
    if entry in email_data[group_key]["token_emails"]:
        await interaction.followup.send("This token email already exists in the group.", ephemeral=True)
        return
    email_data[group_key]["token_emails"].append(entry)
    save_emails(email_data)
    await interaction.followup.send(f"✅ Successfully added 1 token email to **Group {group}**", ephemeral=True)
    log_channel = client.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"Admin: {interaction.user.name} added token email to Group {group}, Time: {datetime.now().isoformat()}")


@tree.command(name="gettoken", description="Dispense email:pass:token:clientid (private DM)")
@app_commands.describe(amount="Number of token emails to dispense")
async def get_token(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    if interaction.channel_id != DISPENSE_CHANNEL_ID:
        await interaction.followup.send("This command can only be used in the designated dispense channel.", ephemeral=True)
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
        await interaction.followup.send("Please request at least 1 token email.", ephemeral=True)
        return
    if amount > len(group_data["token_emails"]):
        await interaction.followup.send(f"Not enough token emails available in your group. Only {len(group_data['token_emails'])} remain.", ephemeral=True)
        return
    dispensed = group_data["token_emails"][:amount]
    group_data["token_emails"] = group_data["token_emails"][amount:]
    save_emails(email_data)
    # Clean private DM
    dm_lines = ["⚠️ **WARNING: These are REAL accounts with tokens. Use carefully.**\n"]
    for item in dispensed:
        parts = item.split(":", 2)
        if len(parts) == 3:
            dm_lines.append(f"**Email:** {parts[0]}")
            dm_lines.append(f"**Password:** {parts[1]}")
            dm_lines.append(f"**Token + Client ID:** {parts[2]}\n")
        else:
            dm_lines.append(f"**Full string:** {item}\n")
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


# ====================== RUN THE BOT ======================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set. Add it to your .env file.")
client.run(TOKEN)
