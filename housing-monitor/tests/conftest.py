import re

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_google import FakeGoogle


@pytest.fixture
def google():
    g = FakeGoogle()
    g.add_tab("후보단지", rows=[["단지", "점수", "메모", "그룹"], ["래미안 파크스위트", "8", "학교 가까움", "A"], ["", "", "", ""], ["다른단지", "6", "", "B"]])
    g.add_tab("요약", rows=[["합계"]])
    return g


@pytest.fixture
def master_key():
    return Fernet.generate_key().decode()


@pytest.fixture
def app(tmp_path, google, master_key):
    return create_app(
        database_url=f"sqlite:///{tmp_path}/t.db",
        master_key=master_key,
        http_client=google.client(),
        session_secret="test-session",
        app_password="",
        public_base_url="http://testserver",
    )


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def csrf_of(client: TestClient, path: str = "/settings") -> str:
    html = client.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)
