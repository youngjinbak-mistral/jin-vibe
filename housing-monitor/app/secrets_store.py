import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from .models import Secret

KNOWN_SECRETS = {
    "molit_service_key": "data.go.kr 서비스키 (국토교통부 실거래가)",
    "google_client_id": "Google OAuth 클라이언트 ID",
    "google_client_secret": "Google OAuth 클라이언트 시크릿",
    "google_refresh_token": "Google 갱신 토큰 (OAuth 로그인 시 자동 저장)",
}

ENV_OVERRIDES = {
    "molit_service_key": "HM_MOLIT_SERVICE_KEY",
    "google_client_id": "HM_GOOGLE_CLIENT_ID",
    "google_client_secret": "HM_GOOGLE_CLIENT_SECRET",
}


class SecretStoreError(RuntimeError):
    pass


class SecretStore:
    def __init__(self, master_key: str | bytes | None):
        if not master_key:
            raise SecretStoreError(
                "HM_MASTER_KEY 환경변수가 없습니다. `python -m app.keygen`으로 생성한 키를 서버 환경변수로 설정하세요."
            )
        try:
            self._fernet = Fernet(master_key)
        except (ValueError, TypeError) as exc:
            raise SecretStoreError("HM_MASTER_KEY 형식이 올바르지 않습니다 (Fernet 키여야 함).") from exc

    def set(self, db: Session, name: str, value: str) -> None:
        if not value:
            raise SecretStoreError("빈 값은 저장할 수 없습니다.")
        token = self._fernet.encrypt(value.encode("utf-8"))
        row = db.get(Secret, name)
        if row is None:
            db.add(Secret(name=name, ciphertext=token))
        else:
            row.ciphertext = token
        db.flush()

    def get(self, db: Session, name: str) -> str | None:
        env_name = ENV_OVERRIDES.get(name)
        if env_name and os.environ.get(env_name):
            return os.environ[env_name]
        row = db.get(Secret, name)
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row.ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise SecretStoreError(f"비밀값 '{name}'을 복호화할 수 없습니다. HM_MASTER_KEY가 바뀌었는지 확인하세요.") from exc

    def delete(self, db: Session, name: str) -> None:
        row = db.get(Secret, name)
        if row is not None:
            db.delete(row)
            db.flush()

    def status(self, db: Session) -> dict[str, str]:
        out = {}
        for name in KNOWN_SECRETS:
            env_name = ENV_OVERRIDES.get(name)
            if env_name and os.environ.get(env_name):
                out[name] = "환경변수로 설정됨"
            elif db.get(Secret, name) is not None:
                out[name] = "암호화 저장됨"
            else:
                out[name] = "미설정"
        return out
