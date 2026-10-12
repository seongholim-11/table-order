"""티오더 스타일 테이블 오더 - 역전할머니맥주 (Streamlit 데모)

실행: streamlit run app.py
"""
import random
import time
from datetime import datetime
from pathlib import Path
from html import escape
from datetime import timedelta, timezone

import streamlit as st
import server
import user_repository as repository
from ai_quiz_data import answer_label, current_weather, time_slot

from recommendations import combo_cart_line, recommend_combos
from menu_images import menu_image_html

KST = timezone(timedelta(hours=9))

# 화면에 쓰는 모든 데이터는 repository 를 거친다 (DATA_SOURCE=dummy|api|auto, user_repository.py 참고).
try:
    REPO, CONTENT = repository.load_content()
except repository.ContentUnavailable as e:
    st.set_page_config(page_title="테이블오더", page_icon="🍺")
    st.error(f"{e} 직원에게 문의해 주세요.")
    st.stop()

st.session_state.data_source = CONTENT.source  # "dummy" | "api" (점검·테스트용 표시)
STORE, CATEGORIES, CATEGORY_BY_ID = CONTENT.store, CONTENT.categories, CONTENT.category_by_id
MENU, MENU_BY_ID = CONTENT.menu, CONTENT.menu_by_id
ROULETTE_PRIZES, STAFF_CALLS = CONTENT.roulette_prizes, CONTENT.staff_calls
QUESTIONS, WEATHER, RULES = CONTENT.quiz_questions, CONTENT.weather, CONTENT.rules
DISCOUNT_PERCENT = RULES["discount_percent"]

st.set_page_config(page_title=f"{STORE['name']} 테이블오더", page_icon="🍺",
                   layout="wide", initial_sidebar_state="collapsed")


# ============================== 상태 ==============================
def init_state():
    ss = st.session_state
    # 새로고침해도 보던 화면으로 돌아오도록 URL(?page=order&cat=...)에서 복원한다. sync_url() 이 반대 방향을 맡는다.
    qp = st.query_params
    ss.setdefault("page", "order" if qp.get("page") == "order" else "splash")
    ss.setdefault("cat", qp.get("cat") if qp.get("cat") in CATEGORY_BY_ID else "best")
    ss.setdefault("cart", {})        # key -> {id, name, opt, unit, qty}
    ss.setdefault("orders", [])      # 주문 내역
    ss.setdefault("calls", [])
    ss.setdefault("roulette", None)  # {"idx", "angle", "animate"} - 세션당 1회
    ss.setdefault("roulette_percent", 0)  # 다음 주문에 적용할 룰렛 할인율
    ss.setdefault("member", None)    # QR 로그인한 회원 {id, nickname}
    ss.setdefault("access_token", None)
    ss.setdefault("quiz", {"step": 0, "answers": {}})  # AI 질문 진행 상태
    ss.setdefault("members", [])      # 이 태블릿에서 로그인한 회원 기록 (누적): {id, nickname, at, eligible, prize}
    ss.setdefault("granted_ids", [])  # 룰렛 기회를 이미 받은 회원 id (회원당 1회)
    ss.setdefault("login", None)     # 발급된 QR 로그인 세션 {token, secret, qr_url, expires_in, created}
    ss.table = table_from_url()


def table_from_url():
    """태블릿마다 다른 QR/주소로 열도록 ?table=번호 를 받는다. 없거나 잘못되면 12번."""
    try:
        n = int(st.query_params.get("table", 12))
    except (TypeError, ValueError):
        n = 12
    return min(max(n, 1), STORE["tables"])


def cart_add(item, opt_label, unit, qty):
    cart = st.session_state.cart
    key = f"{item['id']}|{opt_label}"
    if key in cart:
        cart[key]["qty"] += qty
    else:
        cart[key] = {"id": item["id"], "name": item["name"], "opt": opt_label, "unit": unit, "qty": qty}


def cart_change(key, delta):
    line = st.session_state.cart.get(key)
    if not line:
        return
    line["qty"] += delta
    if line["qty"] <= 0:
        del st.session_state.cart[key]


def cart_remove(key):
    st.session_state.cart.pop(key, None)


def cart_subtotal():
    return sum(l["unit"] * l["qty"] for l in st.session_state.cart.values())


def roulette_discount():
    return cart_subtotal() * st.session_state.roulette_percent // 100 // 10 * 10


def cart_total():
    return cart_subtotal() - roulette_discount()


def cart_count(item_id=None):
    if item_id is None:
        return sum(l["qty"] for l in st.session_state.cart.values())
    return sum(l["qty"] * (sum(c["qty"] for c in l["components"] if c["id"] == item_id)
                           if "components" in l else int(l["id"] == item_id))
               for l in st.session_state.cart.values())


def cart_discount():
    return sum((line.get("original_unit", line["unit"]) - line["unit"]) * line["qty"]
               for line in st.session_state.cart.values())


