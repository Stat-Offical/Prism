# Prism

통계 보도자료를 기준으로 관련 뉴스를 수집·제공하는 뉴스 포털.

## 파일별 역할

| 파일 | 역할 |
| --- | --- |
| `collect_prism_news.py` | RSS 제목과 발행기관명으로 뉴스 검색, 결과 저장 |
| `fetch_bodies.py` | 기사 본문·대표 이미지·언론사 정보 추출 |
| `build_prism_data.py` | 저장된 결과로 `web/data.js` 생성 |
| `news_api.py` | API 설정, 기사 중복 제거, 날짜 처리, 결과·로그 관리 |
| `news_transport.py` | HTTP 요청, `.env` 로딩, 오류 메시지의 인증정보 마스킹 |
| `web/index.html` | 웹 페이지 기본 구조 |
| `web/app.js` | 뉴스 목록·검색·상세 화면·연관 기사 표시 |
| `web/styles.css` | PC·모바일 화면 스타일 |
| `web/assets/` | 로고와 기본 기사 이미지 |
| `data/query_comparison_temp.html` | 검색어별 결과 비교용 임시 보고서 |
| `requirements.txt` | Python 의존성 목록 |
| `.env.example` | 공유용 환경변수 예시 |
| `.env` | 개인 인증정보와 로컬 설정, Git 제외 |
| `.gitignore` | Git 추적 제외 규칙 |

## 설치와 환경 설정

- Python 3.10 이상 필요
- 아래 명령은 macOS·Python 3.12 기준, 프로젝트 폴더에서 실행

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

`.env.example`은 유지하고, 복사한 `.env`에 본인 설정 입력.

| 환경변수 | 설정할 값 |
| --- | --- |
| `NAVER_API_PROVIDER` | 개발자센터: `developers`, 네이버 클라우드: `ncp` |
| `NAVER_CLIENT_ID` | 본인의 API 클라이언트 ID |
| `NAVER_CLIENT_SECRET` | 본인의 API 클라이언트 시크릿 |
| `RSS_URL` | RSS 피드 주소 |
| `RSS_PUBLISHER` | RSS 발행기관명 |
| `RSS_COUNTRY` | RSS 발행기관의 국가 |

## 실행

뉴스 검색 → 본문 수집 → 웹 서버 실행 순서.

```bash
python collect_prism_news.py --limit 10 --per-release 30
python fetch_bodies.py --limit 24
python -m http.server 8000 --bind 127.0.0.1 --directory web
```

접속 주소: <http://127.0.0.1:8000>

저장된 결과로 웹 데이터만 다시 생성할 경우:

```bash
python build_prism_data.py
```

## 참고

- 수집 결과·로그: `data/news_.../`
- 최신 수집 폴더 기록: `data/latest_prism_news.txt`
- 웹 데이터: `web/data.js` (뉴스 검색·본문 수집 후 자동 갱신)
- 본문 수집: 실행당 도메인별 최대 3건, `robots.txt`와 서버 응답에 따라 실패 가능
- 연관 기사: 같은 검색어로 수집된 기사 중 네이버 API 순위 기준

