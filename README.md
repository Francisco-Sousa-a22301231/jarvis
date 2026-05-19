# Jarvis

Voice-driven orchestrator that uses Claude Code. Wake-word activated, runs as a background daemon on macOS.

**Phase 1 (this)**: voice → Claude Code → voice. Single project, no router yet.

## Architecture (Phase 1)

```
Hey Jarvis (Porcupine, ~5MB, always on)
     ↓
record until silence (webrtcvad endpointing)
     ↓
faster-whisper base.en  (~500ms on 2019 Intel MBP, all local)
     ↓
claude -p "<task>"  (Claude Code in the configured project dir)
     ↓
ElevenLabs streaming TTS  (or macOS `say` fallback)
     ↓
back to waiting for wake
```

## Setup (macOS)

### 1. Install Python 3.11+ and Claude Code

```bash
brew install python@3.11
# Claude Code: https://docs.claude.com/en/docs/claude-code/quickstart
which claude  # must print a path
```

### 2. Install Jarvis

```bash
cd ~/StudioProjects/jarvis
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`faster-whisper` will download the `base.en` model (~150MB) on first run.

### 3. Get free API keys

- **Picovoice** (wake word, free tier): https://console.picovoice.ai/
- **ElevenLabs** (TTS, optional — falls back to `say`): https://elevenlabs.io/app/settings/api-keys

### 4. Configure

```bash
mkdir -p ~/.jarvis
cp config.example.toml ~/.jarvis/config.toml
$EDITOR ~/.jarvis/config.toml
```

Fill in `picovoice.access_key` and (optionally) `elevenlabs.api_key`. Point `coder.default_project` at the repo you want voice commands to operate on.

### 5. Grant microphone permission

Run once interactively so macOS shows the permission dialog:

```bash
python -m jarvis
```

Click **Allow** when prompted. The grant applies to the python binary at the path you used — if you change venvs, you'll get re-prompted.

Say **"Jarvis"** (it should respond *"Yes?"*), then say a task like *"list the files in the lib directory"*. It'll spawn Claude Code in the configured project, wait for it to finish, and speak a one-line summary.

## Run as a daemon

```bash
# Edit launchd/com.francisco.jarvis.plist with your absolute paths
cp launchd/com.francisco.jarvis.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.francisco.jarvis.plist
```

Status / logs:
```bash
launchctl list | grep jarvis
tail -f ~/.jarvis/jarvis.log
```

## Daemon mode and Claude Code permissions

A background daemon can't answer permission prompts. Two options:

1. **Pre-allow tools** by passing `--allowedTools` in `coder.py` (safer; you opt in to specific tools).
2. **Skip all prompts** with `dangerously_skip_permissions = true` in config (faster to set up; trust your prompts).

For Phase 1, run interactively first and confirm the flow feels right before enabling daemon mode.

## Cancelling

Mid-utterance: say "cancel" or "never mind" in your sentence — Jarvis won't dispatch to Claude Code. Mid-Claude-Code: not yet — wait for it to finish or `kill -TERM` the daemon.

## Phase 2 — Router + agents

Now shipped. Jarvis runs every utterance through a Haiku router that picks one
of:

| Skill | Agent | What it does |
|---|---|---|
| `code` | Coder (Claude Code subprocess) | Write/edit/debug code in the configured project |
| `trello_query` / `trello_create` | TrelloAgent | Read or create cards on your board |
| `calendar` | CalendarAgent | Read today's macOS Calendar events |
| `mail` | MailAgent | Read unread mail from macOS Mail.app |
| `brief` | BriefAgent | Combined daily summary (Trello + Calendar + Mail) |
| `direct` | DirectAgent | Smalltalk, greetings, factual one-shot Q&A |

### Setup

1. Make sure `claude` (Claude Code) is installed and you're logged in via
   `claude login`. All LLM calls — router, summarizers, brief composer —
   go through `claude -p`, which means **they bill against your Claude Max
   subscription, not pay-as-you-go API.** No `ANTHROPIC_API_KEY` needed.
2. Optional — Trello: get key+token at https://trello.com/app-key. Set
   `TRELLO_KEY`, `TRELLO_TOKEN`, `TRELLO_BOARD_ID`.
3. Calendar / Mail: grant Automation permission when macOS prompts on first use
   (System Settings → Privacy & Security → Automation).

### Try it without voice

```bash
# How would the router classify this utterance?
python -m jarvis route "what's on my plate today"

# Run today's brief once, print to stdout (useful for launchd)
python -m jarvis brief
```

### Daily morning brief via launchd

```bash
cp launchd/com.francisco.jarvis-brief.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.francisco.jarvis-brief.plist
```

Default schedule: 08:00 every day. Output goes to `~/.jarvis/brief.log`.
Edit the plist's `StartCalendarInterval` to change the time.

### Costs

All LLM usage (router, summarizers, brief, coder) goes through `claude -p` on
your **Claude Max subscription**. No per-token API billing. Only out-of-pocket
costs are Picovoice (free tier) and optionally ElevenLabs (~$5/mo).

### Latency note

Each `claude -p` spawn adds ~1–2s of overhead vs a raw API call. For commands
that hit router + agent + summarizer, perceived latency is ~3–5s. A keyword
fast-path that skips the router for unambiguous phrases ("morning brief",
"trello", "calendar") is on the Phase 3 list.

## Phase 3 preview

- QA tester agent (Haiku + Playwright MCP against staging/localhost — no code in context)
- Memory across utterances (markdown files, loaded on demand)
- Gmail OAuth fallback for users not on Apple Mail
- Confirmation gate for any "send" / "push" / destructive action

## Costs (rough, personal-use)

- Picovoice: free
- Whisper / VAD / wake: free (local)
- ElevenLabs: ~$5/mo on the Starter plan if used heavily
- Claude Code: dominates — same cost you'd pay typing prompts manually

## Troubleshooting

| Symptom | Fix |
|---|---|
| `webrtcvad` install fails | `brew install python-tk` or use Python 3.11 (not 3.12+, which sometimes has wheels missing) |
| `pvporcupine` "AccessKey is invalid" | Verify the key at console.picovoice.ai matches `~/.jarvis/config.toml` |
| Whisper is slow / fans loud | Try `tiny.en` instead of `base.en` |
| No mic prompt appears | macOS may need `tccutil reset Microphone` — then run again |
| Daemon doesn't start | Check `~/.jarvis/jarvis.err.log`; common cause is venv path wrong in plist |