def add_combo(combo):
    if any(MENU_BY_ID[c["id"]]["soldout"] for c in combo["components"]):
        st.toast("품절된 메뉴가 있어 다른 조합을 선택해 주세요.", icon="🙏")
        return
    key, line = combo_cart_line(combo)
    if key in st.session_state.cart:
        st.session_state.cart[key]["qty"] += 1
    else:
        st.session_state.cart[key] = line


def won(n):
    return f"{n:,}원"


def go(page):
    st.session_state.page = page


# ============================== 다이얼로그 ==============================
def spicy_level(item):
    """매운 정도(고추 개수). 매운맛 태그가 없으면 0."""
    if "매운맛" not in item["tags"]:
        return 0
    name = item["name"]
    if "아주 매운맛" in name:
        return 3
    if "보통맛" in name or "얼큰" in item["desc"]:
        return 2
    return 1


def thumb_html(item, qty_in_cart=0, big=False):
    c1, c2 = CATEGORY_BY_ID[item["cat"]]["colors"]
    size = " big" if big else ""
    badges = ""
    for t in item["tags"]:
        badges += (f'<span class="badge spicy">{"🌶" * spicy_level(item)} 매운맛</span>'
                   if t == "매운맛" else f'<span class="badge {t}">{t}</span>')
    extra = f'<div class="incart">{qty_in_cart}개 담김</div>' if qty_in_cart else ""
    sold = '<div class="soldout">품절</div>' if item["soldout"] else ""
    return (f'<div class="thumb{size}" style="background:linear-gradient(135deg,{c1},{c2})">'
            f'{menu_image_html(item)}<div class="badges">{badges}</div>{extra}{sold}</div>')


@st.dialog("주문 확인", width="medium")
def confirm_dialog():
    cart = st.session_state.cart
    for l in cart.values():
        opt = f" ({l['opt']})" if l["opt"] else ""
        st.html(f'<div class="order-item"><span>{l["name"]}{opt} × {l["qty"]}</span>'
                    f'<span>{won(l["unit"] * l["qty"])}</span></div>')
    st.divider()
    if cart_discount():
        st.caption(f"AI 조합 할인 −{won(cart_discount())} 적용")
    if roulette_discount():
        st.caption(f"룰렛 {st.session_state.roulette_percent}% 할인 −{won(roulette_discount())} 적용")
    st.html(f'<div class="total-row"><span>총 주문금액</span><b>{won(cart_total())}</b></div>')
    st.caption("주문 후에는 취소가 어려우니 직원에게 문의해 주세요.")
    with st.container(key="dialog_actions"):
        c1, c2 = st.columns(2, wrap=False)
    if c1.button("돌아가기", width="stretch"):
        st.rerun()
    if c2.button("주문하기", type="primary", width="stretch"):
        no = len(st.session_state.orders) + 1
        server_no = REPO.create_order(st.session_state.table, [dict(l) for l in cart.values()], cart_total(),
                                      st.session_state.access_token)
        no = server_no or no  # 서버가 주문번호를 주면 그것을 쓴다
        st.session_state.orders.append({"no": no, "ts": time.time(), "time": datetime.now(KST).strftime("%H:%M"),
                                        "lines": list(cart.values()), "total": cart_total(),
                                        "member": (st.session_state.member or {}).get("nickname")})
        st.session_state.cart = {}
        st.session_state.roulette_percent = 0
        st.toast(f"주문이 접수되었습니다 (주문번호 #{no})", icon="✅")
        st.rerun()


@st.dialog("주문내역", width="large")
def orders_dialog():
    orders = st.session_state.orders
    if not orders:
        st.html('<div class="cart-empty">아직 주문 내역이 없어요</div>')
        return
    for o in reversed(orders):
        elapsed = time.time() - o["ts"]
        s, label = (0, "접수완료") if elapsed < 15 else (1, "조리중") if elapsed < 45 else (2, "서빙완료")
        rows = "".join(
            f'<div class="order-item"><span>{l["name"]}{" (" + l["opt"] + ")" if l["opt"] else ""} × {l["qty"]}</span>'
            f'<span>{won(l["unit"] * l["qty"])}</span></div>' for l in o["lines"])
        st.html(f'<div class="order-box"><div class="order-head"><span>주문 #{o["no"]} · {o["time"]}</span>'
                    f'<span class="status s{s}">{label}</span></div>{rows}'
                    f'<div class="order-item" style="margin-top:6px;font-weight:800;color:#ffb703"><span>소계</span><span>{won(o["total"])}</span></div></div>')
    st.html(f'<div class="total-row"><span>누적 주문금액</span><b>{won(sum(o["total"] for o in orders))}</b></div>')
    st.caption("※ 데모: 시간이 지나면 주문 상태가 자동으로 바뀝니다. 새로 열면 갱신돼요.")


@st.dialog("직원 호출", width="medium")
def staff_dialog():
    picks = st.pills("필요한 항목을 선택해 주세요", STAFF_CALLS, selection_mode="multi")
    if st.button("호출하기", type="primary", width="stretch", disabled=not picks):
        REPO.create_call(st.session_state.table, list(picks))
        st.session_state.calls.append((datetime.now(KST).strftime("%H:%M"), picks))
        st.toast("직원이 곧 도착합니다 🙋", icon="🔔")
        st.rerun()


