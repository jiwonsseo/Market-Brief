"""
Global Market Brief - 매일 아침 미국 증시 모닝브리핑을 텔레그램으로 발송

환경변수 (GitHub Secrets에 등록)
  TG_TOKEN        텔레그램 봇 토큰
  TG_CHAT_ID      받을 chat_id
  GEMINI_API_KEY  Google AI Studio에서 무료 발급
선택
  GEMINI_MODEL    사용할 Gemini 모델 (기본: gemini-flash-latest)
  DRY_RUN=1       텔레그램으로 보내지 않고 화면에만 출력
"""
import os
import json
import time
import datetime as dt
from zoneinfo import ZoneInfo

import requests
import feedparser
import yfinance as yf
from yfinance import EquityQuery

KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (GlobalMarketBrief)"}

# ─────────────────────────────────────────────
# 1. 지수 · 매크로 데이터 (숫자는 전부 코드가 계산)
# ─────────────────────────────────────────────
INDEX = [("S&P500", "^GSPC"), ("NASDAQ", "^IXIC"), ("DOW", "^DJI")]
MACRO = [
    ("러셀2000", "^RUT", "pct"), ("SOX지수", "^SOX", "pct"), ("VIX", "^VIX", "lvl"),
    ("미 10년물 금리", "^TNX", "rate"), ("미 5년물 금리", "^FVX", "rate"),
    ("WTI", "CL=F", "pct"), ("금", "GC=F", "pct"), ("비트코인", "BTC-USD", "pct"),
    ("달러인덱스", "DX-Y.NYB", "pct"), ("원/달러", "KRW=X", "krw"),
]


def last_two_closes(ticker):
    h = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False)
    h = h.dropna(subset=["Close"])
    return float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2]), h.index[-1].date()


def fetch_indices():
    out, us_date = [], None
    for name, tk in INDEX:
        try:
            last, prev, d = last_two_closes(tk)
            out.append(f"{name} {(last / prev - 1) * 100:+.2f}%")
            us_date = us_date or d
        except Exception as e:
            print(f"[지수] {tk} 실패: {e}")
            out.append(f"{name} N/A")
    return ", ".join(out), us_date


def fetch_macro():
    lines = []
    for name, tk, kind in MACRO:
        try:
            last, prev, _ = last_two_closes(tk)
            if kind == "rate":
                lines.append(f"{name}: {last:.3f}% ({(last - prev) * 100:+.1f}bp)")
            elif kind == "krw":
                lines.append(f"{name}: {last:,.1f}원 ({last - prev:+.1f}원)")
            elif kind == "lvl":
                lines.append(f"{name}: {last:.2f} ({last - prev:+.2f})")
            else:
                lines.append(f"{name}: {last:,.2f} ({(last / prev - 1) * 100:+.1f}%)")
        except Exception as e:
            print(f"[매크로] {tk} 실패: {e}")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 2. 주요 종목 후보: 시총 100억달러 이상 급등락 + 관심 종목
# ─────────────────────────────────────────────
WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD",
             "MU", "TSM", "ARM", "PLTR", "ORCL", "INTC", "QCOM", "ASML", "NFLX", "COIN"]


def screen_movers(min_cap=10e9, min_move=3.0, size=25):
    base = [EquityQuery("eq", ["region", "us"]),
            EquityQuery("gt", ["intradaymarketcap", min_cap])]
    quotes = []
    for asc, cond in [(False, EquityQuery("gt", ["percentchange", min_move])),
                      (True, EquityQuery("lt", ["percentchange", -min_move]))]:
        try:
            res = yf.screen(EquityQuery("and", base + [cond]),
                            sortField="percentchange", sortAsc=asc, size=size)
            quotes += res.get("quotes", [])
        except Exception as e:
            print(f"[스크리너] 실패: {e}")
    return quotes


def fetch_movers(max_n=30):
    movers = {}
    for q in screen_movers():
        sym = q.get("symbol")
        pct = q.get("regularMarketChangePercent")
        if sym and pct is not None:
            movers[sym] = {"name": q.get("shortName") or q.get("longName") or sym,
                           "pct": float(pct),
                           "post": q.get("postMarketChangePercent")}
    for sym in WATCHLIST:  # 관심 종목은 ±2% 이상이면 후보에 포함
        if sym in movers:
            continue
        try:
            last, prev, _ = last_two_closes(sym)
            pct = (last / prev - 1) * 100
            if abs(pct) >= 2:
                movers[sym] = {"name": sym, "pct": pct, "post": None}
        except Exception:
            pass
    ranked = sorted(movers.items(), key=lambda kv: abs(kv[1]["pct"]), reverse=True)
    return dict(ranked[:max_n])


