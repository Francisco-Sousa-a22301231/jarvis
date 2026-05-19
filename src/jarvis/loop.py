"""Main daemon loop: wake -> record -> transcribe -> route -> dispatch -> speak.

Phase 5 additions:
  - Multi-project routing — pre-step extracts project mention before the
    router runs; coder shim picks the right Coder instance.
  - Send-mail skill (Gmail + confirmation gate).
"""
from __future__ import annotations

import logging

from .agents import planner
from .agents.brief import BriefAgent
from .agents.calendar import build_calendar_agent
from .agents.direct import DirectAgent
from .agents.mail import build_mail_agent  # selects applescript or gmail
from .agents.mail_send import MailSendAgent
from .agents.memory_query import MemoryQueryAgent
from .agents.qa import QAAgent
from .agents.trello import TrelloAgent
from .coder import Coder
from .config import Config
from .confirmation import is_yes, proposal_for
from .dispatcher import Dispatcher
from .ears import Ears
from .memory import Memory
from .mouth import Mouth
from .projects import resolve_project
from .prompt_registry import PromptRegistry
from .router import route
from .skills import requires_confirm
from .skills_loader import load_dir as load_custom_skills

log = logging.getLogger(__name__)

CANCEL_TOKENS = ("cancel that", "never mind", "nevermind", "forget it")


def _build_dispatcher(
    config: Config,
    memory: Memory,
    registry: PromptRegistry,
) -> tuple[Dispatcher, "_CoderShim"]:
    # Coder per configured project. The shim picks the right one per dispatch.
    coders: dict[str, Coder] = {}
    for p in config.projects:
        coders[p.name] = Coder(
            project_root=p.path,
            claude_bin=config.claude_bin,
            dangerously_skip_permissions=config.dangerously_skip_permissions,
            timeout_seconds=config.timeout_seconds,
            prompt_registry=registry,
        )
    # Validate that at least the default project is usable.
    coders[config.projects[0].name].check()
    coder_shim = _CoderShim(coders, default_name=config.projects[0].name)

    # Trello is optional — daemon still works without credentials.
    try:
        trello: TrelloAgent | None = TrelloAgent()
    except RuntimeError as e:
        log.warning("Trello disabled: %s", e)
        trello = None

    calendar = build_calendar_agent(config)
    mail = build_mail_agent(config)
    direct = DirectAgent()
    brief = BriefAgent(trello=trello, calendar=calendar, mail=mail)
    qa = QAAgent(
        project_root=config.default_project,
        mcp_config_path=config.mcp_config_path,
        claude_bin=config.claude_bin,
    )
    mail_send = MailSendAgent(
        gmail_credentials_path=config.google_credentials_path,
        gmail_token_path=config.google_token_path,
        contacts_path=config.contacts_path,
    )
    memory_query = MemoryQueryAgent(memory=memory)

    agents = {
        "code": coder_shim,
        "calendar": calendar,
        "mail": mail,
        "mail_send": mail_send,
        "direct": direct,
        "brief": brief,
        "qa": qa,
        "memory_query": memory_query,
    }
    if trello is not None:
        agents["trello_query"] = trello
        agents["trello_create"] = trello

    # Custom skills from ~/.jarvis/skills/*.py (loaded once at startup).
    # Each registers itself in skills.SKILL_CATALOG and returns an agent.
    custom = load_custom_skills(config.skills_dir)
    for skill_id, agent in custom.items():
        if skill_id in agents:
            log.warning(
                "Custom skill %r overrides a built-in. Keeping the custom one.", skill_id
            )
        agents[skill_id] = agent

    return Dispatcher(agents), coder_shim


class _CoderShim:
    """Project-aware Coder dispatcher.

    The loop calls `set_next_project()` after resolving the project from the
    transcript; the next `execute()` uses that Coder, then the slot resets.

    Also remembers the *most recent* CoderResult on `last_result` so QA can
    feed PASS/FAIL back to the prompt registry against the right template_id.
    """

    def __init__(self, coders: dict[str, Coder], default_name: str):
        self._coders = coders
        self._default = default_name
        self._next_name: str | None = None
        self.last_result = None  # type: ignore[assignment]

    def set_next_project(self, name: str | None) -> None:
        self._next_name = name

    def execute(self, task: str) -> str:
        name = self._next_name or self._default
        self._next_name = None
        coder = self._coders.get(name)
        if coder is None:
            return f"No coder configured for project {name!r}."
        result = coder.execute(task)
        self.last_result = result
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
    memory = Memory()
    registry = PromptRegistry()
    dispatcher, coder_shim = _build_dispatcher(config, memory, registry)

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

            # Extract project mention (e.g. "in MyLessons add..."). If found,
            # strip it from the transcript before routing.
            proj, cleaned = resolve_project(transcript, config.projects)
            if proj is not None:
                log.info("Project: %s", proj.name)
                coder_shim.set_next_project(proj.name)

            decision = route(cleaned, memory=memory)
            log.info("Routed: %s | %s", decision.skill, decision.task)

            # Planner: for ambiguous code tasks, ask one clarifying question first.
            if decision.skill == "code":
                question = planner.clarification(decision.task)
                if question:
                    mouth.speak(question)
                    answer_audio = ears.record_utterance(max_seconds=15.0, silence_seconds=1.2)
                    answer = ears.transcribe(answer_audio)
                    log.info("Clarification answer: %r", answer)
                    if answer.strip():
                        decision = decision.__class__(  # Routed is frozen
                            skill=decision.skill,
                            task=planner.merge_clarification(decision.task, question, answer),
                        )

            # Confirmation gate for destructive skills.
            if requires_confirm(decision.skill):
                agent = dispatcher.agents.get(decision.skill)
                if agent is not None and hasattr(agent, "propose"):
                    try:
                        proposal = agent.propose(decision.task)
                    except Exception:
                        log.exception("propose() failed; falling back to static template")
                        proposal = proposal_for(decision.skill, decision.task)
                else:
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

            # Outcome wiring: if QA just ran and there's a pending code dispatch,
            # score the template that produced it.
            if decision.skill == "qa" and coder_shim.last_result is not None:
                cr = coder_shim.last_result
                if cr.template_id is not None and cr.task:
                    upper = response.upper().lstrip()
                    if upper.startswith("PASS"):
                        registry.record_outcome(cr.template_id, cr.task, "success", response[:200])
                    elif upper.startswith("FAIL"):
                        registry.record_outcome(cr.template_id, cr.task, "failure", response[:200])
                    coder_shim.last_result = None  # one-shot — don't double-score
    finally:
        ears.close()