@st.dialog("장바구니", width="medium", on_dismiss="rerun")
def cart_dialog():
    render_cart(dialog=True)


# ============================== 룰렛 ==============================
def spins_left():
    """남은 룰렛 기회 = 로그인했지만 아직 돌리지 않은 회원 수 (회원당 1회)."""
    return sum(1 for m in st.session_state.members if m["eligible"] and m["prize"] is None)


def spin_roulette():
    ss = st.session_state
    row = next((m for m in ss.members if m["eligible"] and m["prize"] is None), None)
    if row is None:
        return
    idx = random.randrange(len(ROULETTE_PRIZES))
    seg = 360 / len(ROULETTE_PRIZES)
    # 포인터(12시 방향) 아래에 당첨 칸의 중앙 부근이 오도록 회전
    angle = 360 * 5 - (idx * seg + random.uniform(-seg * 0.3, seg * 0.3))
    ss.roulette = {"idx": idx, "angle": round(angle, 1), "animate": True}
    prize = ROULETTE_PRIZES[idx]
    row["prize"] = prize["short"]
    ss.just_spun = True
    if prize["kind"] == "discount":
        ss.roulette_percent = max(ss.roulette_percent, prize["percent"])
    elif prize["item_id"] in MENU_BY_ID:
        cart_add(MENU_BY_ID[prize["item_id"]], "룰렛 서비스", 0, 1)


CONFETTI = [(18, 18, 38, 12, "#f1566f", -35), (3, 40, 14, 14, "#5b8def", 20), (84, 6, 34, 11, "#37b36b", 30),
            (90, 40, 16, 16, "#9b6bd6", 10), (5, 70, 30, 10, "#2f8de0", 35), (96, 66, 24, 9, "#ffc933", 20)]


@st.cache_resource(show_spinner=False)
def qr_data_uri(url: str) -> str:
    """로그인 팝업에서 가운데 정렬로 보여줄 큰 QR (PNG data URI)."""
    import base64
    import io
    import qrcode
    buf = io.BytesIO()
    qrcode.make(url, box_size=8, border=2).convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def render_roulette():
    ss = st.session_state
    prizes, spun = ROULETTE_PRIZES, ss.roulette
    n = len(prizes)
    seg = 360 / n
    gap = 1.2
    stops = ",".join(f'{p["color"]} {i * seg}deg {(i + 1) * seg - gap}deg,#fff {(i + 1) * seg - gap}deg {(i + 1) * seg}deg'
                     for i, p in enumerate(prizes))
    labels = "".join(
        f'<div class="rw-label" style="transform:rotate({i * seg}deg)"><span style="transform:rotate({-i * seg}deg)">'
        f'{p["label"]}<em>{p["emoji"]}</em></span></div>' for i, p in enumerate(prizes))
    dots = "".join(f'<div class="rw-dot" style="transform:rotate({k * 360 / 16}deg)"><i></i></div>' for k in range(16))
    conf = "".join(f'<div class="rw-conf" style="left:{x}%;top:{y}%;width:{w}px;height:{h}px;background:{col};transform:rotate({r}deg)"></div>'
                   for x, y, w, h, col, r in CONFETTI)
    cls = " spin" if spun and spun["animate"] else ""
    to = f'--to:{spun["angle"]}deg;' if spun else ""
    st.html('<div class="rw-title"><div class="fork">🍴</div>'
            '<div class="q">오늘, 어떤 메뉴가 좋을까요?</div>'
            '<h2><i class="l1"></i><i class="l2"></i>행운의 <span>룰렛</span>을 돌려보세요!<i class="r1"></i><i class="r2"></i></h2>'
            '<div class="s">맛있는 식사와 함께 작은 행운도 받아가세요!</div></div>')
    with st.container(key="rw_box"):
        st.html('<div class="rw-stage"><div class="rw-stand"></div><div class="rw-ring"></div>'
                f'{dots}<div class="rw-pin"></div>'
                f'<div class="rw-wheel{cls}" style="{to}background:conic-gradient(from {-seg / 2}deg,{stops})">{labels}</div>'
                f'{conf}<div class="rw-star" style="left:-8%;top:10%">⭐</div><div class="rw-star" style="right:-9%;top:28%">⭐</div>'
                '<div class="rw-bubble l">오늘의<br>작은 행운!<br>어떤 선물이<br>기다리고 있을까요?</div>'
                '<div class="rw-bubble r">맛있는 식사와<br>특별한 혜택을<br>함께! <span class="heart">♥</span></div></div>')
        left = spins_left()
        with st.container(key="rw_start"):
            clicked = st.button("START", type="primary", key="roulette_btn", on_click=spin_roulette if left else None)
    hint = (f"🎟️ 룰렛 기회 {left}회 남았어요 — START를 눌러 보세요!" if left
            else "한 번 더 돌리려면 다른 회원이 로그인해 주세요." if st.session_state.members
            else "START를 누르면 로그인 후 룰렛을 돌릴 수 있어요.")
    st.html(f'<div class="rw-hint">{hint}</div>')
    just_spun = st.session_state.pop("just_spun", False)  # 이번 클릭이 룰렛을 돌린 것이면 팝업을 띄우지 않는다
    if clicked and not left and not just_spun:  # 기회가 없으면 (처음이든 이미 돌렸든) 로그인 팝업
        login_dialog("again" if st.session_state.members else "spin")
    if spun:
        prize = prizes[spun["idx"]]
        note = "다음 주문에 자동 적용돼요" if prize["kind"] == "discount" else "장바구니에 담아 두었어요"
        reveal = " reveal" if spun["animate"] else ""
        st.html(f'<div class="rw-result{reveal}"><div class="t">축하합니다! 오늘의 행운은</div>'
                f'<div class="p">{prize["emoji"]} {prize["short"]}</div><div class="n">{note}</div></div>')
        spun["animate"] = False


