"""관리자 '메뉴 관리' 화면: 왼쪽 카테고리 CRUD, 카테고리를 클릭하면 그 카테고리에 메뉴 등록."""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "admin")]

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import admin_repository as ar
from admin_dummy_data import DummyBackend
from app.core.settings import Settings
from app.factory import create_app
from app.services.grades import KST
from shared import api

APP = str(ROOT / "admin" / "app.py")
ADMIN = {"Authorization": "Bearer admin-secret"}


def make_server():
    s = Settings(database_url="sqlite:///:memory:", kakao_rest_api_key="", public_base_url="http://t",
                 jwt_secret="x" * 32, admin_token="admin-secret", _env_file=None)
    return create_app(s, sms_clock=lambda: datetime(2026, 10, 12, 14, 0, tzinfo=KST))


@pytest.fixture
def server():
    with TestClient(make_server()) as c:
        api.set_client(c)
        yield c
    api.set_client(None)


def open_menu_page(monkeypatch, mode):
    monkeypatch.setenv("DATA_SOURCE", mode)
    monkeypatch.setenv("ADMIN_TOKEN", "change-me")
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.text_input[0].set_value("change-me" if mode == "dummy" else "admin-secret")
    app.button[0].click().run()
    app.sidebar.radio[0].set_value("메뉴 관리").run()
    assert not app.exception
    return app


def field(app, kind, label):
    return next(w for w in getattr(app, kind) if w.label == label)


def button(app, label):
    return next(b for b in app.button if b.label == label)


def text(app):
    return " ".join(str(x.value) for x in list(app.info) + list(app.error) + list(app.caption) + list(app.markdown))


def pick(app, category_id):
    app.button(key=f"mcat_{category_id}").click().run()
    assert not app.exception


