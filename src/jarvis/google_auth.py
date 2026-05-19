"""Shared OAuth helper for Google APIs (Gmail + Calendar).

One OAuth client + one cached token covers all the scopes we use. Adding a
new scope means one re-consent on the next call that needs it; afterward
the existing token is reused.

Setup the user does ONCE (see README → Google setup):
  1. Cloud Console → OAuth client → Desktop app → download JSON.
  2. Save as ~/.jarvis/google-credentials.json.
  3. First API call pops a browser. Token cached at ~/.jarvis/google-token.json.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Single unified scope list. Add here when introducing a new Google API.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class _MissingDeps(RuntimeError):
    pass


def _import_libs():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as e:
        raise _MissingDeps(
            "Google libraries missing. Install with `pip install -e .[gmail]`."
        ) from e
    return Request, Credentials, InstalledAppFlow, build


def get_credentials(credentials_path: Path, token_path: Path):
    """Return Google OAuth credentials with all SCOPES granted.

    Raises RuntimeError with a friendly message on any failure, so callers
    can return that string to the user instead of crashing.
    """
    if not credentials_path.exists():
        raise RuntimeError(
            f"Google credentials missing at {credentials_path}. "
            "See README → Google setup."
        )

    Request, Credentials, InstalledAppFlow, _ = _import_libs()

    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            log.warning("Google token unreadable (%s); will reauth.", e)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                log.warning("Token refresh failed (%s); falling back to flow.", e)
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def build_service(
    api: str,
    version: str,
    credentials_path: Path,
    token_path: Path,
):
    """Build a Google API client (api='gmail'/'calendar', version='v1'/'v3')."""
    _, _, _, build = _import_libs()
    creds = get_credentials(credentials_path, token_path)
    return build(api, version, credentials=creds, cache_discovery=False)