# ============================== 화면 ==============================
def new_login():
    """서버에서 일회용 QR 로그인 세션을 발급받는다. 서버가 없으면 None."""
    qr = server.create_qr(st.session_state.table)
    st.session_state.login = {**qr, "created": time.time()} if qr else None


def ensure_login():
    login = st.session_state.login
    if not login or time.time() - login["created"] > login["expires_in"]:
        new_login()


def finish_login(event):
    """로그인 완료: 이 태블릿의 회원 기록에 누적하고, 처음 로그인한 회원에게만 룰렛 기회를 준다."""
    ss = st.session_state
    m = event["member"]
    ss.member, ss.access_token, ss.login = m, event["access_token"], None
    first = m["id"] not in ss.granted_ids
    if first:
        ss.granted_ids.append(m["id"])
    ss.members.append({"id": m["id"], "nickname": m["nickname"], "at": datetime.now(KST).strftime("%H:%M"),
                       "eligible": first, "prize": None})
    ss.profile_saved = False


def poll_login_once():
    """진행 중인 QR 로그인이 있으면 서버에 한 번 물어보고, 완료됐으면 반영한다."""
    ss = st.session_state
    if not ss.login:
        return None
    event = server.poll_login(ss.login["secret"])
    if event and event.get("event") == "logged_in":
        finish_login(event)
    return event


LOGIN_STEPS = ["QR 스캔", "카카오 로그인", "완료"]


def login_steps_html(active: int) -> str:
    """진행 단계 표시. active: 0 스캔 대기, 1 카카오 로그인 대기, -1 만료."""
    chips = ""
    for i, name in enumerate(LOGIN_STEPS):
        state = "active" if i == active else "done" if 0 <= active and i < active else ""
        chips += f'<div class="ls {state}"><i>{i + 1}</i><span>{name}</span></div>'
    return f'<div class="login-steps">{chips}</div>'


@st.fragment(run_every=2)
def login_watch():
    """로그인 팝업이 열려 있는 동안 2초마다 확인한다 (서버는 WebSocket 도 지원)."""
    ss = st.session_state
    login = ss.login
    if not login:
        return
    event = poll_login_once()
    if not ss.login:  # 로그인 완료 → 전체 화면을 다시 그려 팝업을 닫는다
        st.rerun()
    left = max(0, int(login["expires_in"] - (time.time() - login["created"])))
    status = "expired" if left == 0 else (event or {}).get("status", "waiting")
    dim = " expired" if status == "expired" else ""
    st.html(f'<div class="login-qr{dim}"><img src="{qr_data_uri(login["qr_url"])}" alt="로그인 QR 코드">'
            + ('<span class="login-qr-badge">만료됨</span>' if dim else "") + '</div>')
    if status == "expired":
        st.html(login_steps_html(-1) + '<div class="login-status expired">QR이 만료되었어요. 새로고침해 주세요.</div>')
        st.button("🔄 QR 새로고침", key="login_refresh", on_click=new_login, width="stretch", type="primary")
    elif status == "scanned":
        st.html(login_steps_html(1) + '<div class="login-status scanned">📱 스캔 완료! 휴대폰에서 카카오 로그인을 마쳐 주세요</div>'
                f'<div class="login-timer">남은 시간 {left // 60}:{left % 60:02d}</div>')
    else:
        st.html(login_steps_html(0) + '<div class="login-status">휴대폰 카메라로 위 QR을 스캔해 주세요</div>'
                f'<div class="login-timer">남은 시간 {left // 60}:{left % 60:02d}</div>')


LOGIN_REASON = {"spin": ("룰렛을 돌리려면 로그인해 주세요", "로그인하면 룰렛을 한 번 돌릴 수 있어요 (회원당 1회)"),
                "again": ("한 번 더 돌리려면 다른 회원이 로그인해 주세요", "이미 돌린 회원은 다시 돌릴 수 없어요 (회원당 1회)"),
                "more": ("다른 회원도 로그인할 수 있어요", "처음 로그인하는 회원은 룰렛을 한 번 돌릴 수 있어요")}