def ticker_news(sym, n=4):
    """yfinance 종목 뉴스 (제목+요약). 응답 형식이 버전마다 달라 둘 다 처리"""
    out = []
    try:
        for item in (yf.Ticker(sym).news or [])[:n]:
            c = item.get("content", item)
            title = c.get("title") or ""
            summary = (c.get("summary") or c.get("description") or "")[:400]
            if title:
                out.append(f"  - {title} — {summary}")
    except Exception as e:
        print(f"[종목뉴스] {sym} 실패: {e}")
    return out


def format_movers(movers):
    blocks = []
    for sym, m in movers.items():
        post = f", 시간외 {m['post']:+.1f}%" if m.get("post") else ""
        head = f"{sym} | {m['name']} | 정규장 {m['pct']:+.1f}%{post}"
        news = ticker_news(sym)
        blocks.append(head + ("\n" + "\n".join(news) if news else "\n  - (관련 기사 없음)"))
        time.sleep(0.3)
    return "\n".join(blocks)


# ─────────────────────────────────────────────
# 3. 시장 뉴스 (공개 RSS)
# ─────────────────────────────────────────────
RSS_FEEDS = {
    "Bloomberg Markets": "https://feeds.bloomberg.com/markets/news.rss",
    "Bloomberg Economics": "https://feeds.bloomberg.com/economics/news.rss",
    "Bloomberg Technology": "https://feeds.bloomberg.com/technology/news.rss",
    "CNBC Top News": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "CNBC Economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "CNBC Earnings": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135",
    "CNBC Technology": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
}


