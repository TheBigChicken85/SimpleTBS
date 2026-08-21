#Features can be removed by commenting out the relevant sections of the code.
#These sections are almost always in the event_message() function

import re
import asyncio
import os
import queue
import threading
import pyttsx3
from twitchio.ext import commands

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
import pythoncom
import sounddevice as sd
import soundfile as sf
import tempfile

import json
QUOTES_FILE = os.environ.get("QUOTES_FILE", "path_to_quotes.json")  # Replace with your actual quotes JSON file path

SFX_COMMANDS = {
    "!sfx my_sfx": "my_sfx", # Replace with your desired sound effect command and actual sound effect name (without extension)
}
SFX_DIR = os.environ.get("SFX_DIR", "path_to_sfx_directory")  # Replace with your actual sound effects directory path
OUTPUT_DEVICES = [0, 1]  # Replace with your actual output device indices from sd_setup.py
# ---- Configuration --------------------------------------------------------
BOT_NICK = os.environ.get("TWITCH_BOT_NICK", "")#your bot nickname here
TOKEN = os.environ.get("TWITCH_OAUTH_TOKEN", "oauth:xxxxxxxxxxxxxxxxxxxxxxxxxxxxx")  # your bot oauth token here
CHANNEL = os.environ.get("TWITCH_CHANNEL", "")  # the channel the bot should join (without the #)
# The Client ID tied to the OAuth token above (from the same token generator
# page). Newer versions of twitchio require this to be passed explicitly.
CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "gp762nuuoqcoxypju8c569th9wz7q5")
LEAD_MODERATORS = {}  #the people who should be allowed to use all commands go here (lowercase usernames, without the @). Example: {"bad_mod", "another_mod"}
BOOM_COUNTS_FILE = os.environ.get("BOOM_COUNTS_FILE", "path_to_boom_counts.json")  # Replace with your actual path to the boom counts JSON file
# Minimum number of bits required before a message gets read out loud.
# Set to 0 or 1 to read every cheer regardless of amount.
MIN_BITS = int(os.environ.get("MIN_BITS", "1"))

from googleapiclient.discovery import build
from google.oauth2 import service_account
CUSTOM_COMMANDS_FILE = os.environ.get("CUSTOM_COMMANDS_FILE", "path_to_custom_commands.json") #insert your actual path to the custom commands JSON file