@st.dialog("📱 휴대폰으로 로그인", width="medium")
def login_dialog(reason="spin"):
    ss = st.session_state
    if server.is_online():
        ensure_login()  # 서버가 안 닿으면 여기서 오프라인으로 표시된다
    if not ss.login:
        st.html('<div class="login-pop"><div class="login-icon">🔌</div><b>로그인을 사용할 수 없어요</b>'
                '<small>' + ("서버에 연결할 수 없어요. 직원에게 문의해 주세요." if not server.is_online()
                             else "로그인 QR을 만들지 못했어요. 잠시 후 다시 시도해 주세요.") +
                '<br>로그인하지 않아도 주문은 가능해요.</small></div>')
        return
    title, sub = LOGIN_REASON[reason]
    st.html(f'<div class="login-pop"><b>{title}</b><small>{sub}</small></div>')
    login_watch()
    st.html('<div class="login-foot">로그인하지 않아도 주문은 할 수 있어요. 창을 닫아도 됩니다.</div>')


def render_profile_form():
    """카카오로 받지 못하는 정보(휴대폰 번호 등)와 마케팅 수신 동의를 직접 입력받는다. 모두 선택."""
    ss = st.session_state
    with st.expander(f"📱 {escape(ss.member['nickname'])}님 회원 정보 입력 (선택)", expanded=not ss.get("profile_saved")):
        with st.form("profile_form"):
            phone = st.text_input("휴대폰 번호", placeholder="010-1234-5678")
            c1, c2 = st.columns(2)
            year = c1.number_input("출생연도", 1920, 2020, value=None, step=1)
            gender = c2.selectbox("성별", ["선택 안 함", "남", "여"])
            consent = st.checkbox("(선택) 쿠폰·이벤트 등 광고성 문자 수신에 동의합니다.")
            st.caption("※ 임시 문구입니다. 정식 서비스 전에 개인정보 처리방침과 동의 문구를 확정해야 해요. "
                       "광고 문자는 21시~08시에는 보내지 않고, 문자 하단 안내로 언제든 수신을 거부할 수 있어요.")
            if st.form_submit_button("저장", type="primary"):
                ok, msg = server.update_profile(
                    ss.access_token, phone=phone.strip() or None, birth_year=int(year) if year else None,
                    gender={"남": "male", "여": "female"}.get(gender), marketing_consent=consent)
                ss.profile_saved = ok
                (st.success if ok else st.error)(msg)
        if st.button("문자 수신거부", key="opt_out_btn"):
            st.toast("수신거부 처리했어요." if server.opt_out(ss.access_token) else "처리하지 못했어요.", icon="🔕")


def render_members_log():
    """이 태블릿에서 로그인한 회원을 로그인할 때마다 아래에 누적해서 보여준다."""
    members = st.session_state.members
    if not members:
        return
    rows = ""
    for i, m in enumerate(members, 1):
        status = (f"🎁 {escape(m['prize'])}" if m["prize"] else "🎟️ 룰렛 대기 중" if m["eligible"]
                  else "룰렛은 이미 참여했어요")
        rows += (f'<li><span class="n">{i}</span><b>{escape(m["nickname"])}님</b>'
                 f'<span class="t">{m["at"]} 로그인</span><em>{status}</em></li>')
    st.html(f'<div class="mlog"><div class="mlog-title">로그인한 회원 <span>{len(members)}</span></div><ul>{rows}</ul></div>')


def render_splash():
    ss = st.session_state
    poll_login_once()  # 팝업을 닫았거나 다시 그려진 뒤에도 완료된 로그인은 반영
    render_roulette()
    member = ss.member
    with st.container(horizontal=True, key="splash_bottom"):
        with st.container(horizontal=True, key="qr_card"):
            if member:
                st.html(f'<div class="qr-text"><div class="a">{escape(member["nickname"])}님</div>'
                        '<div class="b">회원 로그인 완료!</div>'
                        f'<div class="c">남은 룰렛 기회 {spins_left()}회</div></div>')
            else:
                st.html('<div class="qr-text"><div class="a">회원이신가요?</div><div class="b">로그인하고 룰렛 돌리기</div>'
                        '<div class="c">로그인하지 않아도<br>주문은 할 수 있어요.</div></div>')
            if st.button("➕ 다른 회원 로그인" if member else "📱 로그인", key="login_open"):
                login_dialog("more")
        with st.container(key="start_cta"):
            st.button("🍴 회원 주문  ›" if member else "🍴 비회원 주문  ›", type="primary", width="stretch",
                      key="start_btn", on_click=go, args=("menu",))
    if member:
        render_profile_form()
    render_members_log()


