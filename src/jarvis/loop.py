"""Main daemon loop: wake -> record -> transcribe -> route -> dispatch -> speak.

Phase 4 additions:
  - Rolling memory of last ~10 utterances; router uses it only when the
    transcript looks anaphoric.
  - Voice confirmation gate for skills marked `requires_confirm` in the
    catalog (currently `trello_create`).
"""
from __future__ import annotations

import logging

from .agents.brief import BriefAgent
from .agents.calendar import CalendarAgent
from .agents.direct import DirectAgent
from .agents.mail import build_mail_agent  # selects applescript or gmail
from .agents.qa import QAAgent
from .agents.trello import TrelloAgent
from .coder import Coder
from .config import Config
from .confirmation import is_yes, proposal_for
from .dispatcher import Dispatcher
from .ears import Ears
from .memory import Memory
from .mouth import Mouth
from .router import route
from .skills import requires_confirm

log = logging.getLogger(__name__)

CANCEL_TOKENS = ("cancel that", "never mind", "nevermind", "forget it")


def _build_dispatcher(config: Config) -> Dispatcher:
    # Coder is required (Phase 1's reason for existing).
    coder = Coder(
        project_root=config.default_project,
        claude_bin=config.claude_bin,
        dangerously_skip_permissions=config.dangerously_skip_permissions,
        timeout_seconds=config.timeout_seconds,
    )
    coder.check()

    # Trello is optional — daemon still works without credentials.
    try:
        trello: TrelloAgent | None = TrelloAgent()
    except RuntimeError as e:
        log.warning("Trello disabled: %s", e)
        trello = None

    calendar = CalendarAgent()
    mail = build_mail_agent(config)
    direct = DirectAgent()
    brief = BriefAgent(trello=trello, calendar=calendar, mail=mail)
    qa = QAAgent(
        project_root=config.default_project,
        mcp_config_path=config.mcp_config_path,
        claude_bin=config.claude_bin,
    )

    agents = {
        "code": _CoderShim(coder),
        "calendar": calendar,
        "mail": mail,
        "direct": direct,
        "brief": brief,
        "qa": qa,
    }
    if trello is not None:
        agents["trello_query"] = trello
        agents["trello_create"] = trello
    return Dispatcher(agents)


class _CoderShim:
    """Adapts Coder.execute(task) -> CoderResult into Agent.execute -> str."""

    def __init__(self, coder: Coder):
        self._coder = coder

    def execute(self, task: str) -> str:
        result = self._coder.execute(task)
        return result.short


def run(config: Config) -> None:
    if not config.picovoice_key:
        raise RuntimeError(
            "PICOVOICE_KEY not set — daemon needs a Picovoice access key. "
            "Get one free at https://console.picovoice.ai/ and set it in "
            "~/.jarvis/config.toml or via PICOVOICE_KEY env. "
            "(brief/route/qa subcommands work without it.)"
        )
    ears = Ears(
        picovoice_key=config.picovoice_key,
        whisper_model=config.whisper_model,
        whisper_device=config.whisper_device,
        whisper_compute_type=config.whisper_compute_type,
        vad_aggressiveness=config.vad_aggressiveness,
    )
    mouth = Mouth(
        elevenlabs_key=config.elevenlabs_key,
        voice_id=config.elevenlabs_voice_id,
        model=config.elevenlabs_model,
    )
    dispatcher = _build_dispatcher(config)
    memory = Memory()

    mouth.speak("Jarvis online.")
    log.info("Waiting for wake word ('jarvis')...")

    try:
        while True:
            ears.wait_for_wake()
            mouth.speak("Yes?")

            audio = ears.record_utterance(
                max_seconds=config.max_utterance_seconds,
                silence_seconds=config.silence_seconds,
            )
            transcript = ears.transcribe(audio)
            log.info("Transcript: %r", transcript)

            if len(transcript) < 3:
                mouth.speak("Didn't catch that.")
                continue
            if any(tok in transcript.lower() for tok in CANCEL_TOKENS):
                mouth.speak("Cancelled.")
                continue

            decision = route(transcript, memory=memory)
            log.info("Routed: %s | %s", decision.skill, decision.task)

            # Confirmation gate for destructive skills (trello_create, future mail_send, ...).
            if requires_confirm(decision.skill):
                proposal = proposal_for(decision.skill, decision.task)
                mouth.speak(f"{proposal} Confirm?")
                confirm_audio = ears.record_utterance(max_seconds=8.0, silence_seconds=1.5)
                confirm_text = ears.transcribe(confirm_audio)
                log.info("Confirmation transcript: %r", confirm_text)
                if not is_yes(confirm_text):
                    mouth.speak("Cancelled.")
                    memory.append(transcript, decision.skill, "cancelled by user")
                    continue

            # Acknowledge before potentially slow ops (Claude Code mostly).
            if decision.skill == "code":
                mouth.speak("On it.")

            response = dispatcher.execute(decision)
            mouth.speak(response)
            memory.append(transcript, decision.skill, response)
    finally:
        ears.close()
