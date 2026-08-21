# Twitch Chat Bot — TTS, SFX, Quotes, Custom Commands & More

A TwitchIO-based chat bot that reads out chat messages / cheers via text-to-speech,
plays sound effects on command, maintains a quote database synced to a Google Doc,
tracks a running "boom count" per user, and lets lead moderators create their own
custom text commands on the fly — all without restarting the bot.

## Features

- **Bits/Cheer TTS** — any message with Bits attached is read aloud automatically.
- **`!tts <text>`** — lead mods can make the bot speak arbitrary text.
- **Sound effects (`SFX_COMMANDS`)** — trigger local audio files by chat command.
- **Multi-device audio output** — TTS and SFX play out to multiple audio devices
  at once (e.g. your headphones *and* a virtual cable feeding OBS).
- **Quote system (`!quote`)** — add, remove, look up, and randomly pull quotes,
  automatically kept in sync with a shared Google Doc.
- **Boom tracker (`!boom`, `!boomcheck`)** — a running per-user counter the
  broadcaster can increment manually, with a public checker anyone can use.
- **Custom commands (`!command`)** — lead mods can add/edit/remove simple
  text-response commands without touching code or restarting the bot.
- **`!commands`** — points chat to a Google Doc listing all available commands.

## Requirements

- Python 3.10+ (a fixed TwitchIO version is required — see below) in coding i used 14.3 so that is my suggestion
- Windows (the TTS pipeline uses `pyttsx3`'s SAPI5 backend and `pywin32` for COM
  threading; other platforms would need adjustments to `_speak_once`)

## Quick Start

### 1. Get the code and create a virtual environment

```bash
cd C:\Users\YOUR_USER  # Change YOUR_USER to an actual user
git clone https://github.com/TheBigChicken85/SimpleTBS.git
cd SimpleTBS                     # If this fails find the exact path to this folder (usually something like C:\Users\YOUR_USER\SimpleTBS)
python -m venv .venv
.venv\Scripts\activate.bat       # Command Prompt
.venv\Scripts\Activate.ps1       # PowerShell
```