def render_header():
    with st.container(key="header"):
        c_brand, c_table, c_actions = st.columns([3.5, 1.2, 4], vertical_alignment="center")
        c_brand.html(f'<div class="brand"><div class="logo">🍺</div><div><div class="name">{STORE["name"]}</div>'
                     f'<div class="sub">{STORE["branch"]}{f" · {escape(st.session_state.member["nickname"])}님 (회원)" if st.session_state.member else " · 비회원"}</div></div></div>')
        c_table.html(f'<div class="table-chip">TABLE <b>{st.session_state.table}</b></div>')
        with c_actions.container(horizontal=True, key="header_actions"):
            if st.button("🔔 직원호출", width="stretch"):
                staff_dialog()
            n_orders = len(st.session_state.orders)
            if st.button(f"🧾 주문내역{f' ({n_orders})' if n_orders else ''}", width="stretch"):
                orders_dialog()
            if st.button(f"🛒 장바구니 ({cart_count()})", width="stretch"):
                cart_dialog()
            st.button("🏠 처음으로", width="stretch", on_click=go, args=("splash",))


def render_categories():
    st.button("💬 AI 질문", key="open_quiz", width="stretch", type="primary", on_click=open_quiz,
              help="몇 가지 질문에 답하면 메뉴 조합을 추천해 드려요")
    for c in CATEGORIES:
        if st.button(f"{c['icon']}  {c['name']}", key=f"cat_{c['id']}", width="stretch",
                     type="primary" if st.session_state.cat == c["id"] else "secondary"):
            st.session_state.cat = c["id"]
            st.rerun()


def render_menu():
    cat = st.session_state.cat
    if cat == "ai":
        render_recommendations()
        return
    items = [m for m in MENU if "BEST" in m["tags"]] if cat == "best" else [m for m in MENU if m["cat"] == cat]
    category = CATEGORY_BY_ID[cat]
    st.html(f'<div class="section-title">{category["icon"]} {category["name"]} <span>{len(items)}</span></div>')
    with st.container(horizontal=True, key="menu_grid"):
        for item in items:
            with st.container(key=f"card_{item['id']}"):
                st.html(thumb_html(item, cart_count(item["id"])) +
                        f'<div class="mname">{item["name"]}</div><div class="mdesc">{item["desc"]}</div>'
                        f'<div class="mprice">{won(item["price"])}</div>')
                if st.button("품절" if item["soldout"] else "담기", key=f"add_{item['id']}", width="stretch",
                             disabled=item["soldout"]):
                    cart_add(item, "", item["price"], 1)
                    st.rerun()


def log_recommendation(params, combos):
    """추천 조합이 노출된 사실을 저장소에 남긴다(AI 추천 적중률 계산용). 같은 결과는 한 번만."""
    ss = st.session_state
    key = (tuple(sorted(params.items(), key=lambda kv: kv[0])), tuple(c["id"] for c in combos))
    if combos and ss.get("last_rec_key") != key:
        ss.last_rec_key = key
        REPO.log_recommendation(ss.table, params, [c["id"] for c in combos], ss.access_token)


def render_combo_cards(combos):
    """추천 조합 카드와 '담기' 버튼 (AI 추천 조합 화면과 AI 질문 결과가 함께 쓴다)."""
    for rank, combo in enumerate(combos, 1):
        with st.container(key=f"ai_combo_{rank}"):
            contents = "".join(
                f'<div class="combo-item">{menu_image_html(MENU_BY_ID.get(c["id"], c), "combo-photo", "combo-emoji")}'
                f'<span>{escape(c["name"])}<small>{escape(c["opt"])}</small></span><b>× {c["qty"]}</b></div>'
                for c in combo["components"])
            st.html(f'<div class="combo-heading"><span class="combo-rank rank-{rank}">{rank}위</span>'
                    f'<h3>{combo["name"]}</h3>{"<span class=\"combo-top\">가장 추천해요</span>" if rank == 1 else ""}</div>'
                    f'<div class="combo-items">{contents}</div>'
                    f'<div class="combo-reason"><strong>✨ 이 조합을 추천한 이유</strong><p>{combo["reason"]}</p></div>'
                    f'<div class="combo-pricing"><span class="combo-discount">{DISCOUNT_PERCENT}% 할인</span>'
                    f'<del>{won(combo["original"])}</del><strong>{won(combo["price"])}</strong>'
                    f'<small>{won(combo["discount"])} 절약</small></div>')
            if st.button(f"{rank}위 조합 담기 · {won(combo['price'])}", key=f"add_combo_{rank}",
                         type="primary" if rank == 1 else "secondary", width="stretch"):
                add_combo(combo)
                st.toast("할인된 가격으로 조합을 담았어요", icon="🛒")
                st.rerun()


