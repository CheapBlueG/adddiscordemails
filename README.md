# Discord Dispense Bot

A Discord bot for dispensing email credentials with group-based access control.

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
   cd YOUR_REPO
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and fill in your `DISCORD_TOKEN` and `ADMIN_ROLE_ID`.

4. **Prepare data** (optional)
   Create a `data/` folder and add an `emailstouse.txt` file with one `email:password` per line.

5. **Run**
   ```bash
   python bot.py
   ```

## Commands

| Command | Description | Access |
|---------|-------------|--------|
| `/gettoken <amount>` | Dispense token emails via DM | Group members |
| `/addtoken <entry> <group>` | Add a token email to a group | Admin only |

## Notes

- The bot token is loaded from the `DISCORD_TOKEN` environment variable — **never commit it**.
- Data files (`emails.json`, `emailstouse.txt`) are stored in the `data/` folder and excluded from Git.
- Works on both Windows and Linux (cross-platform file locking).
