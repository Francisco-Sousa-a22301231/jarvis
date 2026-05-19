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

## Phase 3 — QA tester + fast-path

### QA tester agent

Built-in skill: `qa`. The agent reads `<project>/.jarvis-qa-spec.md`, spawns
Haiku via `claude -p`, and drives a real browser through the Playwright MCP
server. **It cannot read your source code** — built-in Read/Write/Bash/Glob
tools are explicitly disallowed; only `mcp__playwright__*` is enabled.

#### Workflow

1. Tell Claude Code (manually, or via a project-specific prompt): *"Write a
   QA spec to `.jarvis-qa-spec.md` before stopping. Include URL + numbered
   steps + expected results. No code, just behavior."*
2. Once Claude Code finishes, say *"Jarvis, run QA"* (or `python -m jarvis qa`).
3. The agent reports `PASS — <summary>` or `FAIL — <step>`. PASS deletes the
   spec; FAIL keeps it so you can iterate.

Example `.jarvis-qa-spec.md`:
```markdown
URL: http://localhost:8000/settings
Steps:
1. Click "Dark mode" toggle in the sidebar.
2. Verify the body element has class `dark-mode`.
3. Reload the page; verify class is still applied.
Failure modes:
- Toggle doesn't animate
- Persistence broken after reload
```

#### Setup (one-time)

```bash
# 1. Install Node.js (needed for the Playwright MCP server)
brew install node

# 2. Copy the MCP config to where Jarvis looks for it
cp mcp_config.example.json ~/.jarvis/mcp.json

# 3. Pre-pull the Playwright MCP server (avoids first-run lag)
npx -y @playwright/mcp@latest --help >/dev/null
```

#### Cost & latency

Single run is typically <10k Haiku tokens (~$0.01 on pay-as-you-go pricing, or
free on Max). End-to-end QA against `localhost` finishes in 20–60 seconds.

### Keyword fast-path

The router now tries a local regex fast-path before spawning Haiku. Common
phrases — "morning brief", "what's on my calendar", "any new emails", "run
QA", "hello" — skip the LLM call entirely, saving ~2s of latency per match.
Anything ambiguous still falls through to the Haiku router.

## Phase 4 — Memory, confirmation, Gmail, auto-spec

### Memory (anaphora resolution)

Jarvis keeps the last 10 (transcript, skill, result) tuples in
`~/.jarvis/memory/recent.md`. The router **only loads it** when the new
transcript looks anaphoric — contains *it / that / those / same / again*.
Most utterances pay zero memory tokens; the rest get ~80 extra tokens for a
much better resolution of "do the same for the dashboard" etc.

### Confirmation gate

Skills marked `requires_confirm=True` in `skills.py` go through a voice
confirmation step before dispatch. Currently: `trello_create`.

```
You:    "Add a card to call Pedro tomorrow"
Jarvis: "I'll add to Trello: call Pedro tomorrow. Confirm?"
You:    "yes" / "go" / "do it" / "ok"  →  executes
You:    silence / "no" / "cancel"      →  cancels
```

Add new gated skills by flipping the flag and a phrase in `confirmation.proposal_for()`.

### Gmail OAuth (alternative mail backend)

For non-Mail.app users. One-time setup:

1. https://console.cloud.google.com/ → new (or existing) project.
2. Enable the **Gmail API**.
3. APIs & Services → Credentials → Create OAuth client ID → **Desktop app**.
4. Download the JSON → save as `~/.jarvis/gmail-credentials.json`.
5. Install the extra deps: `pip install -e ".[gmail]"`.
6. In `~/.jarvis/config.toml`:
   ```toml
   [mail]
   backend = "gmail"
   gmail_credentials = "~/.jarvis/gmail-credentials.json"
   gmail_token = "~/.jarvis/gmail-token.json"
   ```
7. First call (e.g. `python -m jarvis brief`) pops a browser for consent.
   Token is cached for subsequent runs.

Scope is **read-only**. Sending mail intentionally isn't in this agent yet —
that's a destructive action and would need its own confirmation-gated skill.

### Auto-generated QA spec (closes the Phase 3 loop)

`python -m jarvis spec` reads the project's uncommitted `git diff` and asks
Claude (Sonnet by default) to write a `.jarvis-qa-spec.md`. Then `python -m
jarvis qa` runs it.

Wire it to a Claude Code Stop hook so the spec generates automatically after
every Claude Code session in a project:

```bash
mkdir -p <your-project>/.claude
cp hooks/claude-code-stop-hook.example.json <your-project>/.claude/settings.json
```

The spec generator skips on read-only sessions / tiny diffs (< 8 lines), so
it's safe to leave the hook always-on.

## Phase 5 preview

- Send-mail skill (Gmail + confirmation gate)
- A "watcher" that surfaces important new mail / Trello / calendar changes proactively
- Multi-project routing (Phase 2 placeholder finally resolved)

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