def render_recommendations():
    st.html('<div class="ai-hero"><div class="ai-eyebrow">✨ 오늘의 맞춤 메뉴</div>'
            '<h2>AI 추천 조합</h2><p>취향에 맞는 한 상, 조합 할인까지 한 번에.</p>'
            f'<span class="ai-offer">조합으로 주문하면 {DISCOUNT_PERCENT}% 할인</span></div>')
    with st.container(key="ai_preferences"):
        st.html('<div class="ai-preference-title">어떤 한 상을 원하세요?</div>')
        with st.container(key="ai_preference_fields"):
            c1, c2, c3, c4 = st.columns(4, wrap=False)
            people = c1.selectbox("주문 인원", list(range(1, 7)), index=1,
                                  format_func=lambda n: f"{n}명", key="ai_people")
            budget = c2.selectbox("조합 예산", [20000, 30000, 40000, 60000, 100000], index=2,
                                  format_func=lambda n: f"{won(n)} 이하", key="ai_budget")
            spicy = c3.selectbox("맵기 취향", ["상관없어요", "맵지 않게", "매콤하게"], key="ai_spicy")
            drink = c4.selectbox("함께 마실 음료", ["맥주", "소주", "음료", "없이"], key="ai_drink")
        st.caption("선택한 조건에 따라 추천이 바로 바뀝니다. 예산은 한 조합의 할인 후 총액 기준입니다.")
    lines = list(st.session_state.cart.values()) + [line for order in st.session_state.orders for line in order["lines"]]
    combos = recommend_combos(people, budget, spicy, drink, lines, menu_by_id=MENU_BY_ID, rules=RULES)
    log_recommendation({"people": people, "budget": budget, "spicy": spicy, "drink": drink}, combos)
    st.html(f'<div class="section-title ai-results-title">나에게 맞는 추천 <span>{len(combos)}</span>'
            f'<small>{people}명 · {won(budget)} 이하</small></div>')
    if not combos:
        st.info("선택한 조건에 맞는 조합이 없어요. 예산을 높이거나 음료·인원 조건을 바꿔 주세요.")
    render_combo_cards(combos)
    st.caption("현재는 취향과 주문 정보를 반영한 데모 추천입니다. 조합 할인은 세트 단위로 적용됩니다.")


# ============================== AI 질문 ==============================
def open_quiz():
    st.session_state.quiz = {"step": 0, "answers": {}}
    go("ai_quiz")


def quiz_answer(qid, value):
    q = st.session_state.quiz
    q["answers"][qid] = value
    q["step"] = min(q["step"] + 1, len(QUESTIONS))  # 선택하면 바로 다음 질문으로


def quiz_back():
    q = st.session_state.quiz
    q["step"] = max(q["step"] - 1, 0)


def quiz_goto(step):
    st.session_state.quiz["step"] = step


def quiz_restart():
    st.session_state.quiz = {"step": 0, "answers": {}}


def render_quiz_question(step):
    q = QUESTIONS[step]
    answers = st.session_state.quiz["answers"]
    c_back, c_bar, c_close = st.columns([1.2, 5, 2.4], vertical_alignment="center")
    c_back.button("←", key="quiz_back", on_click=quiz_back, disabled=step == 0, width="stretch", help="이전 질문")
    c_bar.html(f'<div class="qz-progress"><span class="n">{step + 1}</span><div class="bar">'
               f'<i style="width:{(step + 1) / len(QUESTIONS) * 100:.0f}%"></i></div><span class="t">{len(QUESTIONS)}</span></div>')
    c_close.button("🍽️ 메뉴로 돌아가기", key="quiz_close", on_click=go, args=("menu",), width="stretch", help="질문을 그만하고 메뉴 화면으로 돌아가기")
    st.html(f'<div class="qz-group">{escape(q["group"])}</div><h2 class="qz-title">{escape(q["title"])}</h2>')
    with st.container(horizontal=True, key="quiz_grid"):
        for i, o in enumerate(q["options"]):
            with st.container(key=f"quiz_opt_{i}"):
                st.html(f'<div class="qz-emoji">{o["emoji"]}</div>')
                st.button(o["label"], key=f"quiz_pick_{q['id']}_{i}", width="stretch", on_click=quiz_answer,
                          args=(q["id"], o["value"]), type="primary" if answers.get(q["id"]) == o["value"] else "secondary")
    st.html('<div class="qz-hint">선택하면 바로 다음 질문으로 넘어가요 · 시간대와 날씨는 자동으로 반영돼요</div>')


