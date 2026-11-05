import json
from pathlib import Path
from typing import Callable
from google.auth.transport.requests import Request

DEFAULT_SCOPES = (
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
)


def token_provider(
    credentials_path: str | Path,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
) -> Callable[[], str]:
    path = Path(credentials_path)
    data = json.loads(path.read_text())
    if 'type' in data and data['type'] == 'service_account':
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            str(path), scopes=list(scopes))
    else:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(path), scopes=list(scopes))

    def _token() -> str:
        if not creds.valid:
            creds.refresh(Request())
        return creds.token

    return _token
