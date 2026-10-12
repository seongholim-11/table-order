"""user 페이지(Streamlit AppTest) ↔ 실제 백엔드(FastAPI TestClient) QR 로그인 통합 테스트.

휴대폰 동작은 같은 TestClient 로 흉내 낸다 (QR 주소 열기 → 모의 카카오 로그인 콜백).
실행: 저장소 루트에서 `python -m pytest tests -q` (fastapi, streamlit 필요)
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "user")]

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.core.settings import Settings
from app.factory import create_app
from shared import api

APP = str(ROOT / "user" / "app.py")


@pytest.fixture
def server():
    s = Settings(database_url="sqlite:///:memory:", kakao_rest_api_key="", public_base_url="http://t",
                 jwt_secret="x" * 32, admin_token="admin-secret", _env_file=None)
    with TestClient(create_app(s)) as c:
        api.set_client(c)
        yield c
    api.set_client(None)


def phone_login(server, qr_url: str, nickname: str):
    """휴대폰이 QR을 스캔하고 (모의) 카카오 로그인을 마치는 과정."""
    path = urlparse(qr_url)
    r = server.get(f"{path.path}?{path.query}", follow_redirects=False)
    assert r.status_code == 302
    state = path.query.removeprefix("token=")
    assert server.get("/api/auth/kakao/callback", params={"state": state, "code": f"mock-{nickname}"}).status_code == 200


def ss(app):
    return app.session_state


def test_guest_sees_guest_order_button_and_roulette_asks_for_login(server):
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert app.button(key="start_btn").label == "🍴 비회원 주문  ›"
    assert not ss(app)["members"] and any("로그인 후 룰렛" in h.value for h in app.get("html"))
    app.button(key="roulette_btn").click().run()  # 로그인 안 한 상태로 START → 로그인 팝업
    assert ss(app)["roulette"] is None
    login = ss(app)["login"]
    assert login and login["qr_url"].startswith("http://t/api/auth/kakao/start?token=")
    assert not app.exception


def test_login_then_spin_then_second_spin_needs_another_login(server):
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.button(key="roulette_btn").click().run()
    phone_login(server, ss(app)["login"]["qr_url"], "가")
    app.run()  # 팝업이 닫힌 뒤에도 완료된 로그인이 반영된다
    assert ss(app)["member"]["nickname"] == "가" and ss(app)["login"] is None
    assert app.button(key="start_btn").label == "🍴 회원 주문  ›"
    assert len(ss(app)["members"]) == 1 and any("룰렛 기회 1회" in h.value for h in app.get("html"))

    app.button(key="roulette_btn").click().run()  # 로그인 O → 룰렛이 돈다
    assert ss(app)["roulette"] and ss(app)["members"][0]["prize"]
    assert ss(app)["login"] is None and not [d for d in app.get("dialog")]  # 돌린 직후에는 로그인 팝업이 없다
    first_result = ss(app)["roulette"]["idx"]

    app.button(key="roulette_btn").click().run()  # 이미 돌렸는데 또 돌리려 하면 → 추가 로그인 팝업
    assert ss(app)["roulette"]["idx"] == first_result and ss(app)["login"]
    phone_login(server, ss(app)["login"]["qr_url"], "나")
    app.run()
    assert [m["nickname"] for m in ss(app)["members"]] == ["가", "나"] and ss(app)["members"][1]["prize"] is None
    app.button(key="roulette_btn").click().run()
    assert ss(app)["members"][1]["prize"] and ss(app)["login"] is None and not app.exception
    # 하단에 로그인한 회원이 누적된다
    log = next(h.value for h in app.get("html") if "mlog" in h.value)
    assert "가님" in log and "나님" in log and "로그인한 회원 <span>2</span>" in log


def test_same_member_logging_in_again_adds_row_but_no_extra_spin(server):
    app = AppTest.from_file(APP, default_timeout=30).run()
    for _ in range(2):
        app.button(key="login_open").click().run()
        phone_login(server, ss(app)["login"]["qr_url"], "같은사람")
        app.run()
    rows = ss(app)["members"]
    assert len(rows) == 2 and rows[0]["eligible"] is True and rows[1]["eligible"] is False
    app.button(key="roulette_btn").click().run()
    app.button(key="roulette_btn").click().run()  # 두 번째 START → 기회 없음 → 팝업
    assert rows[0]["prize"] and rows[1]["prize"] is None and ss(app)["login"]
    log = next(h.value for h in app.get("html") if "mlog" in h.value)
    assert "룰렛은 이미 참여했어요" in log


def test_profile_form_after_login_saves(server):
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.button(key="login_open").click().run()
    phone_login(server, ss(app)["login"]["qr_url"], "홍대손님")
    app.run()
    app.text_input[0].set_value("010-1234-5678")
    app.checkbox[0].check()
    next(b for b in app.get("button") if b.proto.label == "저장").click().run()
    me = server.get("/api/members/me", headers={"Authorization": f"Bearer {ss(app)['access_token']}"}).json()
    assert me["phone"] == "010-1234-5678" and me["marketing_consent"] is True and not app.exception


def test_used_qr_is_rejected_and_expired_qr_can_be_refreshed(server):
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.button(key="login_open").click().run()
    first = ss(app)["login"]
    phone_login(server, first["qr_url"], "가")
    path = urlparse(first["qr_url"])
    assert server.get(f"{path.path}?{path.query}", follow_redirects=False).status_code == 410  # 재사용 불가
    app.run()
    app.button(key="login_open").click().run()
    old = ss(app)["login"]["token"]
    ss(app)["login"]["created"] -= 10_000  # 만료시키기
    app.run()
    app.button(key="login_open").click().run()  # 만료된 QR 은 열 때 새로 발급
    assert ss(app)["login"]["token"] != old


def test_without_server_roulette_explains_and_guest_order_still_works():
    api.set_client(__import__("httpx").Client(base_url="http://127.0.0.1:9", timeout=1))
    try:
        app = AppTest.from_file(APP, default_timeout=30)
        app.query_params["table"] = "7"
        app.run()
        assert not app.exception and ss(app)["table"] == 7
        app.button(key="roulette_btn").click().run()
        assert any("서버에 연결할 수 없어요" in h.value for h in app.get("html")) and not ss(app)["members"]
        app.button(key="start_btn").click().run()  # 비회원 주문은 서버 없이도 가능
        assert not app.exception
    finally:
        api.set_client(None)


def test_order_screen_and_category_are_restored_from_url_on_reload():
    api.set_client(__import__("httpx").Client(base_url="http://127.0.0.1:9", timeout=1))
    try:
        app = AppTest.from_file(APP, default_timeout=30)
        app.query_params["table"] = "7"
        app.run()
        assert app.session_state["page"] == "splash" and "page" not in app.query_params
        app.button(key="start_btn").click().run()
        app.button(key="cat_soup").click().run()
        assert app.query_params["page"] == "order" and app.query_params["cat"] == "soup"
        fresh = AppTest.from_file(APP, default_timeout=30)  # 새로고침
        fresh.query_params["table"], fresh.query_params["page"], fresh.query_params["cat"] = "7", "order", "soup"
        fresh.run()
        assert not fresh.exception
        assert fresh.session_state["page"] == "order" and fresh.session_state["cat"] == "soup"
    finally:
        api.set_client(None)
