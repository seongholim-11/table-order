# Table Order

FastAPI 서버 + 사용자 페이지 + 관리자 페이지를 한 저장소에서 관리하는 모노레포입니다.

```
backend/   FastAPI 서버 (app factory 구조: core / routers / services / stores)
user/      사용자(손님) Streamlit 페이지
admin/     관리자 Streamlit 페이지
shared/    두 페이지가 같이 쓰는 API 호출 코드
```

## 실행

```bash
# 서버 (http://127.0.0.1:8000/docs)
cd backend
cp .env.example .env
uv sync
uv run fastapi dev main.py

# 페이지 (저장소 루트에서, 서버가 켜져 있어야 QR 로그인·문자 발송이 동작)
pip install -r requirements.txt
streamlit run user/app.py --server.port 8501    # 사용자 (?table=12 로 테이블 지정)
streamlit run admin/app.py --server.port 8502   # 관리자 (현재 토큰 입력 생략. 끄려면 ADMIN_SKIP_TOKEN=0, 토큰은 ADMIN_TOKEN)
```

- 휴대폰으로 QR 로그인을 시험하려면 `backend/.env` 의 `PUBLIC_BASE_URL` 을 서버 PC 주소(예: `http://192.168.0.10:8000`)로 두고 `--host 0.0.0.0` 으로 실행하세요. 카카오 키가 없으면 모의 로그인 화면이 열립니다.
- 문자 발송은 `SMS_DRY_RUN=true`(기본)이면 실제 전송 없이 기록만 남깁니다.
- 자세한 계획과 체크리스트: `docs/PRODUCTION_PLAN.md`

## Streamlit Community Cloud 배포 (user·admin 각각)

같은 저장소에서 앱 두 개를 따로 만듭니다. <https://share.streamlit.io> → **Create app** → *Deploy a public app from GitHub* 에서 두 번 반복하세요.

| 앱 | Repository | Branch | Main file path | 권장 URL |
|---|---|---|---|---|
| 사용자 | `seongholim-11/table-order` | `main` | `user/app.py` | `…-user.streamlit.app` |
| 관리자 | `seongholim-11/table-order` | `main` | `admin/app.py` | `…-admin.streamlit.app` |

- 의존성은 루트 `requirements.txt`, 테마는 루트 `.streamlit/config.toml` 을 두 앱이 함께 씁니다. Python 버전은 Advanced settings 에서 3.11 이상을 고르세요.
- Advanced settings → **Secrets** (TOML, 최상위 키는 환경 변수로도 읽힙니다):
  - 둘 다 더미로만 시연: `DATA_SOURCE = "dummy"`
  - 관리자 더미 로그인 토큰 바꾸기: `ADMIN_TOKEN = "원하는-비밀번호"` (기본값 `change-me` 는 공개 배포 시 반드시 변경)
  - 실제 백엔드 연결: `DATA_SOURCE = "api"` 와 `API_URL = "https://백엔드-주소"` (FastAPI 서버는 Streamlit Cloud 에서 돌릴 수 없으니 Render/Fly.io 등에 따로 배포하고, 그 `CORS_ORIGINS`·`PUBLIC_BASE_URL` 에 두 앱 주소를 넣으세요)
- `DATA_SOURCE=auto`(기본)에서 `127.0.0.1` 서버는 클라우드에서 닿지 않으므로 자동으로 더미로 동작합니다. 의도를 분명히 하려면 `dummy` 를 명시하세요.
- 사용자 페이지는 `?table=12` 로 테이블을 지정합니다. 테이블별 QR 은 배포된 사용자 앱 주소 뒤에 이 값을 붙여 만드세요.

## 데이터 소스 전환 (더미 ↔ API)

화면(user·admin)의 데이터는 모두 **저장소 한 곳**을 거칩니다. 환경 변수 `DATA_SOURCE` 로 바꿉니다.

| 값 | 동작 |
|---|---|
| `auto` (기본) | 서버가 닿으면 API, 안 닿으면 더미 |
| `api` | 서버(`API_URL`, 기본 `http://127.0.0.1:8000`)에서만. 안 닿으면 오류 안내 |
| `dummy` | 코드 안의 더미만 (서버 불필요) |

```bash
DATA_SOURCE=api API_URL=http://127.0.0.1:8000 streamlit run user/app.py
DATA_SOURCE=dummy streamlit run admin/app.py     # 로그인 토큰은 ADMIN_TOKEN(기본 change-me)
```

| 구분 | 저장소 (여기만 보면 됨) | 더미 데이터 (= API 응답 명세) |
|---|---|---|
| user | `user/user_repository.py` | `user/menu_data.py`, `ai_quiz_data.py`, `recommendation_data.py` |
| admin | `admin/admin_repository.py` | `admin/admin_dummy_data.py` (서버와 같은 JSON 을 돌려주는 가짜 서버) |

- 더미 파일은 서버 응답과 **같은 JSON 모양**이라 변환 코드가 필요 없습니다. 서버 초기 데이터는 `python tools/export_dummy_seed.py` 로 더미에서 만듭니다.
- 새 데이터를 API로 바꾸려면: 저장소의 `ENDPOINTS` 에 경로 추가 → 가져오는 줄 추가 → 서버 응답을 더미와 같은 모양으로 맞추기. 맞는지는 `tests/test_admin_data_source.py`, `backend/tests/test_shop_admin.py` 의 계약 테스트가 확인합니다.
- 콘텐츠(카테고리·룰렛·직원호출 항목·AI 질문·추천 규칙)는 `GET /api/content`, 관리자는 `PUT /admin/api/content/{이름}` 으로 고칩니다.
- 서버 데이터는 10초 캐시되어 관리자가 바꾼 가격·품절이 곧 반영됩니다.

## 테스트

```bash
(cd backend && python -m pytest)          # 백엔드
python -m pytest tests                    # user·admin ↔ 백엔드 통합
(cd user && python -m unittest test_ai_quiz test_cart test_recommendations)
```

## 규칙

- API 경로: 사용자용 `/api/...`, 관리자용 `/admin/api/...`
- CORS 허용 주소는 `backend/.env`의 `CORS_ORIGINS`에서 관리