# ---- 화면 흐름 (더미 모드) ------------------------------------------------------------------------
def test_categories_listed_on_the_left_and_nothing_selected_at_first(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    keys = [b.key for b in app.button if str(b.key).startswith("mcat_") and b.key != "mcat_panel"]
    assert keys == ["mcat_chicken", "mcat_anju", "mcat_soup", "mcat_beer", "mcat_soju", "mcat_side"]
    assert app.button(key="mcat_chicken").label == "🍗  치킨·튀김  (3)"  # 아이콘·이름·메뉴 수
    assert any("왼쪽에서 카테고리를 클릭" in i.value for i in app.info)
    assert not [b for b in app.button if b.label == "메뉴 등록"]  # 클릭하기 전에는 등록 폼이 없다


def test_clicking_a_category_opens_the_register_form_for_that_category(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    pick(app, "soup")
    assert app.session_state["menu_cat"] == "soup"
    assert app.button(key="mcat_soup").proto.type == "primary" and app.button(key="mcat_chicken").proto.type == "secondary"
    assert any("탕·전골" in h.value and "메뉴 2개" in h.value for h in app.get("html"))
    assert field(app, "text_input", "메뉴 이름 *") and [b for b in app.button if b.label == "메뉴 등록"]


def test_register_a_menu_in_the_clicked_category(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    pick(app, "soup")
    field(app, "text_input", "메뉴 이름 *").set_value("매운 닭볶음탕")
    field(app, "number_input", "가격 *").set_value(26000)
    field(app, "text_input", "설명").set_value("얼큰한 국물")
    field(app, "selectbox", "매운 정도").set_value("아주 매움")
    button(app, "메뉴 등록").click().run()
    assert not app.exception
    repo = app.session_state["repo"]
    row = repo.menus().set_index("메뉴명").loc["매운 닭볶음탕"]
    assert row["카테고리"] == "탕·전골" and row["가격"] == 26000 and row["매운 정도"] == "아주 매움"
    assert app.button(key="mcat_soup").label.endswith("(3)")  # 메뉴 수가 늘었다


def test_register_requires_a_name(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    pick(app, "soup")
    button(app, "메뉴 등록").click().run()
    assert any("메뉴 이름을 입력" in e.value for e in app.error)
    assert app.session_state["repo"].category_list()[2]["menu_count"] == 2


def test_add_rename_and_delete_a_category(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    field(app, "text_input", "이름").set_value("세트 메뉴")  # 왼쪽 '카테고리 추가' 양식
    field(app, "selectbox", "색상").set_value("초록")
    button(app, "추가").click().run()
    assert not app.exception
    repo = app.session_state["repo"]
    created = next(c for c in repo.category_list() if c["name"] == "세트 메뉴")
    assert created["colors"] == ar.COLOR_PRESETS["초록"] and created["menu_count"] == 0
    assert app.session_state["menu_cat"] == created["id"]  # 만들면 바로 선택되어 메뉴를 등록할 수 있다
    assert [b for b in app.button if b.label == "메뉴 등록"]

    edit_name = [w for w in app.text_input if w.label == "이름"][1]  # 두 번째 '이름' = 수정 양식
    edit_name.set_value("세트·콤보")
    button(app, "수정 저장").click().run()
    assert any(c["name"] == "세트·콤보" for c in app.session_state["repo"].category_list())

    app.checkbox(key=f"cat_del_ok_{created['id']}").check().run()
    app.button(key="cat_delete").click().run()
    assert not app.exception
    assert all(c["id"] != created["id"] for c in app.session_state["repo"].category_list())
    assert app.session_state["menu_cat"] is None and any("왼쪽에서 카테고리를 클릭" in i.value for i in app.info)


def test_category_with_menus_cannot_be_deleted_and_names_must_be_unique(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    pick(app, "chicken")
    assert any("삭제할 수 없어요" in c.value for c in app.caption)
    assert not [b for b in app.button if b.key == "cat_delete"]
    field(app, "text_input", "이름").set_value("안주")  # 이미 있는 이름
    button(app, "추가").click().run()
    assert any("이미 있어요" in e.value for e in app.error)
    field(app, "text_input", "이름").set_value("   ")
    button(app, "추가").click().run()
    assert any("이름을 입력" in e.value for e in app.error)


# ---- 서버 모드: 같은 화면이 서버 데이터를 바꾼다 --------------------------------------------------------------
def test_api_mode_category_and_menu_changes_reach_the_server_and_users(server, monkeypatch):
    app = open_menu_page(monkeypatch, "api")
    field(app, "text_input", "이름").set_value("세트 메뉴")
    button(app, "추가").click().run()
    cats = server.get("/api/content/categories").json()
    created = next(c for c in cats if c["name"] == "세트 메뉴")
    assert [c["id"] for c in cats[:2]] == ["ai", "best"]  # 손님 화면용 가상 카테고리는 그대로
    assert created["icon"] == "🍽️" and len(created["colors"]) == 2

    field(app, "text_input", "메뉴 이름 *").set_value("가족 세트")
    field(app, "number_input", "가격 *").set_value(55000)
    button(app, "메뉴 등록").click().run()
    menu = next(m for m in server.get("/api/menus").json() if m["name"] == "가족 세트")
    assert menu["cat"] == created["id"] and menu["price"] == 55000
    assert created["id"] in [c["id"] for c in server.get("/admin/api/menus", headers=ADMIN).json()["categories"]]

    # 메뉴가 남은 카테고리는 지울 수 없고, 비운 뒤에는 지울 수 있다
    repo = app.session_state["repo"]
    with pytest.raises(ar.CategoryError):
        repo.delete_category(created["id"])
    server.delete(f"/admin/api/menus/{menu['id']}", headers=ADMIN)
    repo.delete_category(created["id"])
    after = server.get("/api/content/categories").json()
    assert created["id"] not in [c["id"] for c in after] and [c["id"] for c in after[:2]] == ["ai", "best"]


def test_repository_validations_on_both_backends(server):
    for repo in (ar.AdminRepository(DummyBackend()), ar.AdminRepository(ar.ApiBackend("admin-secret"))):
        before = len(repo.category_list())
        new_id = repo.add_category("테스트", "🧪", "파랑")
        with pytest.raises(ar.CategoryError):
            repo.add_category("테스트")  # 중복
        with pytest.raises(ar.CategoryError):
            repo.update_category(new_id, "안주", "🧪")  # 다른 카테고리와 이름 충돌
        repo.update_category(new_id, "테스트2", "")  # 빈 아이콘은 기본 아이콘으로
        updated = next(c for c in repo.category_list() if c["id"] == new_id)
        assert updated["name"] == "테스트2" and updated["icon"] == "🍽️" and updated["colors"] == ar.COLOR_PRESETS["파랑"]
        with pytest.raises(ar.CategoryError):
            repo.update_category("nope", "x", "")
        menu_id = repo.add_menu(new_id, "시험 메뉴", 5000)
        assert next(c for c in repo.category_list() if c["id"] == new_id)["menu_count"] == 1
        with pytest.raises(ar.CategoryError):
            repo.add_menu(new_id, "  ", 100)
        repo.backend.delete_menu(menu_id)
        repo.delete_category(new_id)
        assert len(repo.category_list()) == before


# ---- 저장 전 되돌리기 버튼 ------------------------------------------------------------------------------
def test_menu_editor_undo_button_sits_next_to_save_and_is_disabled_without_changes(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    pick(app, "chicken")
    assert app.button(key="menu_save").label == "변경 저장"
    assert app.button(key="menu_undo").label == "↩ 되돌리기" and app.button(key="menu_undo").disabled


def test_weights_page_shows_photo_cards_with_plus_minus_and_undo(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    app.sidebar.radio[0].set_value("추천 가중치").run()
    assert not app.exception
    assert len([b for b in app.button if str(b.key).startswith("winc_")]) == len(app.session_state["repo"].menus())  # 메뉴마다 + / − 버튼
    assert any('class="wthumb"' in h.value for h in app.get("html"))  # 주문 화면처럼 사진(썸네일) 카드
    assert app.button(key="weights_undo").disabled
    app.button(key="winc_c1").click().run()
    app.button(key="winc_c1").click().run()
    app.button(key="wdec_c2").click().run()
    assert app.session_state["w_c1"] == 60 and app.session_state["w_c2"] == 45
    assert not app.button(key="weights_undo").disabled  # 변경하면 켜진다
    app.button(key="weights_undo").click().run()
    assert not app.exception
    assert app.session_state["w_c1"] == 50 and app.session_state["w_c2"] == 50 and app.button(key="weights_undo").disabled


def test_weights_save_persists_changes(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    app.sidebar.radio[0].set_value("추천 가중치").run()
    app.button(key="winc_c1").click().run()
    next(b for b in app.button if b.label == "가중치 저장").click().run()
    assert not app.exception
    assert int(app.session_state["repo"].menus().set_index("id").at["c1", "추천 가중치"]) == 55
    assert app.button(key="weights_undo").disabled


def test_grade_rule_reset_returns_to_defaults(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    app.sidebar.radio[0].set_value("고객 등급").run()
    assert app.button(key="rule_reset").disabled
    app.number_input(key="rule_dormant").set_value(120).run()
    assert not app.button(key="rule_reset").disabled
    app.button(key="rule_reset").click().run()
    assert not app.exception
    assert app.number_input(key="rule_dormant").value == ar.DEFAULT_RULE["dormant"] and app.button(key="rule_reset").disabled


# ---- 새로고침 후 복원 (URL 쿼리) --------------------------------------------------------------------
def test_page_and_category_are_kept_in_url_and_restored_on_reload(monkeypatch):
    app = open_menu_page(monkeypatch, "dummy")
    pick(app, "soup")
    assert app.query_params["page"] == "메뉴 관리" and app.query_params["cat"] == "soup"
    monkeypatch.setenv("ADMIN_TOKEN", "change-me")
    fresh = AppTest.from_file(APP, default_timeout=30)  # 새로고침 = 새 세션 + 같은 URL
    fresh.query_params["page"], fresh.query_params["cat"] = "메뉴 관리", "soup"
    fresh.run()
    fresh.text_input[0].set_value("change-me")
    fresh.button[0].click().run()
    assert not fresh.exception
    assert fresh.sidebar.radio[0].value == "메뉴 관리" and fresh.session_state["menu_cat"] == "soup"


def test_skip_token_enters_without_login(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "dummy")
    monkeypatch.setenv("ADMIN_TOKEN", "change-me")
    monkeypatch.setenv("ADMIN_SKIP_TOKEN", "1")
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    assert len(app.text_input) == 0  # 토큰 입력 화면이 없다
    assert app.session_state["owner"] is True


def test_skip_token_off_shows_login(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "dummy")
    monkeypatch.setenv("ADMIN_SKIP_TOKEN", "0")
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert len(app.text_input) == 1
    assert app.session_state["owner"] is False