RESERVED_COMMANDS = {
    #insert all reserved commands here, so mods don't accidentally overwrite them with !command add
} | set(SFX_COMMANDS.keys())
GOOGLE_CREDS_FILE = os.environ.get("GOOGLE_CREDS_FILE", "your_google_creds.json")  # Replace with your actual path to the service account JSON file
GOOGLE_DOC_ID = os.environ.get("GOOGLE_DOC_ID", "your_google_doc_id_here")  # Replace with your actual Google Doc ID
_docs_service = None
def load_boom_counts() -> dict[str, int]:
    """Load per-user boom counts from disk. Keys are lowercase usernames."""
    if not os.path.isfile(BOOM_COUNTS_FILE):
        return {}
    try:
        with open(BOOM_COUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[BOOM ERROR] Failed to load {BOOM_COUNTS_FILE}: {exc!r}")
        return {}


def save_boom_counts(counts: dict[str, int]) -> None:
    try:
        with open(BOOM_COUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(counts, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"[BOOM ERROR] Failed to save {BOOM_COUNTS_FILE}: {exc!r}")


def increment_boom_count(username: str) -> int:
    """Bump a user's boom count by 1, save it, and return the new total."""
    counts = load_boom_counts()
    key = username.lower()
    counts[key] = counts.get(key, 0) + 1
    save_boom_counts(counts)
    return counts[key]

def get_docs_service():
    """Lazily build and cache the Google Docs API client."""
    global _docs_service
    if _docs_service is None:
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDS_FILE,
            scopes=["https://www.googleapis.com/auth/documents"],
        )
        _docs_service = build("docs", "v1", credentials=creds)
    return _docs_service

def sync_quotes_to_doc() -> None:
    """Clear the Google Doc and rewrite it with the full current quote
    list. Runs synchronously — call it from a background thread so it
    doesn't block the bot's event loop."""
    try:
        service = get_docs_service()
        quotes = load_quotes()

        doc = service.documents().get(documentId=GOOGLE_DOC_ID).execute()
        end_index = doc["body"]["content"][-1]["endIndex"]

        requests = []

        # Delete existing content first (can't delete index 1 alone if
        # the doc is totally empty, so only issue this if there's more
        # than just the trailing newline)
        if end_index > 2:
            requests.append({
                "deleteContentRange": {
                    "range": {"startIndex": 1, "endIndex": end_index - 1}
                }
            })

        if quotes:
            body_text = "\n".join(
                f'#{q["id"]}: "{q["text"]}" — added by {q["added_by"]}'
                for q in quotes
            )
        else:
            body_text = "No quotes yet."

        requests.append({
            "insertText": {
                "location": {"index": 1},
                "text": body_text,
            }
        })

        service.documents().batchUpdate(
            documentId=GOOGLE_DOC_ID, body={"requests": requests}
        ).execute()

    except Exception as exc:
        print(f"[QUOTE DOC ERROR] Failed to sync doc: {exc!r}")

def remove_quote(quote_id: int) -> bool:
    """Remove a quote by ID and renumber the remaining ones so IDs stay
    contiguous (1, 2, 3, ...). Returns True if a quote was removed,
    False if no quote with that ID existed."""
    quotes = load_quotes()
    original_len = len(quotes)
    quotes = [q for q in quotes if q["id"] != quote_id]

    if len(quotes) == original_len:
        return False  # nothing was removed, ID didn't exist

    # Renumber so IDs stay sequential after a removal
    for i, q in enumerate(quotes, start=1):
        q["id"] = i

    save_quotes(quotes)
    return True

def load_quotes() -> list[dict]:
    """Load quotes from disk. Returns an empty list if the file doesn't
    exist yet or is malformed."""
    if not os.path.isfile(QUOTES_FILE):
        return []
    try:
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[QUOTE ERROR] Failed to load {QUOTES_FILE}: {exc!r}")
        return []


def save_quotes(quotes: list[dict]) -> None:
    """Write the full quote list back to disk."""
    try:
        with open(QUOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(quotes, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"[QUOTE ERROR] Failed to save {QUOTES_FILE}: {exc!r}")


def add_quote(text: str, added_by: str) -> int:
    """Append a new quote and return its 1-indexed ID."""
    quotes = load_quotes()
    quotes.append({"id": len(quotes) + 1, "text": text, "added_by": added_by})
    save_quotes(quotes)
    return len(quotes)


def get_quote_by_id(quote_id: int) -> dict | None:
    quotes = load_quotes()
    for q in quotes:
        if q["id"] == quote_id:
            return q
    return None


def get_random_quote() -> dict | None:
    quotes = load_quotes()
    if not quotes:
        return None
    import random
    return random.choice(quotes)
def load_custom_commands() -> dict[str, str]:
    """Load custom commands from disk. Keys are lowercase trigger words
    (including the leading '!'), values are the response text."""
    if not os.path.isfile(CUSTOM_COMMANDS_FILE):
        return {}
    try:
        with open(CUSTOM_COMMANDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[CMD ERROR] Failed to load {CUSTOM_COMMANDS_FILE}: {exc!r}")
        return {}


def save_custom_commands(commands_dict: dict[str, str]) -> None:
    try:
        with open(CUSTOM_COMMANDS_FILE, "w", encoding="utf-8") as f:
            json.dump(commands_dict, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"[CMD ERROR] Failed to save {CUSTOM_COMMANDS_FILE}: {exc!r}")


def add_or_edit_custom_command(trigger: str, response: str) -> None:
    commands_dict = load_custom_commands()
    commands_dict[trigger.lower()] = response
    save_custom_commands(commands_dict)


def remove_custom_command(trigger: str) -> bool:
    commands_dict = load_custom_commands()
    key = trigger.lower()
    if key not in commands_dict:
        return False
    del commands_dict[key]
    save_custom_commands(commands_dict)
    return True

def resolve_sfx_path(name: str) -> str | None:
    """Look up a sound effect by name inside SFX_DIR, trying a few common
    extensions if none is given. Returns None if nothing is found."""
    # If the caller already included an extension, just check it directly
    if os.path.splitext(name)[1]:
        path = os.path.join(SFX_DIR, name)
        return path if os.path.isfile(path) else None

    # Otherwise try common audio extensions in order
    for ext in (".mp3", ".wav", ".ogg"):
        path = os.path.join(SFX_DIR, name + ext)
        if os.path.isfile(path):
            return path

    return None
def play_sound_file(path: str) -> None:
    """Load an audio file from disk and play it to every device in
    OUTPUT_DEVICES simultaneously, reusing the same per-device stream
    approach used for TTS to avoid sounddevice's global-state issue."""
    try:
        data, samplerate = sf.read(path, dtype="float32")
    except Exception as exc:
        print(f"[SOUND ERROR] Failed to read {path}: {exc!r}")
        return

    threads = []
    for device_index in OUTPUT_DEVICES:
        t = threading.Thread(
            target=_play_to_device, args=(data, samplerate, device_index)
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
# ---- Text-to-speech setup --------------------------------------------------
tts_queue: "queue.Queue[str]" = queue.Queue()

CHEERMOTE_PATTERN = re.compile(r"\bcheer\d+\b", re.IGNORECASE)


def strip_cheermotes(text: str) -> str:
    """Remove 'Cheer<number>' tokens from a chat message, collapsing any
    resulting extra whitespace."""
    cleaned = CHEERMOTE_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()

def _play_to_device(data, samplerate, device_index):
    """Play audio data to a single specific device using its own
    dedicated stream, avoiding sounddevice's shared global playback
    state (which sd.play() uses and which breaks under concurrent
    calls from multiple threads)."""
    try:
        with sd.OutputStream(
            samplerate=samplerate,
            device=device_index,
            channels=data.shape[1] if data.ndim > 1 else 1,
        ) as stream:
            stream.write(data)
    except Exception as exc:
        print(f"[TTS ERROR] Playback failed on device {device_index}: {exc!r}")


def _speak_once(text: str) -> None:
    """Creates a brand-new pyttsx3 engine, speaks one utterance, and tears
    the engine down. Must run in a thread with COM initialized, since
    SAPI5 (used by pyttsx3 on Windows) requires CoInitialize() to be
    called on every thread that uses it — it doesn't carry over from
    the main thread automatically."""
    pythoncom.CoInitialize()
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.setProperty("volume", 1.5)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
        engine.stop()

        data, samplerate = sf.read(tmp_path, dtype="float32")

        threads = []
        for device_index in OUTPUT_DEVICES:
            t = threading.Thread(
                target=_play_to_device, args=(data, samplerate, device_index)
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        os.remove(tmp_path)

    except Exception as exc:
        print(f"[TTS ERROR] Failed to speak message: {exc!r}")
    finally:
        pythoncom.CoUninitialize()


def _tts_worker() -> None:
    """Runs in its own thread for the lifetime of the program, pulling
    text off the queue one item at a time. Each utterance is handed off
    to a fresh, short-lived thread (see _speak_once) so every pyttsx3
    engine gets a clean thread/COM state. We join() that thread before
    grabbing the next item so cheers are still spoken one at a time,
    in order, without overlapping."""
    while True:
        text = tts_queue.get()
        if text is None:  
            break

        worker = threading.Thread(target=_speak_once, args=(text,))
        worker.start()
        worker.join()

        tts_queue.task_done()


def speak(text: str) -> None:
    tts_queue.put(text)

threading.Thread(target=_tts_worker, daemon=True).start()


# ---- Bot --------------------------------------------------------------
class BitsReaderBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=TOKEN,
            client_id=CLIENT_ID,
            nick=BOT_NICK,
            prefix="!",
            initial_channels=[CHANNEL],
        )

    async def event_ready(self):
        print(f"Logged in as {self.nick}")
        print(f"Started bot in #{CHANNEL} (cheers: min {MIN_BITS} bits)")

    async def event_message(self, message):
        global mcounter
        # Ignore messages sent by the bot itself
        if message.echo:
            return

        author = message.author.name if message.author else "Someone"
        content = message.content or ""

        bits = 0
        if message.tags:
            bits = int(message.tags.get("bits", 0))
#tts handling-----------------------------------------------------------------------------------------------
        if bits >= MIN_BITS and bits > 0:
            print(f"[CHEER] {author} cheered {bits} bits: {content}")
            clean_content = strip_cheermotes(content)
            spoken_text = f"{author} cheered {bits} bits! {clean_content}"
            speak(spoken_text)

        elif content.startswith("!tts"):
            is_lead = bool(message.author and message.author.name.lower() in LEAD_MODERATORS)
            if is_lead:
                tts_text = content[len("!tts"):].strip()
                if tts_text:
                    print(f"[TTS CMD] {author} triggered !tts: {tts_text}")
                    speak(tts_text)
#sound effect command handling------------------------------------------------------------------------
        elif content.split() and content.split()[0] in SFX_COMMANDS:
            is_lead = bool(message.author and message.author.name.lower() in LEAD_MODERATORS)
            if is_lead:
                sound_name = SFX_COMMANDS[content.split()[0]]
                sfx_path = resolve_sfx_path(sound_name)
                if sfx_path:
                    print(f"[SFX CMD] {author} triggered {content.split()[0]} -> {sfx_path}")
                    threading.Thread(target=play_sound_file, args=(sfx_path,), daemon=True).start()
                else:
                    print(f"[SFX CMD] Sound file not found for '{sound_name}' in {SFX_DIR}")
            else:
                print("[SFX CMD] Blocked: failed mod/lead check")
#quote command handling------------------------------------------------------------------------
        elif content.startswith("!quote"):
            is_lead = bool(message.author and message.author.name.lower() in LEAD_MODERATORS)
            args = content[len("!quote"):].strip()

            if args.lower().startswith("add"):
                if not is_lead:
                    print(f"[QUOTE CMD] Blocked: {author} tried !quote add without lead-mod")
                else:
                    quote_text = args[len("add"):].strip()
                    if quote_text:
                        new_id = add_quote(quote_text, author)
                        threading.Thread(target=sync_quotes_to_doc, daemon=True).start()
                        await message.channel.send(f'Quote #{new_id} added: "{quote_text}"')
                    else:
                        await message.channel.send("Usage: !quote add <text>")

            elif args.lower().startswith("remove"):
                if not is_lead:
                    print(f"[QUOTE CMD] Blocked: {author} tried !quote remove without lead-mod")
                else:
                    remove_arg = args[len("remove"):].strip()
                    if remove_arg.isdigit():
                        removed = remove_quote(int(remove_arg))
                        if removed:
                            threading.Thread(target=sync_quotes_to_doc, daemon=True).start()
                            await message.channel.send(f"Quote #{remove_arg} removed.")
                        else:
                            await message.channel.send(f"No quote found with #{remove_arg}.")
                    else:
                        await message.channel.send("Usage: !quote remove <number>")

            elif args.lower() == "book":
                doc_link = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/edit"
                await message.channel.send(f"All quotes here: {doc_link}")

            elif args.isdigit():
                quote = get_quote_by_id(int(args))
                if quote:
                    await message.channel.send(f'Quote #{quote["id"]}: "{quote["text"]}" — added by {quote["added_by"]}')
                else:
                    await message.channel.send(f"No quote found with #{args}.")

            else:
                quote = get_random_quote()
                if quote:
                    await message.channel.send(f'Quote #{quote["id"]}: "{quote["text"]}"')
                else:
                    await message.channel.send("No quotes saved yet. Add one with !quote add <text>")
#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
        elif content.startswith("!boom "): #this command is broadcaster only
            is_broadcaster = bool(message.author and message.author.name.lower() == CHANNEL.lower())

            if not is_broadcaster: 
                print(f"[BOOM CMD] Blocked: {author} is not the broadcaster")
            else:
                target = content[len("!boom "):].strip().lstrip("@")
                if not target:
                    await message.channel.send("Usage: !boom <username>")
                else:
                    total_booms = increment_boom_count(target)
                    await message.channel.send(f"{target} has been BOOM'ed manually! Total: {total_booms} times")

        elif content.startswith("!boomcheck "):
            target = content[len("!boomcheck "):].strip().lstrip("@")
            if not target:
                await message.channel.send("Usage: !boomcheck <username>")
            else:
                counts = load_boom_counts()
                total = counts.get(target.lower(), 0)
                if total == 0:
                    await message.channel.send(f"{target} has never been BOOM'ed.")
                else:
                    await message.channel.send(f"{target} has been BOOM'ed {total} times")
#command management handling--------------------------------------------------------------------------------------------------------
        elif content.startswith("!commands"):
            await message.channel.send("The command list: https://your_google_doc_link_here")  # Replace with your actual Google Doc link

        elif content.startswith("!command "):
            is_lead = bool(message.author and message.author.name.lower() in LEAD_MODERATORS)
            args = content[len("!command "):].strip()

            if not is_lead:
                print(f"[CMD MGMT] Blocked: {author} tried !command without lead-mod")
            elif args.lower().startswith("add "):
                rest = args[len("add "):].strip()
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    await message.channel.send("Usage: !command add !trigger response text")
                else:
                    trigger, response = parts[0], parts[1]
                    if not trigger.startswith("!"):
                        await message.channel.send("Trigger must start with '!' (e.g. !command add !hello Hi there!)")
                    elif trigger.lower() in RESERVED_COMMANDS:
                        await message.channel.send(f"{trigger} is a built-in command and can't be overwritten.")
                    elif trigger.lower() in load_custom_commands():
                        await message.channel.send(f"{trigger} already exists. Use !command edit to change it, or !command remove first.")
                    else:
                        add_or_edit_custom_command(trigger, response)
                        await message.channel.send(f"Added command {trigger} -> {response}")

            elif args.lower().startswith("edit "):
                rest = args[len("edit "):].strip()
                parts = rest.split(" ", 1)
                if len(parts) < 2:
                    await message.channel.send("Usage: !command edit !trigger new response text")
                else:
                    trigger, response = parts[0], parts[1]
                    if trigger.lower() not in load_custom_commands():
                        await message.channel.send(f"{trigger} doesn't exist. Use !command add to create it.")
                    else:
                        add_or_edit_custom_command(trigger, response)
                        await message.channel.send(f"Updated command {trigger} -> {response}")

            elif args.lower().startswith("remove "):
                trigger = args[len("remove "):].strip()
                if remove_custom_command(trigger):
                    await message.channel.send(f"Removed command {trigger}")
                else:
                    await message.channel.send(f"{trigger} doesn't exist.")

            elif args.lower() == "list":
                commands_dict = load_custom_commands()
                if not commands_dict:
                    await message.channel.send("No custom commands yet.")
                else:
                    trigger_list = ", ".join(sorted(commands_dict.keys()))
                    await message.channel.send(f"Custom commands: {trigger_list} see !commands for the full list doc.")

            else:
                await message.channel.send("Usage: !command add|edit|remove|list ...")

        elif content.split() and content.split()[0].lower() in load_custom_commands():
            commands_dict = load_custom_commands()
            trigger = content.split()[0].lower()
            await message.channel.send(commands_dict[trigger])

        await self.handle_commands(message)

if __name__ == "__main__":
    bot = BitsReaderBot()
    bot.run()
