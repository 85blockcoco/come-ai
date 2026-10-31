import socket
import threading
import time
import urllib.request

import uvicorn
import pytest

from career.service import CareerService
from come_ai_web import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def app_url(tmp_path_factory):
    base = tmp_path_factory.mktemp("e2e")
    service = CareerService(base, curated_sources=())
    app = create_app(base_dir=base, career_override=service)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/career/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("FastAPI test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def app(app_url):
    return app_url


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when == "call" and outcome.excinfo:
        page = item.funcargs.get("page")
        if page is not None:
            try:
                page.screenshot(path=f"e2e_failure_{item.name}.png", full_page=True)
            except Exception:
                pass