def fetch_headlines(hours=22, per_feed=30):
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    items, seen = [], set()
    for src, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=15).content)
        except Exception as e:
            print(f"[RSS] {src} 실패: {e}")
            continue
        for e in feed.entries[:per_feed]:
            title = (e.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            t = e.get("published_parsed") or e.get("updated_parsed")
            if t and dt.datetime(*t[:6], tzinfo=dt.timezone.utc) < cutoff:
                continue
            seen.add(title.lower())
            items.append(f"[{src}] {title} — {(e.get('summary') or '')[:300]}")
    return items


# ─────────────────────────────────────────────
# 4. Gemini로 본문 작성
# ─────────────────────────────────────────────
SYSTEM = """너는 한국 증권사 투자전략팀의 미국증시 시황 애널리스트다. 매일 아침 텔레그램 '모닝브리핑' 본문을 쓴다.

[출력 형식 — 반드시 그대로]
■ 핵심 이슈 제목 1
본문 3~4문장

■ 핵심 이슈 제목 2
본문 3~4문장

■ 핵심 이슈 제목 3
본문 3~4문장


===========

■ 주요 종목

» 회사명(+X.X%)
1~3문장

» 회사명(-X.X%)
1~3문장

(주요 종목은 8~12개)

※ 오늘 주목할 내용
2~4문장

[핵심 이슈 작성법]
- 전일 미국장의 가장 중요한 이슈 3개(매크로·금리·지정학·섹터·대형 테마)를 고른다.
- 제목은 짧고 핵심이 드러나게. 따옴표 인용형도 가능(예: ■ Micron “27·28년이 올해보다 더 타이트”).
- 본문은 사실 → 원인 → 시장 함의 순서. 금리 bp, 유가 %, 지표 수치 등 구체적 숫자를 넣는다.

[주요 종목 작성법]
- 회사명은 영어 통용명(Micron, Alphabet, Constellation Energy 등). 법인 접미사(Inc., Corp.)는 뺀다.
- 등락률은 [종목 데이터]의 '정규장' 값을 소수 첫째 자리까지 그대로 쓴다. 절대 바꾸거나 추정하지 않는다.
- 두 종목이 같은 이슈로 엇갈리면 한 줄로 묶는다: » United Therapeutics(+5.4%) / Liquidia(-7.5%)
- 등락 사유가 기사로 확인되는 종목만 쓴다. 사유를 모르는 종목은 뺀다.
- 비상장 기업의 중요 뉴스(IPO 등)는 등락률 없이 » 회사명 으로 쓸 수 있다.
- 핵심 이슈에서 다룬 종목도 주요 종목에 다시 넣어도 된다.

[오늘 주목할 내용]
- 자료에서 확인되는 오늘 밤(미국 시간) 또는 이번 주 주요 지표·이벤트·실적 발표와 시장 관전 포인트.
- 컨센서스 수치는 자료에 있을 때만 쓴다.

[문체 규칙]
- 음슴체로 끝맺는다(~상승, ~확인, ~전망, ~부각, ~모습, ~지속).
- 합니다체, 인사말, 마무리 멘트 금지.
- 감정적 형용사(놀라운, 엄청난, 획기적인, 충격적인, 폭발적인) 금지.
- '무대', '베팅', '기록적인', '역대 최대' 단어 금지.
- 추측성 표현(~로 보인다, ~인 것 같다) 금지. 투자 권유 금지.
- 마크다운(#, **, 표)·이모지 금지. 일반 텍스트만.

[사실성]
- 제공된 [시장 데이터], [종목 데이터], [뉴스]에 있는 내용만 쓴다. 없는 수치·사건을 지어내지 않는다.
- 기사 문장을 그대로 번역하지 말고 한국어 애널리스트 노트 톤으로 재서술한다."""

USER_TMPL = """브리핑 날짜: {kst} (KST), 대상 미국 거래일: {us_date}

[지수]
{indices}

[시장 데이터]
{macro}

[종목 데이터] (티커 | 이름 | 등락률, 아래는 관련 기사)
{movers}

[뉴스]
{news}

위 형식대로 '■ 핵심 이슈 제목 1'부터 '※ 오늘 주목할 내용' 끝까지만 출력해."""


def call_gemini(system, user):
    key = os.environ["GEMINI_API_KEY"]
    models = [os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash", "gemini-flash-latest"]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 16384},
    }
    last_err = None
    for model in dict.fromkeys(models):  # 중복 제거, 순서 유지
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(3):
            r = requests.post(url, headers={"x-goog-api-key": key,
                                            "Content-Type": "application/json"},
                              data=json.dumps(body), timeout=180)
            if r.status_code in (429, 500, 503):
                last_err = f"{model}: {r.status_code} {r.text[:200]}"
                time.sleep(20 * (attempt + 1))
                continue
            if not r.ok:
                last_err = f"{model}: {r.status_code} {r.text[:300]}"
                break  # 모델명 오류 등 → 다음 모델 시도
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if text.strip():
                print(f"[Gemini] 사용 모델: {model}")
                return text.strip()
    raise RuntimeError(f"Gemini 호출 실패: {last_err}")


def clean(text):
    # 혹시 섞여 나온 마크다운 제거
    return text.replace("**", "").replace("```", "").strip()


# ─────────────────────────────────────────────
# 5. 텔레그램 발송 (일반 텍스트)
# ─────────────────────────────────────────────
def send_telegram(text):
    token, chat_id = os.environ["TG_TOKEN"], os.environ["TG_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in split_message(text):
        r = requests.post(url, data={"chat_id": chat_id, "text": chunk,
                                     "disable_web_page_preview": True}, timeout=20)
        r.raise_for_status()


def split_message(text, limit=4000):
    parts, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > limit:
            parts.append(buf.rstrip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        parts.append(buf.rstrip())
    return parts


def main():
    now = dt.datetime.now(KST)
    indices, us_date = fetch_indices()
    macro = fetch_macro()
    movers = fetch_movers()
    movers_txt = format_movers(movers)
    news = fetch_headlines()
    print(f"[수집] 종목 {len(movers)}개, 뉴스 {len(news)}건")

    body = clean(call_gemini(SYSTEM, USER_TMPL.format(
        kst=now.strftime("%Y-%m-%d"), us_date=us_date, indices=indices, macro=macro,
        movers=movers_txt or "(없음)", news="\n".join(news[:150]) or "(없음)")))

    msg = f"[{now:%Y.%m.%d} 모닝브리핑]\n{indices}\n\n{body}"

    if os.environ.get("DRY_RUN") == "1":
        print(msg)
    else:
        send_telegram(msg)
        print("발송 완료")


if __name__ == "__main__":
    main()
