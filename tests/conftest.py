import os
from pathlib import Path

TEST_DB = Path("/tmp/disseqt_gateway_pytest.db")
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")

import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app
from app.seed import initialize


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(engine)
    initialize()
    yield


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def admin_headers():
    return {"X-Demo-User-Id": "00000000-0000-0000-0000-000000000001"}


@pytest.fixture
def agent_headers():
    return {"Authorization": "Bearer ag_demo_full_access_local_only"}


def tool_call(tool="documents.search", arguments=None, context=None):
    return {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "model": "mock-secure-v1",
        "tool": tool,
        "arguments": arguments or {"query": "Customer"},
        "environment": "PRODUCTION",
        "untrusted_context": context or [],
    }