> [Git for Windows](https://git-scm.com/download/win) is
> required for this installation method to work

### 2. Install dependencies from `requirements.txt`

> **Important:** This script is written for **TwitchIO 2.x**. TwitchIO 3.x
> changed its authentication model (it requires a `client_secret` and full OAuth
> app flow) and will fail immediately with
> `RuntimeError: Expected a valid "client_secret", instead received: None`
> if installed. The `<3.0` pin above is required, not optional.

Install dependancies:

```bash
pip install -r requirements.txt
```

### 3. Fill in every placeholder in the script

This script ships with placeholder values everywhere something personal needs
to go. **The bot will not run correctly until every item below is filled in.**
They're listed in the order they appear in the file:

| # | Variable / location | What to put there |
|---|---|---|
| 1 | `QUOTES_FILE` | Full path to where the quotes JSON file should live, e.g. `r"C:\path\to\quotes.json"` |
| 2 | `SFX_COMMANDS` dict | Your own `"!trigger": "filename"` pairs, e.g. `{"!airhorn": "airhorn"}`. Filename must match a file in `SFX_DIR` (extension omitted — `.mp3`/`.wav`/`.ogg` are all auto-detected) |
| 3 | `SFX_DIR` | Full path to the folder holding your sound effect files |
| 4 | `OUTPUT_DEVICES` | List of audio output device indices to play TTS/SFX to. Find yours by running: `python -c "import sounddevice as sd; print(sd.query_devices())"` |
| 5 | `BOT_NICK` | Your bot account's Twitch username |
| 6 | `TOKEN` | Your bot's OAuth token (including the `oauth:` prefix), from [twitchtokengenerator.com](https://twitchtokengenerator.com/) (scopes: `chat:read`, `chat:edit`) |
| 7 | `CHANNEL` | The channel name the bot should join (no `#`) |
| 8 | `CLIENT_ID` | The Client ID shown alongside your token on the token generator page. The default in the script is the token generator's own public client ID — replace it if you register your own Twitch application |
| 9 | `LEAD_MODERATORS` | Set of lowercase Twitch usernames allowed to use mod-gated commands, e.g. `{"mymod1", "mymod2"}` |
| 10 | `BOOM_COUNTS_FILE` | Full path to where the boom-counts JSON file should live.
| 11 | `MIN_BITS` | Optional — minimum bits before a cheer is read aloud. Defaults to `1`, change only if you want a higher threshold |
| 12 | `CUSTOM_COMMANDS_FILE` | Full path to where the custom-commands JSON file should live |
| 13 | `RESERVED_COMMANDS` | Add any built-in trigger words you want protected from being overwritten by `!command add`, e.g. `{"!tts", "!quote", "!boom", "!boomcheck", "!commands", "!command"}`. SFX triggers are merged in automatically — you don't need to repeat those |
| 14 | `GOOGLE_CREDS_FILE` | Full path to your Google service account JSON key (see Google Docs setup below) |
| 15 | `GOOGLE_DOC_ID` | The ID portion of your Google Doc's URL (see Google Docs setup below) |
| 16 | `!commands` handler, inside `event_message` | Replace `"https://your_google_doc_link_here"` with the real share link to your command-list doc |

Every one of these can alternatively be supplied via an environment variable
instead of editing the script directly (see table below) — the script checks
the environment variable first and only falls back to the hardcoded value if
it isn't set.

| Environment variable | Overrides |
|---|---|
| `TWITCH_BOT_NICK` | `BOT_NICK` |
| `TWITCH_OAUTH_TOKEN` | `TOKEN` |
| `TWITCH_CHANNEL` | `CHANNEL` |
| `TWITCH_CLIENT_ID` | `CLIENT_ID` |
| `MIN_BITS` | `MIN_BITS` |
| `QUOTES_FILE` | `QUOTES_FILE` |
| `SFX_DIR` | `SFX_DIR` |
| `BOOM_COUNTS_FILE` | `BOOM_COUNTS_FILE` |
| `CUSTOM_COMMANDS_FILE` | `CUSTOM_COMMANDS_FILE` |
| `GOOGLE_CREDS_FILE` | `GOOGLE_CREDS_FILE` |
| `GOOGLE_DOC_ID` | `GOOGLE_DOC_ID` |

On Windows (PowerShell), for example:

```powershell
$env:TWITCH_BOT_NICK = "your_bot_name"
$env:TWITCH_OAUTH_TOKEN = "oauth:xxxxxxxxxxxxxxxxxxxxxxxxx"
$env:TWITCH_CHANNEL = "your_channel"
$env:TWITCH_CLIENT_ID = "your_client_id"
```

`OUTPUT_DEVICES`, `SFX_COMMANDS`, `LEAD_MODERATORS`, and `RESERVED_COMMANDS`
are Python data structures rather than simple strings, so those four must be
edited directly in the script — they can't be set via environment variable.

### 4. Audio device setup (optional, for multi-output)

To route TTS/SFX to more than one device at once (e.g. your headphones *and* a
stream mix), set up a virtual audio device such as **VB-Audio Virtual Cable** or
**Voicemeeter** (Windows) and list its device index alongside your normal output 
in `OUTPUT_DEVICES`.

### 5. Google Docs sync (optional, for `!quote book`)

1. In [Google Cloud Console](https://console.cloud.google.com/), create/select a
   project and enable the **Google Docs API**.
2. Create a **Service Account**, then generate a **JSON key** for it — this is
   your `GOOGLE_CREDS_FILE`.
3. Create a Google Doc, click **Share**, and give the service account's email
   (found in the JSON key file as `client_email`) **Editor** access.
4. Copy the Doc ID from its URL
   (`https://docs.google.com/document/d/DOC_ID_HERE/edit`) into `GOOGLE_DOC_ID`.

If you skip the Google setup entirely, quote add/remove will still work
locally — only the Doc sync (and thus `!quote book`) will fail, logging an
error to console instead of crashing the bot.

### 6. Run it

```bash
python twitch_bot.py
```

## Commands

### Everyone

| Command | Description |
|---|---|
| `!quote` | Shows a random saved quote |
| `!quote <number>` | Shows a specific quote by ID |
| `!quote book` | Links the Google Doc containing all quotes |
| `!boomcheck <username>` | Shows how many times a user has been "boomed" |
| `!commands` | Links the Google Doc listing all commands |
| any custom command | Replies with its saved text (see `!command` below) |

### Lead moderators only (`LEAD_MODERATORS`)

| Command | Description |
|---|---|
| `!tts <text>` | Makes the bot speak the given text aloud |
| `!<sfx trigger>` | Plays the mapped sound effect (see `SFX_COMMANDS`) |
| `!quote add <text>` | Adds a new quote |
| `!quote remove <number>` | Removes a quote by ID and renumbers the rest |
| `!command add !trigger <response>` | Creates a new custom command |
| `!command edit !trigger <response>` | Edits an existing custom command |
| `!command remove !trigger` | Deletes a custom command |
| `!command list` | Lists all current custom command triggers |

### Broadcaster only

| Command | Description |
|---|---|
| `!boom <username>` | Manually increments a user's boom count |

## Data files

The bot persists state to JSON files on disk (paths configured via the
environment variables above): quotes, per-user boom counts, and custom
commands all survive restarts. Back these up if you want to preserve your
data across reinstalls.

> **Tip:** Anchor these paths to the script's own folder rather than hardcoding
> an absolute path, so the bot behaves consistently regardless of which
> directory it's launched from:
> ```python
> SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
> QUOTES_FILE = os.environ.get("QUOTES_FILE", os.path.join(SCRIPT_DIR, "quotes.json"))
> ```

## Security notes

- Treat your **OAuth token** and **Google service account JSON key** as
  passwords. Never commit them to a public repository.

- If a token or key is ever exposed, rotate it immediately via
  twitchtokengenerator.com or the Google Cloud Console.

## Known platform notes

- TTS relies on Windows' SAPI5 voices via `pyttsx3`; each utterance runs in its
  own thread with explicit COM initialization (`pythoncom.CoInitialize()`),
  since SAPI5 requires COM to be initialized per-thread.
- Multi-device playback uses `sounddevice.OutputStream` per device rather than
  the simpler `sd.play()`, since `sd.play()` shares global playback state and
  breaks under concurrent calls from multiple threads.