def render_quiz_result():
    ss = st.session_state
    a = ss.quiz["answers"]
    hour, slot = time_slot()
    weather = current_weather(WEATHER, st.query_params.get("weather"))
    w_label, w_icon = WEATHER["types"][weather]["label"], WEATHER["types"][weather]["icon"]
    lines = list(ss.cart.values()) + [line for order in ss.orders for line in order["lines"]]
    combos = recommend_combos(a["people"], a["budget"], a["spicy"], "맥주", lines, menu_by_id=MENU_BY_ID, rules=RULES,
                              hour=hour, weather=weather, hunger=a["hunger"], stress=a["stress"], kind=a["kind"],
                              intent=a["intent"], gender=a["gender"])
    log_recommendation({**a, "hour": hour, "weather": weather}, combos)
    chips = "".join(f'<span class="qz-chip">{escape(answer_label(QUESTIONS, q["id"], a[q["id"]]))}</span>' for q in QUESTIONS)
    st.html('<div class="ai-hero"><div class="ai-eyebrow">✨ AI 질문 결과</div><h2>맞춤 메뉴 조합이 완성됐어요</h2>'
            f'<p>답변해 주신 {len(QUESTIONS)}가지와 오늘의 상황을 반영했어요.</p></div>'
            f'<div class="qz-chips">{chips}</div>'
            f'<div class="qz-auto">자동 반영 · 🕒 {slot} ({hour}시) · {w_icon} 날씨 {w_label} <small>(날씨는 더미 데이터)</small></div>')
    if not combos:
        st.info("선택한 조건에 맞는 조합이 없어요. 예산이나 인원을 바꿔서 다시 골라 보세요.")
        st.button("💵 예산 다시 고르기", key="quiz_edit_budget", on_click=quiz_goto, args=(len(QUESTIONS) - 1,))
    else:
        st.html(f'<div class="section-title ai-results-title">추천 조합 <span>{len(combos)}</span></div>')
        render_combo_cards(combos)
    c1, c2 = st.columns(2)
    c1.button("🔄 처음부터 다시 질문", key="quiz_restart", on_click=quiz_restart, width="stretch")
    c2.button("🍽️ 메뉴 보러가기", key="quiz_to_menu", on_click=go, args=("menu",), type="primary", width="stretch")
    st.caption("현재는 더미 데이터와 임시 규칙으로 만든 데모 추천입니다. 조합 할인은 세트 단위로 적용됩니다.")


def render_ai_quiz():
    step = st.session_state.quiz["step"]
    with st.container(key="quiz_page"):
        if step < len(QUESTIONS):
            render_quiz_question(step)
        else:
            render_quiz_result()


def render_cart(dialog=False):
    cart = st.session_state.cart
    with st.container(key="dialog_cart_panel" if dialog else "cart_panel"):
        st.html(f'<div class="cart-title">🛒 장바구니 <span>{cart_count()}</span></div>')
        with st.container(key="dialog_cart_items" if dialog else "cart_items"):
            if not cart:
                st.html('<div class="cart-empty"><span class="emoji">🍻</span>메뉴를 담아주세요</div>')
            for key, l in list(cart.items()):
                st.html(f'<div class="cart-line"><div><div class="n">{l["name"]}</div>'
                            f'<div class="o">{l["opt"]}</div></div><div class="p">{won(l["unit"] * l["qty"])}</div></div>')
                c1, c2, c3, c4 = st.columns(4, vertical_alignment="center", wrap=False)
                prefix = "dialog_" if dialog else ""
                c1.button("−", key=f"q_{prefix}dec_{key}", help=f"{l['name']} 수량 줄이기", width="stretch", on_click=cart_change, args=(key, -1))
                c2.html(f'<div class="quantity">{l["qty"]}</div>')
                c3.button("+", key=f"q_{prefix}inc_{key}", help=f"{l['name']} 수량 늘리기", width="stretch", on_click=cart_change, args=(key, 1))
                c4.button("🗑", key=f"q_{prefix}del_{key}", help=f"{l['name']} 삭제", width="stretch", on_click=cart_remove, args=(key,))
                st.divider()
        if cart_discount():
            st.html(f'<div class="cart-savings">✨ AI 조합으로 {won(cart_discount())} 할인받았어요</div>')
        if roulette_discount():
            st.html(f'<div class="cart-savings">🎟️ 룰렛 {st.session_state.roulette_percent}% 할인 −{won(roulette_discount())}</div>')
        st.html(f'<div class="total-row"><span>총 주문금액</span><b>{won(cart_total())}</b></div>')
        if st.button("주문 확인하기", type="primary", width="stretch", key="dialog_order_btn" if dialog else "order_btn", disabled=not cart):
            st.session_state.confirm_order = True
            st.rerun()


def sync_url():
    """현재 화면을 URL 쿼리에 반영한다 (splash·AI 질문 중에는 주문 화면 기준으로 둔다)."""
    qp = st.query_params
    want = {} if st.session_state.page == "splash" else {"page": "order", "cat": st.session_state.cat}
    for k in ("page", "cat"):
        if want.get(k) is None:
            qp.pop(k, None)
        elif qp.get(k) != want[k]:
            qp[k] = want[k]


def main():
    init_state()
    sync_url()
    st.html(Path(__file__).with_name("app.css"))
    if st.session_state.page == "splash":
        render_splash()
        return
    render_header()
    if st.session_state.page == "ai_quiz":
        render_ai_quiz()
        if st.session_state.pop("confirm_order", False):
            confirm_dialog()
        return
    with st.container(key="order_layout"):
        c_cat, c_menu, c_cart = st.columns([1.15, 5.2, 2.5], gap="medium")
    with c_cat:
        with st.container(key="categories"):
            render_categories()
    with c_menu:
        render_menu()
    with c_cart:
        render_cart()
    if st.session_state.pop("confirm_order", False):
        confirm_dialog()


main()
