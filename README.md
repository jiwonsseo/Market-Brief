# Global Market Brief 봇

미국장 마감 후 KST 아침(화~토)에 모닝브리핑을 텔레그램으로 보냅니다.

- 지수 등락률, 금리·유가·환율 등 숫자: yfinance (코드가 계산)
- 주요 종목 후보: 시총 100억달러 이상 ±3% 급등락 종목 + 관심 종목(±2%)과 각 종목 기사
- 시장 뉴스: Bloomberg · CNBC · MarketWatch · Yahoo Finance 공개 RSS
- 본문 작성: Google Gemini API (무료 티어)

## 설정 순서

1. Gemini API 키 발급: https://aistudio.google.com/apikey → Create API key (무료, 카드 등록 불필요)
2. GitHub에서 New repository → 이름 `global-market-brief` → **Private** → Create
3. 저장소 화면의 "uploading an existing file" 링크 → 압축 푼 폴더 안의 파일들을 끌어다 놓고 Commit
   - `.github` 폴더는 숨김 폴더라 안 보일 수 있음. 이 경우 Add file → Create new file에서
     파일 이름을 `.github/workflows/brief.yml`로 입력하고 내용을 붙여넣기
4. Settings → Secrets and variables → Actions → New repository secret
   - `TG_TOKEN` (재발급한 봇 토큰), `TG_CHAT_ID`, `GEMINI_API_KEY`
5. Actions 탭 → Global Market Brief → Run workflow로 테스트

## 조정 포인트

- 발송 요일·시각: `.github/workflows/brief.yml`의 cron (UTC 기준)
- 관심 종목: `main.py`의 `WATCHLIST`
- 문체·구성 규칙: `main.py`의 `SYSTEM` 프롬프트
- 모델 변경: Secrets 또는 env에 `GEMINI_MODEL` 지정
- 로컬 테스트: `DRY_RUN=1 python main.py` (텔레그램 발송 없이 출력)
