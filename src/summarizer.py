from __future__ import annotations

import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from src.config import PROJECT_ROOT, Settings
from src.models import FilteredArticle, SummarizedArticle

logger = logging.getLogger(__name__)

# Seconds to wait between requests to stay within free-tier RPM limits.
_REQUEST_DELAY = float(os.getenv("SUMMARIZER_REQUEST_DELAY", "1.0"))
_MAX_RETRIES = 5

# Matches stray Chinese/Japanese characters embedded in Korean text.
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+")

# Post-processing fixes for common LLM calques (longer patterns first).
_KOREAN_PHRASE_FIXES: list[tuple[str, str]] = [
    # Energy/grid calques
    (r"산업용\s*유연\s*부하\s*보유자", "산업용 수요조절이 가능한 시설·기업"),
    (r"상업용\s*유연\s*부하\s*보유자", "상업용 수요조절이 가능한 시설·기업"),
    (r"유연\s*부하\s*보유자", "수요조절 참여 기업·시설"),
    (r"유연\s*수요", "수요조절(DR) 자원"),
    (r"유연\s*용량", "조절 가능 용량"),
    (r"유연\s*부하", "수요조절 가능 부하"),
    (r"유연\s*자원", "수요·공급 조절 자원"),
    (r"유연\s*전력", "조절 가능 전력"),
    # Calques of English "underscores/highlights": "X를 강조한다/강조함"
    # 사물·사건이 주어일 때 한국어에서 '강조하다'는 자연스럽지 않음.
    (r"수요를\s*강조(?:한다|함)([.。]?)", r"수요가 이어지고 있음을 보여줌\1"),
    (r"헌신을\s*강조(?:한다|함)([.。]?)", r"역량 강화 의지를 재확인함\1"),
    (r"헌신을\s*강조(?:한다|함)", "역량 강화 의지를 재확인함"),
    # Korean grammar errors: redundant topic/possessive markers
    # e.g. "시장은의" → "시장의", "기업의은" → "기업은"
    (r"([가-힣A-Za-z0-9]+)은의\s", r"\1의 "),
    (r"([가-힣A-Za-z0-9]+)는의\s", r"\1의 "),
    (r"([가-힣A-Za-z0-9]+)의은\s", r"\1은 "),
    (r"([가-힣A-Za-z0-9]+)의는\s", r"\1는 "),
    # 합니다/ㅂ니다체 → -함/-임/-었음 (sentence-final, . optional)
    # Past tense before present; longer patterns before shorter.
    (r"지\s*않\s*았습니다([.。？!?]?)$", r"지 않았음\1"),
    (r"지\s*않\s*았다([.。？!?]?)$", r"지 않았음\1"),
    (r"났습니다([.。？!?]?)$", r"났음\1"),
    (r"났다([.。？!?]?)$", r"났음\1"),
    (r"켰습니다([.。？!?]?)$", r"켰음\1"),
    (r"켰다([.。？!?]?)$", r"켰음\1"),
    (r"렸습니다([.。？!?]?)$", r"렸음\1"),
    (r"렸다([.。？!?]?)$", r"렸음\1"),
    (r"하였습니다([.。？!?]?)$", r"했음\1"),
    (r"했습니다([.。？!?]?)$", r"했음\1"),
    (r"하였다([.。？!?]?)$", r"했음\1"),
    (r"했다([.。？!?]?)$", r"했음\1"),
    (r"되었습니다([.。？!?]?)$", r"되었음\1"),
    (r"됐습니다([.。？!?]?)$", r"됐음\1"),
    (r"되었다([.。？!?]?)$", r"되었음\1"),
    (r"됐다([.。？!?]?)$", r"됐음\1"),
    (r"였습니다([.。？!?]?)$", r"였음\1"),
    (r"([가-힣])였다([.。？!?]?)$", r"\1였음\2"),
    (r"었습니다([.。？!?]?)$", r"었음\1"),
    (r"([가-힣])었다([.。？!?]?)$", r"\1었음\2"),
    (r"([가-힣])았다([.。？!?]?)$", r"\1았음\2"),
    (r"않았습니다([.。？!?]?)$", r"않았음\1"),
    (r"해야\s*합니다([.。？!?]?)$", r"해야 함\1"),
    (r"([가-힣])합니다([.。？!?]?)$", r"\1함\2"),
    (r"([가-힣])입니다([.。？!?]?)$", r"\1임\2"),
    (r"([가-힣])있습니다([.。？!?]?)$", r"\1있음\2"),
    (r"([가-힣])없습니다([.。？!?]?)$", r"\1없음\2"),
    (r"([가-힣])됩니다([.。？!?]?)$", r"\1됨\2"),
    (r"([가-힣])보입니다([.。？!?]?)$", r"\1보임\2"),
    (r"([가-힣])줍니다([.。？!?]?)$", r"\1줌\2"),
    (r"([가-힣])둡니다([.。？!?]?)$", r"\1둠\2"),
    (r"나타냅니다([.。？!?]?)$", r"나타냄\1"),
    (r"나타납니다([.。？!?]?)$", r"나타남\1"),
    (r"습니다([.。？!?]?)$", r"음\1"),
    (r"해야\s*한다([.。？!?]?)$", r"해야 함\1"),
    (r"([가-힣])한다([.。？!?]?)$", r"\1함\2"),
    (r"([가-힣])하다([.。？!?]?)$", r"\1함\2"),
    (r"([가-힣])이다([.。？!?]?)$", r"\1임\2"),
    (r"([가-힣])있다([.。？!?]?)$", r"\1있음\2"),
    (r"([가-힣])없다([.。？!?]?)$", r"\1없음\2"),
    (r"([가-힣])된다([.。？!?]?)$", r"\1됨\2"),
    (r"([가-힣])보인다([.。？!?]?)$", r"\1보임\2"),
    (r"([가-힣])온다([.。？!?]?)$", r"\1옴\2"),
    (r"([가-힣])진다([.。？!?]?)$", r"\1짐\2"),
    (r"([가-힣])친다([.。？!?]?)$", r"\1침\2"),
    (r"나타낸다([.。？!?]?)$", r"나타냄\1"),
    (r"나타난다([.。？!?]?)$", r"나타남\1"),
    (r"([가-힣]+)킵니다([.。？!?]?)$", r"\1킴\2"),
    (r"둔다([.。？!?]?)$", r"둠\1"),
    (r"보여준다([.。？!?]?)$", r"보여줬음\1"),
    (r"만든다([.。？!?]?)$", r"만듦\1"),
]

# Repairs for past tense truncated by an older normalizer (맺음→맺었음, etc.).
_TRUNCATED_PAST_REPAIRS: list[tuple[str, str]] = [
    (r"불러일으킴([.。？!?]?)$", r"불러일으켰음\1"),
    (r"일으킴([.。？!?]?)$", r"일으켰음\1"),
    (r"것으로 나타남([.。？!?]?)$", r"것으로 나타났음\1"),
    (r"으로 나타남([.。？!?]?)$", r"으로 나타났음\1"),
    (r"맺음([.。？!?]?)$", r"맺었음\1"),
]

# Sentence-final -다체/-합니다체 → -함/임/-었음 (명사형 종결).
_ENDING_NORMALIZERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"고\s*있도록\s*한다([.。？!?]?)$"), r"고 있도록 함\1"),
    (re.compile(r"지\s*않\s*있다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*한다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*습니다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*는다([.。？!?]?)$"), r"지 않음\1"),
    (re.compile(r"지\s*않\s*았습니다([.。？!?]?)$"), r"지 않았음\1"),
    (re.compile(r"지\s*않\s*았다([.。？!?]?)$"), r"지 않았음\1"),
    (re.compile(r"고\s*있습니다([.。？!?]?)$"), r"고 있음\1"),
    (re.compile(r"고\s*있다([.。？!?]?)$"), r"고 있음\1"),
    (re.compile(r"났습니다([.。？!?]?)$"), r"났음\1"),
    (re.compile(r"났다([.。？!?]?)$"), r"났음\1"),
    (re.compile(r"켰습니다([.。？!?]?)$"), r"켰음\1"),
    (re.compile(r"켰다([.。？!?]?)$"), r"켰음\1"),
    (re.compile(r"렸습니다([.。？!?]?)$"), r"렸음\1"),
    (re.compile(r"렸다([.。？!?]?)$"), r"렸음\1"),
    (re.compile(r"하였습니다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"했습니다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"하였다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"했다([.。？!?]?)$"), r"했음\1"),
    (re.compile(r"되었습니다([.。？!?]?)$"), r"되었음\1"),
    (re.compile(r"됐습니다([.。？!?]?)$"), r"됐음\1"),
    (re.compile(r"되었다([.。？!?]?)$"), r"되었음\1"),
    (re.compile(r"됐다([.。？!?]?)$"), r"됐음\1"),
    (re.compile(r"겠습니다([.。？!?]?)$"), r"겠음\1"),
    (re.compile(r"였습니다([.。？!?]?)$"), r"였음\1"),
    (re.compile(r"([가-힣])였다([.。？!?]?)$"), r"\1였음\2"),
    (re.compile(r"었습니다([.。？!?]?)$"), r"었음\1"),
    (re.compile(r"([가-힣])었다([.。？!?]?)$"), r"\1었음\2"),
    (re.compile(r"([가-힣])았다([.。？!?]?)$"), r"\1았음\2"),
    (re.compile(r"않았습니다([.。？!?]?)$"), r"않았음\1"),
    (re.compile(r"해야\s*합니다([.。？!?]?)$"), r"해야 함\1"),
    (re.compile(r"해야\s*한다([.。？!?]?)$"), r"해야 함\1"),
    (re.compile(r"있습니다([.。？!?]?)$"), r"있음\1"),
    (re.compile(r"없습니다([.。？!?]?)$"), r"없음\1"),
    (re.compile(r"됩니다([.。？!?]?)$"), r"됨\1"),
    (re.compile(r"보입니다([.。？!?]?)$"), r"보임\1"),
    (re.compile(r"줍니다([.。？!?]?)$"), r"줌\1"),
    (re.compile(r"둡니다([.。？!?]?)$"), r"둠\1"),
    (re.compile(r"나타냅니다([.。？!?]?)$"), r"나타냄\1"),
    (re.compile(r"나타납니다([.。？!?]?)$"), r"나타남\1"),
    (re.compile(r"입니다([.。？!?]?)$"), r"임\1"),
    (re.compile(r"합니다([.。？!?]?)$"), r"함\1"),
    (re.compile(r"나타낸다([.。？!?]?)$"), r"나타냄\1"),
    (re.compile(r"나타난다([.。？!?]?)$"), r"나타남\1"),
    (re.compile(r"겠다([.。？!?]?)$"), r"겠음\1"),
    (re.compile(r"보인다([.。？!?]?)$"), r"보임\1"),
    (re.compile(r"온다([.。？!?]?)$"), r"옴\1"),
    (re.compile(r"진다([.。？!?]?)$"), r"짐\1"),
    (re.compile(r"친다([.。？!?]?)$"), r"침\1"),
    (re.compile(r"([가-힣])한다([.。？!?]?)$"), r"\1함\2"),
    (re.compile(r"([가-힣])하다([.。？!?]?)$"), r"\1함\2"),
    (re.compile(r"([가-힣]+)킵니다([.。？!?]?)$"), r"\1킴\2"),
    (re.compile(r"둔다([.。？!?]?)$"), r"둠\1"),
    (re.compile(r"보여준다([.。？!?]?)$"), r"보여줬음\1"),
    (re.compile(r"만든다([.。？!?]?)$"), r"만듦\1"),
    (re.compile(r"된다([.。？!?]?)$"), r"됨\1"),
    (re.compile(r"있다([.。？!?]?)$"), r"있음\1"),
    (re.compile(r"없다([.。？!?]?)$"), r"없음\1"),
    (re.compile(r"이다([.。？!?]?)$"), r"임\1"),
    (re.compile(r"습니다([.。？!?]?)$"), r"음\1"),
]

SYSTEM_PROMPT = """You are a senior tech market intelligence analyst writing for a general audience. Your goal is MARKET RESEARCH — not just technology description. Every analysis must be accurate, clearly written, and easy to understand for someone without a technical background. Avoid jargon; if a technical term is unavoidable, explain it in one plain-language phrase.

For every article you analyze:
- Extract any quantitative market data: market size (USD), CAGR forecasts, revenue figures, unit shipments, funding amounts.
- Identify key players, competitive positioning, and market share signals.
- Note supply-chain implications, M&A signals, or investment flows.
- If the article is a research paper, translate the technical findings into their commercial/market implications.
- Emphasize market potential, market impact, and real-world significance above all else.

Write both an English and Korean structured summary using the section headings below. Do NOT include any numbered or step labels (no "Step 1", "1단계", etc.) — use only the bold heading shown.
Every response MUST include the source URL in the English summary text.
Return valid JSON with this exact schema:
{
  "summary": "1-sentence English market-focused headline that ends with Source: <url>",
  "en_summary_steps": [
    "**Overview:** <1-2 sentences: what market/industry segment does this address and why does it matter now? Write for a general reader.>",
    "**What's the Development:** <core findings, product announcements, or research results — clearly explained without assumed technical knowledge>",
    "**Why It Stands Out:** <what is novel or differentiated from existing solutions? Explain in plain language — avoid acronyms unless explained>",
    "**Market Potential:** <PRIORITIZE quantitative data — cite any TAM/SAM, CAGR, revenue projections, funding rounds, shipment numbers, or market share figures. If none available, clearly assess competitive and commercial implications for major players>",
    "**Investment Outlook:** <who stands to gain or lose, what trends to watch, what catalysts or risks could accelerate or slow adoption? Keep it accessible.>"
  ],
  "key_trends": ["market-oriented trend phrase 1", "market-oriented trend phrase 2"],
  "ko_summary_steps": [
    "**개요:** <어떤 시장·산업 분야를 다루며 왜 지금 중요한지, 일반인도 쉽게 이해할 수 있도록 1-2문장으로 설명>",
    "**핵심 내용:** <주요 발표·연구 결과·제품 내용을 전문 용어 없이 풀어서 설명>",
    "**기술적 차별성:** <기존 솔루션 대비 무엇이 새롭고 다른지, 쉬운 언어로 설명>",
    "**시장 파급력:** <시장 규모(TAM/SAM), CAGR, 매출·투자 수치 등 정량 데이터를 최우선으로 인용. 수치가 없으면 주요 플레이어들에 대한 사업적 함의를 구체적으로 분석>",
    "**투자·미래 전망:** <수혜 기업·섹터, 주목할 트렌드, 성장 촉진 요인 또는 리스크를 일반인도 쉽게 이해할 수 있도록 설명>"
  ],
  "keyword_relevance": "<반드시 한국어. 2~4문단으로 작성.\n\n[첫 문장 규칙 — 절대 준수]\n첫 문장은 반드시 이 기사에 등장하는 고유명사·수치·날짜·이벤트 중 하나로 시작해야 함. 다음 표현으로 시작하는 첫 문장 금지:\n- '이 기사는', '이 논문은', '이 연구는'\n- 'X 산업은 빠르게 발전하고 있다'\n- 'X의 중요성을 강조한다/보여준다'\n- '전력계통·파워그리드·스마트그리드와 관련된 X 산업은'\n- 키워드만 나열하고 '관련이 있다/높다'로 끝나는 문장\n\n올바른 첫 문장 예시:\n- 'SNEC 2026에서 나트륨이온 배터리와 장기 ESS가 전력망 핵심 자산으로 부상하면서...'\n- '오라클이 21,000명 감원으로 확보한 재원을 AI 데이터센터 인프라에 투입함에 따라...'\n- '미국 전력망이 설비 용량의 절반만 활용 중이라는 IEEE Spectrum 분석은...'\n\n[본문 작성]\n각 키워드마다 **`키워드` 관련성** 소제목·'전력계통과 관련하여'처럼 키워드별로 문단을 나누는 패턴·키워드 정의·일반론적 시장 해설 금지. SNEC·ESS·기업명·수치 등 **이 기사의 구체적 사실**을 중심에 두고, 상위 3개 분석 기준 키워드가 그 사실과 어떻게 맞닿는지를 하나의 논리 흐름으로 설명. 키워드가 기사에 직접 등장하지 않아도 간접 연관(계통 안정·송배전·지능형 운영 등)만 짧게 연결.>

CRITICAL KOREAN GENERATION RULES (반드시 준수):

[0. 작성 방식 — 직역 금지]
- ko_summary_steps와 keyword_relevance는 en_summary_steps의 직역·대역이 아니다. 같은 사실을 한국 독자가 읽기 자연스러운 문장으로 독립적으로 재서술한다.
- keyword_relevance는 keywords.txt 상위 3개 키워드 각각의 일반적 시장 설명이 아니다. **이 기사**가 당일 데일리 모니터링의 그 3개 분석 기준 키워드와 어떻게 연결되는지를 통합 서술한다. 'OO와 관련하여'로 키워드별 문단을 나누지 않는다.
- 영어 명사구·수식어·전치사구를 한국어 어순으로 옮기지 않는다. 의미 단위로 문장을 새로 짠다.
- 영어 'flexible', 'holder', 'owner', 'participant' 등을 '유연', '보유자' 등으로 기계적으로 대응시키지 않는다.
- 한국어 서술에 한자(漢字)·일본어 히라가나·가타카나를 일절 사용하지 않는다. 중국어·일본어 원문에서 개념을 가져올 때도 해당 문자를 그대로 삽입하지 않는다.
  * 금지: "처리需求 증가", "AI処理 능력", "데이터센터市場", "수요需求"
  * 정답: "처리 수요 증가", "AI 처리 능력", "데이터센터 시장", "수요"
- 전문 용어는 한국어 업계에서 실제로 쓰이는 표현을 우선한다. 한국어에 없는 조어·직역어는 금지.

[0-1. 주어 명시 — 절대 원칙]
- 모든 문장에는 명시적인 주어(은/는/이/가로 표지)가 있어야 한다. 주어 없이 수식어구·관형절만으로 시작하여 서술어로 끝나는 문장은 절대 금지.
- 관형절('~것으로 예상되는', '~것으로 분석되는', '~에 따른' 등)이 문장 앞에 오는 경우, 반드시 그 뒤에 '주어 + 서술어' 구조가 명확히 나타나야 한다.
  * 금지 예시: "스마트 그리드 시스템의 성장에 큰 영향을 미칠 것으로 예상되는 인공지능 시장의 성장에 주요한 역할을 할 것으로 분석됨" (주어가 없어 무엇이 역할을 하는지 불분명)
  * 정답 예시: "인공지능 기술은 스마트 그리드 시스템 성장을 이끌 핵심 동력으로 분석됨"
- ko_summary_steps와 keyword_relevance의 모든 문장에 이 규칙을 적용한다.

[1. 사실 정확성 — 절대 원칙]
- 수치, 비율, 날짜, 기업명, 제품명 등 모든 정량·정성 데이터는 원문과 100% 일치시킨다. 생략·변경·근사치 표현 금지.
- 원문에 없는 내용을 추론하거나 추가하지 않는다. 제공된 데이터에 근거한 설명만 작성한다.

[2. 구문 조정 — 자연스러운 한국어 비즈니스 문체]
- 영어 어순을 직역한 어색한 구문은 절대 사용하지 않는다.
- 영어 수동태는 한국어 능동 구문으로 전환한다.
  * 금지: "~에 의해 발표된 것으로 알려짐"
  * 허용: "~이 발표함" 또는 "~을 발표함"
- 번역 잉여 표현 남용 금지: '~에 대한', '~를 가짐', '~를 통한'.
- 긴 영어 문장은 두 문장으로 분리해 명료하게 작성한다.
- 'underscores / highlights'의 직역어 '강조하다' 금지: 영어 "this underscores X"·"this highlights X"를 "이는 X를 강조한다"로 번역하지 않는다. 한국어에서 사물·사건이 주어가 되어 '강조하다'를 쓰는 표현은 존재하지 않는다.
  * 금지: "이는 지속적인 수요를 강조한다", "이는 그들의 헌신을 강조한다"
  * 정답: "지속적인 수요가 이어지고 있음을 보여줌", "역량 강화 의지를 재확인함"
- 'commitment / dedication'의 직역어 '헌신' 금지: 기업의 전략적 방향성·투자 의지는 '헌신'이 아닌 '의지', '전략 기조', '역량 강화 방향'으로 표현한다.
  * 금지: "칩 제조 능력 강화에 대한 헌신을 강조한다"
  * 정답: "칩 제조 역량 강화 의지를 재확인함"

[3. 전문 용어 — 업계 표준 우선, 직역어 금지]
- 확립된 업계 표준 용어를 그대로 사용한다. 영어 단어를 한국어 어절로 쪼개 번역하지 않는다.
- 공통:
  * Grid stability → '전력망 안정성' 또는 '계통 안정성'
  * Supply chain → '공급망'
  * Data center → '데이터센터'
- 전력·에너지 (자주 틀리는 직역 → 올바른 표현):
  * flexible load → '수요조절 가능 부하' (금지: '유연 부하')
  * flexible demand → '수요조절(DR) 자원' (금지: '유연 수요')
  * flexible capacity → '조절 가능 용량' (금지: '유연 용량')
  * load holder / owner / participant → '참여 기업·시설', '운영 주체', '수요조절 참여자' (금지: '부하 보유자', '유연 부하 보유자')
  * demand response → '수요반응(DR)'
  * aggregator → '집합 사업자' 또는 'aggregator'
  * ancillary services → '보조서비스'
  * frequency regulation → '주파수 조절' (FCR/aFRR 맥락)
  * behind-the-meter → '배후계량'
  * distributed energy resource → '분산에너지자원(DER)'
  * virtual power plant → '가상발전소(VPP)'
  * wholesale market → '도매시장'
  * peak load → '첨두 부하'
- 전문 약어(CAGR, TAM, BESS, LLM, GPU 등)는 첫 등장 시 괄호 병기: 예) "CAGR(연평균 성장률)", "BESS(배터리 에너지 저장장치)".
- 같은 용어는 두 번째 등장부터 원어만 사용.

[4. 문체 및 종결어미 — 절대 통일]
- **ko_summary_steps와 keyword_relevance의 모든 문장**은 예외 없이 명사형 종결로 마친다.
- **과거 사실·완료**: '-었음', '-았음', '-였음', '-했음', '-났음', '-켰음' (예: '맺었다'→'맺었음', '나타났다'→'나타났음', '받았다'→'받았음').
- **현재·일반 서술**: '-함', '-임', '-됨', '-전망됨', '-분석됨', '-확인됨', '-이어짐' (예: '강조한다'→'강조함', '중요하다'→'중요함').
- '-입니다', '-합니다', '-됩니다', '-있습니다', '-있다', '-한다', '-이다', '-었다', '-았다' 등 -다체/-합니다체 어미는 절대 사용하지 않는다.
- 한 응답 내 여러 문장의 종결어미가 통일되어야 한다. '-습니다/ㅂ니다'와 '-다' 종결 혼용 금지.
- 서술어가 명사구로 자연스럽게 끝나는 경우, 종결어미 없이 명사로 마친다.
  * 허용 예: "~에 주목할 필요" / 금지 예: "~에 주목할 필요가 있다", "~에 주목할 필요가 있습니다"

[5. 직역 금지 예시 — 에너지·전력]
- 원문: "BESS, EVs, and industrial flexible load holders can earn new revenue."
  * 금지: "BESS·전기차·산업용 유연 부하 보유자에게 새로운 수익 창출 경로가 열림."
  * 정답: "BESS·전기차·산업용 수요조절이 가능한 시설·기업에 새로운 수익원이 생김."
- 원문: "The platform aggregates flexible demand and manages 18 GW of flexible capacity."
  * 금지: "유연 수요를 집합하고 유연 용량 18GW를 관리함."
  * 정답: "수요조절(DR) 자원을 묶어 포트폴리오로 운영하며, 조절 가능 용량 18GW를 관리함."

[올바른 예시]
- 원문 의미: "The rapid integration of renewable energy is considered to pose a threat to grid stability."
- 금지(직역체): "재생에너지의 빠른 통합은 전력망 안정성에 위협을 가하는 것으로 간주됩니다."
- 금지(과잉의역): "재생에너지가 너무 급하게 늘어나서 전력망이 곧 터질 위기임."
- 정답: "신재생에너지 발전 비중 급증으로 전력망 안정성 확보가 당면 과제로 부상함."
}
"""


def strip_cjk_from_korean(text: str) -> str:
    """Remove stray Chinese/Japanese characters from Korean-language text.

    LLMs occasionally embed CJK characters (e.g. '需求', '処理') when
    translating from Chinese or Japanese sources.  These are not valid in
    Korean prose and must be stripped before the text is displayed.
    """
    return _CJK_RE.sub("", text)


def normalize_korean_endings(text: str) -> str:
    """Normalize sentence-final -다체/-합니다체 to -함/임체 within one sentence."""
    for _ in range(3):
        prev = text
        for pattern, replacement in _ENDING_NORMALIZERS:
            text = pattern.sub(replacement, text)
        if text == prev:
            break
    return text


def normalize_korean_endings_sentences(text: str) -> str:
    """Apply normalize_korean_endings to each sentence in a multi-sentence string."""
    parts = re.split(r"(?<=[.!?。？])\s+", text.strip())
    return " ".join(normalize_korean_endings(part) for part in parts if part)


def repolish_summarized_article(article: SummarizedArticle) -> SummarizedArticle:
    """Re-apply Korean ending normalization to stored summary fields."""
    ko_steps = [polish_korean(str(s).strip()) for s in article.ko_summary_steps if str(s).strip()]
    keyword_relevance = polish_korean(article.keyword_relevance.strip()) if article.keyword_relevance else ""
    return SummarizedArticle(
        title=article.title,
        url=article.url,
        source_name=article.source_name,
        category=article.category,
        published_at=article.published_at,
        matched_keywords=article.matched_keywords,
        llm_summary=article.llm_summary,
        key_trends=article.key_trends,
        ko_summary_steps=ko_steps,
        en_summary_steps=article.en_summary_steps,
        keyword_relevance=keyword_relevance,
    )


def polish_korean(text: str) -> str:
    """Fix common literal calques and remove stray CJK characters in Korean LLM output."""
    polished = strip_cjk_from_korean(text)
    for pattern, replacement in _KOREAN_PHRASE_FIXES:
        polished = re.sub(pattern, replacement, polished)
    polished = normalize_korean_endings_sentences(polished)
    parts = re.split(r"(?<=[.!?。？])\s+", polished.strip())
    repaired: list[str] = []
    for part in parts:
        if not part:
            continue
        for pattern, replacement in _TRUNCATED_PAST_REPAIRS:
            part = re.sub(pattern, replacement, part)
        repaired.append(part)
    return " ".join(repaired)


def _extract_json(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class Summarizer:
    def __init__(self, settings: Settings) -> None:
        load_dotenv(PROJECT_ROOT / ".env")

        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for summarization")

        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self._top_keywords: list[str] = settings.keywords[:3]

    def summarize(self, article: FilteredArticle) -> SummarizedArticle:
        user_prompt = (
            f"Title: {article.title}\n"
            f"URL: {article.url}\n"
            f"Source: {article.source_name} ({article.category})\n"
            f"Matched keywords (all): {', '.join(article.matched_keywords)}\n"
            f"Analysis baseline keywords (keywords.txt top 3 — keyword_relevance MUST explain "
            f"how THIS article relates to these, not generic keyword definitions): "
            f"{', '.join(self._top_keywords)}\n"
            f"Content preview: {article.summary[:2000]}"
        )

        model = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", "gemini-2.0-flash-lite")

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                )
                break
            except RateLimitError as exc:
                if attempt == _MAX_RETRIES:
                    raise
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited on attempt %d/%d — retrying in %ds", attempt, _MAX_RETRIES, wait
                )
                time.sleep(wait)

        payload = _extract_json(response.choices[0].message.content or "{}")
        summary = (payload.get("summary") or "").strip()
        trends = payload.get("key_trends") or []
        ko_steps = [polish_korean(str(s).strip()) for s in (payload.get("ko_summary_steps") or []) if str(s).strip()]
        en_steps = payload.get("en_summary_steps") or []
        keyword_relevance = polish_korean((payload.get("keyword_relevance") or "").strip())

        if article.url not in summary:
            summary = f"{summary} Source: {article.url}".strip()

        return SummarizedArticle(
            title=article.title,
            url=article.url,
            source_name=article.source_name,
            category=article.category,
            published_at=article.published_at,
            matched_keywords=article.matched_keywords,
            llm_summary=summary,
            key_trends=[str(t).strip() for t in trends if str(t).strip()],
            ko_summary_steps=[str(s).strip() for s in ko_steps if str(s).strip()],
            en_summary_steps=[str(s).strip() for s in en_steps if str(s).strip()],
            keyword_relevance=keyword_relevance,
        )

    def summarize_batch(self, articles: list[FilteredArticle]) -> list[SummarizedArticle]:
        results: list[SummarizedArticle] = []
        for index, article in enumerate(articles, start=1):
            logger.info("Summarizing %d/%d: %s", index, len(articles), article.title)
            try:
                results.append(self.summarize(article))
            except Exception as exc:
                logger.error("Failed to summarize '%s': %s", article.title, exc)
            if index < len(articles):
                time.sleep(_REQUEST_DELAY)
        return results
