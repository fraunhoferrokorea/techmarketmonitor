"""
One-off script: generate sample reports reflecting all current prompt configurations.

  - Daily report  : 2026-06-21 (output/daily/daily_2026-06-21.md)
  - Monthly report: 2026-05    (output/monthly/tech-market-report-2026-05.docx + -ko.docx)

Run:
    python generate_sample_reports.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("REPORTS_OUTPUT_DIR", "output/monthly")
sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_settings
from src.daily_report import save_daily_report
from src.models import SummarizedArticle
from src.report_generator import ReportGenerator

# ─────────────────────────────────────────────────────────────────────────────
# June 21 daily sample articles
# All five en_summary_steps / ko_summary_steps follow the SYSTEM_PROMPT schema.
# ─────────────────────────────────────────────────────────────────────────────

def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


DAILY_ARTICLES: list[SummarizedArticle] = [
    SummarizedArticle(
        title="South Korea targets 100 GW of offshore wind to power next-gen AI data centers",
        url="https://www.energy.go.kr/cms/en/2026/06/ai-offshore-wind-100gw",
        source_name="MOTIE",
        category="energy",
        published_at=_dt("2026-06-21T02:00:00"),
        matched_keywords=["power grid", "data center", "smart grid", "AI infrastructure"],
        llm_summary=(
            "South Korea's Ministry of Trade, Industry and Energy announced a revised 2030 offshore "
            "wind roadmap targeting 100 GW of capacity, explicitly linking the expansion to "
            "AI data center power demand projected to triple by 2030. "
            "Source: https://www.energy.go.kr/cms/en/2026/06/ai-offshore-wind-100gw"
        ),
        en_summary_steps=[
            "**Overview:** South Korea is confronting a looming electricity deficit driven by "
            "exponential AI workload growth, prompting its government to fast-track the world's "
            "most ambitious offshore wind programme. The country's AI data center power demand "
            "is projected to triple to roughly 45 TWh/year by 2030.",
            "**What's the Development:** The Ministry of Trade, Industry and Energy (MOTIE) "
            "revised its 2030 Renewable Energy Plan to target 100 GW of offshore wind capacity — "
            "up from the previous 30 GW goal. The acceleration is driven by a formal request from "
            "five hyperscalers (Microsoft, Google, AWS, Meta, Kakao) that plan to invest $60 B "
            "in Korean data center infrastructure through 2030.",
            "**Why It Stands Out:** Unlike prior renewable plans shaped by climate commitments, "
            "this revision is explicitly demand-pull: AI infrastructure operators have signed "
            "preliminary power purchase agreements (PPAs) directly with offshore wind developers, "
            "bypassing the state utility (KEPCO) in a first for Korean energy policy.",
            "**Market Potential:** The 100 GW build-out implies roughly $180 B in total project "
            "investment. CAGR for Korean offshore wind components (towers, foundations, cables) "
            "is estimated at 28% through 2030. Korean shipbuilders (HD Hyundai, Samsung Heavy) "
            "are positioned to capture installation vessel contracts worth an estimated $12 B.",
            "**Investment Outlook:** Korean steel, cable (LS Cable), and electrical equipment "
            "(Hyosung) suppliers stand to benefit most. Grid integration risk remains — KEPCO's "
            "transmission build-out is 3–4 years behind the generation timeline. Investors should "
            "monitor the Transmission Act amendment scheduled for Q3 2026.",
        ],
        key_trends=[
            "AI-driven power demand reshaping national energy policy",
            "Hyperscaler direct PPAs bypassing state utilities",
            "Offshore wind as AI infrastructure enabler",
        ],
        ko_summary_steps=[
            "**개요:** 한국은 AI 워크로드 폭증으로 인한 전력 부족에 대응하기 위해 세계 최대 규모의 "
            "해상풍력 확충 계획을 추진 중임. 국내 AI 데이터센터 전력 수요는 2030년까지 약 45TWh/년으로 "
            "3배 증가할 전망임.",
            "**핵심 내용:** 산업통상자원부(MOTIE)가 2030 재생에너지 계획을 개정해 해상풍력 목표를 "
            "기존 30GW에서 100GW로 상향 조정함. 마이크로소프트·구글·AWS·메타·카카오 등 하이퍼스케일러 "
            "5개사가 2030년까지 600억 달러 규모의 국내 데이터센터 투자 계획을 제출한 것이 직접적 배경임.",
            "**기술적 차별성:** 기존 기후 정책 중심의 재생에너지 확충과 달리, 이번 계획은 AI 인프라 수요가 "
            "직접 견인하는 구조임. 하이퍼스케일러들이 한국전력(KEPCO)을 거치지 않고 해상풍력 개발사와 "
            "직접 전력구매계약(PPA)을 체결하는 방식은 국내 에너지 정책 사상 최초 사례임.",
            "**시장 파급력:** 100GW 개발에 소요될 총 프로젝트 투자 규모는 약 1,800억 달러로 추산됨. "
            "국내 해상풍력 부품(타워·기초·케이블) 시장의 CAGR(연평균 성장률)은 2030년까지 28%로 예측됨. "
            "HD현대·삼성중공업 등 국내 조선사는 약 120억 달러 규모의 설치선(installation vessel) 계약 "
            "수주 기회를 확보할 것으로 분석됨.",
            "**투자·미래 전망:** 국내 철강·케이블(LS전선)·전력기기(효성) 공급망이 최대 수혜 대상임. "
            "반면 KEPCO의 송전망 확충 일정이 발전 타임라인보다 3~4년 늦어 계통 통합 리스크가 잠재함. "
            "2026년 3분기 예정된 송전법 개정 동향을 면밀히 주시할 필요가 있음.",
        ],
        keyword_relevance=(
            "**`power grid` 관련성**\n\n"
            "전력망(power grid)은 발전소에서 생산된 전기를 가정·기업·데이터센터까지 안정적으로 "
            "전달하는 핵심 인프라임. AI 데이터센터의 전력 수요가 급증하면서 기존 전력망이 감당하기 "
            "어려운 부하가 발생하고 있음. 한국의 100GW 해상풍력 계획은 전력 공급원을 대폭 확대하는 "
            "동시에 송·배전망 고도화를 병행하지 않으면 오히려 계통 불안정을 야기할 수 있음.\n\n"
            "이 기사는 AI 인프라 확장이 국가 전력망 정책을 직접 바꾼 최초 사례로서 투자자와 "
            "인프라 기업에 중요한 시그널임. 전력망 현대화 관련 기업(송전·변전 장비, 에너지 소프트웨어) "
            "에 대한 관심이 높아질 것으로 전망됨.\n\n"
            "**`data center` 관련성**\n\n"
            "데이터센터는 AI 모델 학습과 추론을 수행하는 대형 컴퓨팅 시설임. 단일 AI 학습 클러스터가 "
            "수백 메가와트(MW)의 전력을 소비하며, 한국 내 하이퍼스케일러 5개사가 2030년까지 60억 "
            "달러를 투자할 계획임. 이는 단순한 IT 투자를 넘어 국가 에너지 인프라 전략과 직결됨.\n\n"
            "데이터센터 입지 결정 요인으로 '전력 확보 가능성'이 부지·노동력보다 우선시되는 추세가 "
            "확인됨. 재생에너지 직접 PPA가 가능한 지역과 기업에 투자 프리미엄이 붙을 전망임."
        ),
    ),
    SummarizedArticle(
        title="KEPCO unveils $14B smart grid modernization plan for 2026–2030",
        url="https://home.kepco.co.kr/kepco/EN/news/2026/smartgrid-14b",
        source_name="KEPCO",
        category="energy",
        published_at=_dt("2026-06-21T04:30:00"),
        matched_keywords=["smart grid", "grid modernization", "energy management system", "power grid"],
        llm_summary=(
            "Korea Electric Power Corporation (KEPCO) released a five-year ₩19 T ($14 B) "
            "smart grid investment plan covering advanced metering, digital substations, "
            "real-time grid analytics, and distributed energy resource management systems (DERMS). "
            "Source: https://home.kepco.co.kr/kepco/EN/news/2026/smartgrid-14b"
        ),
        en_summary_steps=[
            "**Overview:** South Korea's state utility KEPCO launched its most aggressive "
            "grid modernisation push in two decades, earmarking $14 B over five years as AI data "
            "centers and renewable energy sources strain a transmission network built for the "
            "nuclear-and-coal era.",
            "**What's the Development:** The plan covers four pillars: (1) 12 million advanced "
            "metering infrastructure (AMI) upgrades; (2) full digitalisation of 4,800 substations "
            "using IEC 61850 protocol; (3) a national DERMS platform to orchestrate 15 GW of "
            "distributed solar and BESS; (4) an AI-powered situational awareness center capable "
            "of 100 ms fault isolation.",
            "**Why It Stands Out:** KEPCO's DERMS platform will be the first national-scale "
            "implementation in Asia to integrate rooftop solar, EVs, and commercial BESS under "
            "a single control layer — enabling virtual power plant (VPP) aggregation without "
            "third-party intermediaries.",
            "**Market Potential:** The $14 B spend translates to an estimated $3.5 B in software "
            "and hardware procurement. Korean conglomerates (LS Electric, Hyosung Heavy, "
            "HD Hyundai Electric) are expected to capture 60–70% of the domestic contract value. "
            "Export potential for the DERMS platform is estimated at $800 M over 5 years in "
            "Southeast Asian markets.",
            "**Investment Outlook:** KEPCO bonds may offer yield compression as credit outlook "
            "improves with government backing. Pure-play smart grid software vendors and "
            "AMI hardware suppliers are the primary equity beneficiaries. The key risk is "
            "political: KEPCO's chronic debt (₩200 T) may slow capital deployment.",
        ],
        key_trends=[
            "National DERMS rollout as VPP enabler",
            "Digital substation standard IEC 61850 adoption accelerating",
            "AI-powered fault isolation cutting outage duration",
        ],
        ko_summary_steps=[
            "**개요:** 한국전력공사(KEPCO)가 핵발전·석탄 시대에 구축된 기존 송전망의 한계를 극복하고 "
            "AI 데이터센터·재생에너지 급증에 대응하기 위해 20년 만에 최대 규모인 19조 원($140억) "
            "스마트그리드 투자 계획을 발표함.",
            "**핵심 내용:** 4대 투자 축은 ①AMI(지능형 계량 인프라) 1,200만 개 교체, "
            "②IEC 61850 프로토콜 기반 변전소 4,800개소 완전 디지털화, "
            "③분산에너지자원관리시스템(DERMS)을 통한 분산 태양광·BESS 15GW 통합 운영, "
            "④100ms 고장 격리 AI 상황인식 센터 구축임.",
            "**기술적 차별성:** KEPCO의 DERMS 플랫폼은 아시아 최초로 옥상 태양광·전기차·상업용 "
            "BESS를 제3자 중개 없이 단일 제어 레이어에서 통합 운영하는 국가급 구현 사례가 될 것임. "
            "이는 사실상 국가 단위 가상발전소(VPP) 인프라를 의미함.",
            "**시장 파급력:** 14조 원 규모 구매에서 소프트웨어·하드웨어 조달액은 약 3.5조 원으로 추산됨. "
            "LS일렉트릭·효성중공업·HD현대일렉트릭 등 국내 대기업이 국내 계약의 60~70%를 수주할 전망임. "
            "DERMS 플랫폼의 동남아 수출 잠재력은 5년간 8억 달러로 평가됨.",
            "**투자·미래 전망:** 정부 신용 보강으로 KEPCO 채권 수익률 스프레드 축소가 기대됨. "
            "스마트그리드 소프트웨어 전문 기업과 AMI 하드웨어 공급사가 주요 수혜 대상임. "
            "핵심 리스크는 KEPCO의 만성적 부채(약 200조 원)로 인한 자본 배포 지연 가능성임.",
        ],
        keyword_relevance=(
            "**`smart grid` 관련성**\n\n"
            "스마트그리드는 전력망에 디지털 통신·제어 기술을 접목해 전기를 더 효율적으로 생산·전달·소비하는 "
            "시스템임. 일반 가정에서는 스마트 전기계량기(AMI)로 실시간 전기요금을 확인하고 전력 피크 시간대 "
            "사용을 줄여 요금을 절약하는 형태로 직결됨.\n\n"
            "KEPCO의 19조 원 투자는 한국 스마트그리드 장비·소프트웨어 시장에 구체적이고 대규모 수요를 "
            "창출함. 특히 DERMS 플랫폼 구축은 수많은 분산 전원을 하나의 '가상발전소'처럼 운용할 수 있게 해 "
            "재생에너지의 불규칙한 발전 패턴을 안정화하는 핵심 인프라가 됨.\n\n"
            "**`energy management system` 관련성**\n\n"
            "에너지 관리 시스템(EMS)은 건물·공장·전력망 전반에서 에너지 사용을 실시간으로 측정·분석·최적화하는 "
            "소프트웨어임. KEPCO가 구축하는 AI 상황인식 센터와 DERMS는 국가 단위 초대형 EMS라 할 수 있음.\n\n"
            "이 기사가 갖는 시장적 의미는 EMS 시장의 주요 고객 풀이 기업·건물 단위에서 국가 전력망 운영자로 "
            "확대된다는 점임. EMS 소프트웨어 기업(ABB, Siemens Energy, LS일렉트릭 등)에 수조 원 규모의 "
            "공공 조달 기회가 열림. 투자자는 IEC 61850·DERMS 구현 역량을 보유한 전력 자동화 기업을 주목할 것."
        ),
    ),
    SummarizedArticle(
        title="Global BESS market crosses $50B in annual deployments — Korea leads Asia-Pacific",
        url="https://www.iea.org/reports/bess-market-2026-q2-update",
        source_name="IEA",
        category="energy",
        published_at=_dt("2026-06-21T06:00:00"),
        matched_keywords=["BESS", "battery energy storage", "grid stability", "market size", "market forecast"],
        llm_summary=(
            "The IEA's Q2 2026 update shows global grid-scale BESS deployments surpassed $50 B "
            "in annualised revenue for the first time, with Asia-Pacific — led by South Korea and "
            "China — accounting for 47% of new capacity. CAGR through 2030 is forecast at 31%. "
            "Source: https://www.iea.org/reports/bess-market-2026-q2-update"
        ),
        en_summary_steps=[
            "**Overview:** Battery energy storage systems (BESS) have become the fastest-growing "
            "segment of the global energy infrastructure market, driven by the parallel booms in "
            "renewable energy and AI data center power demand. For the first time, annual "
            "deployment revenue has crossed the $50 B threshold, signaling the technology's "
            "transition from pilot projects to core grid infrastructure.",
            "**What's the Development:** IEA's Q2 2026 update records 42 GWh of grid-scale BESS "
            "deployed in H1 2026, a 67% increase year-on-year. South Korea deployed 8.2 GWh — "
            "the largest single-country figure outside China — primarily to stabilize the grid "
            "as solar penetration exceeded 22% of peak generation for the first time. "
            "Lithium iron phosphate (LFP) chemistry now accounts for 78% of new deployments "
            "due to improved cycle life and lower fire risk.",
            "**Why It Stands Out:** Korea's outsized deployment rate reflects a regulatory "
            "mandate (Renewable Portfolio Standard + BESS mandatory co-location requirement) "
            "that forces every utility-scale solar project above 100 MW to pair at least "
            "2 hours of BESS storage — a policy template being studied by Japan and Taiwan.",
            "**Market Potential:** Global BESS TAM (전체 시장 규모) is forecast to reach $180 B "
            "by 2030 at a CAGR of 31%. LFP cell prices fell to $58/kWh in Q1 2026, a new record, "
            "improving project economics to the point where BESS is now competitive with peaker "
            "gas plants in most G20 markets. Samsung SDI and LG Energy Solution combined hold "
            "a 28% global market share in grid-scale BESS cells.",
            "**Investment Outlook:** Korean battery manufacturers and system integrators are "
            "prime beneficiaries. The key watch item is whether the US IRA BESS manufacturing "
            "credit (45X) will be extended post-2027, which would drive further Korean cell "
            "factory investment in North America. Risks include LFP price commoditization "
            "pressuring margins.",
        ],
        key_trends=[
            "BESS crosses $50B annual deployment milestone",
            "LFP chemistry dominance reshaping supply chain",
            "BESS mandatory co-location policy spreading across Asia",
        ],
        ko_summary_steps=[
            "**개요:** 배터리 에너지 저장 장치(BESS)는 재생에너지와 AI 데이터센터 전력 수요 동반 급증에 힘입어 "
            "글로벌 에너지 인프라 시장에서 가장 빠르게 성장하는 분야로 자리 잡음. 연간 배포 매출이 처음으로 "
            "500억 달러를 돌파해 시범사업 단계에서 핵심 전력망 인프라로의 전환이 확인됨.",
            "**핵심 내용:** IEA Q2 2026 보고서에 따르면 2026년 상반기 그리드 스케일 BESS 배포량은 42GWh로 "
            "전년 동기 대비 67% 증가했음. 한국은 중국 외 단일 국가 최대치인 8.2GWh를 배포했으며, "
            "이는 태양광 발전이 최초로 피크 발전량의 22%를 초과하면서 계통 안정화 목적으로 집중 투입된 결과임. "
            "LFP(리튬인산철) 화학계는 우수한 사이클 수명과 낮은 화재 위험성 덕분에 신규 배포의 78%를 차지함.",
            "**기술적 차별성:** 한국의 높은 배포율은 100MW 이상 유틸리티 태양광 사업에 최소 2시간 BESS 병설을 "
            "의무화하는 규제(신재생에너지 공급의무화(RPS) + BESS 병설 요건)에 기인함. "
            "이 정책 모델은 일본과 대만이 벤치마킹 중임.",
            "**시장 파급력:** 글로벌 BESS TAM(전체 시장 규모)은 2030년까지 CAGR 31%로 1,800억 달러에 이를 것으로 "
            "전망됨. LFP 셀 가격은 2026년 1분기 기준 kWh당 58달러(신저가)까지 하락해 대부분의 G20 국가에서 "
            "첨두 발전용 가스 발전기와 경쟁 가능한 수준에 도달함. 삼성SDI와 LG에너지솔루션이 그리드 스케일 "
            "BESS 셀 시장에서 합산 28%의 글로벌 점유율을 보유함.",
            "**투자·미래 전망:** 국내 배터리 제조사와 시스템 통합 기업이 최대 수혜 대상임. "
            "2027년 이후 미국 IRA BESS 제조 세액공제(45X) 연장 여부가 핵심 변수로, 연장 시 "
            "국내 기업들의 북미 셀 공장 투자가 가속화될 것으로 분석됨. "
            "LFP 가격 상품화로 인한 마진 압박이 주요 하방 리스크임.",
        ],
        keyword_relevance=(
            "**`BESS` 관련성**\n\n"
            "BESS(Battery Energy Storage System, 배터리 에너지 저장 장치)는 태양광·풍력으로 생산된 전기를 "
            "대형 배터리에 저장해 두었다가 전력이 필요한 시간에 방전하는 시스템임. 가정용 스마트폰 보조 배터리의 "
            "수십만 배 규모로, 전력망의 '완충 장치' 역할을 함.\n\n"
            "이 기사는 BESS 시장이 연간 500억 달러를 넘어선 '규모의 경제' 전환점에 도달했음을 보여줌. "
            "한국이 아시아·태평양 최대 배포국이 된 것은 삼성SDI·LG에너지솔루션·SK온 등 국내 배터리 기업의 "
            "글로벌 공급망 경쟁력 강화와 직결됨.\n\n"
            "**`grid stability` 관련성**\n\n"
            "계통 안정성(grid stability)은 전력망이 수요와 공급의 균형을 유지해 정전 없이 안정적으로 운영되는 "
            "상태를 의미함. 재생에너지는 날씨에 따라 발전량이 불규칙하기 때문에 계통 안정성이 핵심 과제가 됨.\n\n"
            "BESS가 계통 안정성에 기여하는 방식은 두 가지임: ①재생에너지 출력 변동 흡수(주파수 조정), "
            "②피크 수요 시간대 방전(첨두 부하 완화). 한국 태양광 발전 비중이 22%를 초과한 시점에서 "
            "8.2GWh 배포는 계통 붕괴 방지를 위한 필수 투자로 평가됨."
        ),
    ),
    SummarizedArticle(
        title="AI grid orchestration startup GridMind raises $320M Series C at $2.1B valuation",
        url="https://www.ft.com/content/gridmind-series-c-ai-grid-2026",
        source_name="Financial Times Tech",
        category="enterprise",
        published_at=_dt("2026-06-21T08:00:00"),
        matched_keywords=["startup funding", "M&A", "smart grid", "virtual power plant", "demand response"],
        llm_summary=(
            "GridMind, an AI-native grid orchestration platform, closed a $320 M Series C at a "
            "$2.1 B valuation, led by Brookfield and BlackRock. The platform aggregates VPPs, "
            "demand response, and real-time wholesale market bidding across 8 countries. "
            "Source: https://www.ft.com/content/gridmind-series-c-ai-grid-2026"
        ),
        en_summary_steps=[
            "**Overview:** The rapid electrification of AI data centers and transportation is "
            "creating a new category of infrastructure software: AI-native grid orchestration "
            "platforms that manage millions of distributed assets in real time. GridMind's "
            "$320 M raise is the largest single VC round in energy software to date.",
            "**What's the Development:** GridMind's platform aggregates flexible demand "
            "(EV chargers, industrial loads, commercial HVAC) and distributed supply (rooftop "
            "solar, behind-the-meter BESS) into VPP portfolios, then bids them into day-ahead "
            "and real-time wholesale electricity markets across the US, UK, Germany, Australia, "
            "South Korea, Japan, Taiwan, and Singapore. The platform currently manages 18 GW "
            "of flexible capacity and 2.4 million enrolled assets.",
            "**Why It Stands Out:** Unlike legacy demand-response providers, GridMind uses a "
            "reinforcement learning model trained on 5 years of grid data to forecast 15-minute "
            "market price intervals with 94% accuracy, enabling automated bidding strategies that "
            "consistently outperform manual dispatch by 22%.",
            "**Market Potential:** GridMind's ARR grew 4.2× year-on-year to $85 M, implying a "
            "24.7× ARR valuation multiple — at the high end of enterprise software comps. "
            "The addressable market for AI grid orchestration software is estimated at $45 B "
            "by 2030 (Gartner, 2026). Brookfield and BlackRock's participation signals that "
            "infrastructure capital is treating grid software as an asset class.",
            "**Investment Outlook:** GridMind's M&A pipeline includes potential acquisitions of "
            "demand response operators in Japan and South Korea, which could expand its "
            "Asia-Pacific footprint significantly. The risk is regulatory fragmentation: "
            "each market has different rules for VPP market participation, increasing "
            "compliance complexity and customer acquisition costs.",
        ],
        key_trends=[
            "AI grid orchestration achieving institutional-grade valuation",
            "Reinforcement learning for real-time market bidding",
            "Infrastructure capital treating grid software as asset class",
        ],
        ko_summary_steps=[
            "**개요:** AI 데이터센터·전기차 충전의 급속한 확산으로 수백만 개의 분산 자원을 실시간 관리하는 "
            "'AI 기반 전력망 오케스트레이션 플랫폼'이라는 새로운 인프라 소프트웨어 카테고리가 형성됨. "
            "GridMind의 3억 2,000만 달러 조달은 에너지 소프트웨어 분야 단일 VC 투자로 역대 최대 규모임.",
            "**핵심 내용:** GridMind 플랫폼은 수요조절(DR) 자원(EV 충전기, 산업용 부하, 상업용 HVAC)과 분산 공급원 "
            "(옥상 태양광, 배후계량 BESS)을 VPP 포트폴리오로 집합화한 뒤, 미국·영국·독일·호주·한국·일본·대만·싱가포르 "
            "등 8개국 전력 도매시장에 전일 및 실시간으로 입찰함. 현재 관리 조절 가능 용량 18GW, 등록 자산 240만 개임.",
            "**기술적 차별성:** 기존 수요반응(DR) 사업자와 달리, GridMind는 5년치 전력망 데이터로 훈련된 "
            "강화학습 모델로 15분 단위 시장가격 구간을 94% 정확도로 예측함. "
            "이를 통한 자동 입찰 전략이 수동 디스패치 대비 22% 높은 수익을 일관되게 창출함.",
            "**시장 파급력:** GridMind의 ARR(연간 반복 매출)이 전년 대비 4.2배 증가해 8,500만 달러에 달하며, "
            "이는 21억 달러 기업가치의 ARR 배수 24.7배에 해당함(엔터프라이즈 소프트웨어 상위권 수준). "
            "AI 전력망 오케스트레이션 소프트웨어의 TAM(전체 시장 규모)은 2030년 450억 달러로 추산됨(Gartner, 2026). "
            "브룩필드·블랙록의 참여는 인프라 자본이 전력망 소프트웨어를 독립 자산 군으로 인식하기 시작했음을 시사함.",
            "**투자·미래 전망:** GridMind는 일본·한국의 수요반응 운영사 인수를 통한 아시아·태평양 거점 확대를 "
            "검토 중임. 핵심 리스크는 시장별 VPP 참여 규정의 파편화로 인한 컴플라이언스 비용 및 고객 획득 "
            "비용 상승 가능성임.",
        ],
        keyword_relevance=(
            "**`startup funding` 관련성**\n\n"
            "스타트업 투자(startup funding)는 기술 혁신 기업이 성장 자금을 조달하는 방식으로, 투자 규모는 "
            "해당 분야의 시장 성숙도와 기대 수익성을 반영함. 3억 2,000만 달러는 에너지 소프트웨어 분야에서 "
            "단일 VC 라운드 기준 역대 최대로, 전력망 소프트웨어 시장이 성숙 단계에 진입했음을 시사함.\n\n"
            "브룩필드·블랙록 등 글로벌 대형 인프라 펀드의 참여는 단순한 VC 투자를 넘어 전력망 소프트웨어가 "
            "'인프라 자산'으로 분류되기 시작했음을 의미함. 이는 향후 그리드 소프트웨어 기업들의 M&A와 IPO "
            "밸류에이션에 상향 압력을 가할 것으로 분석됨.\n\n"
            "**`virtual power plant` 관련성**\n\n"
            "가상발전소(VPP)는 실제 발전소가 아니라 수많은 소규모 분산 자원(태양광 패널, 배터리, 전기차, "
            "에어컨 등)을 소프트웨어로 묶어 하나의 '발전소처럼' 운용하는 개념임. "
            "GridMind가 18GW를 관리한다는 것은 중형 원자력 발전소 18기에 해당하는 조절 가능 용량을 디지털로 "
            "제어한다는 의미임.\n\n"
            "이 뉴스는 VPP 시장이 실증 단계를 넘어 수십억 달러 규모의 투자가 이뤄지는 상업적 인프라로 "
            "전환되고 있음을 확인해 줌. 한국 전력 규제 당국이 VPP 관련 제도 정비를 서두를 필요성을 시사함."
        ),
    ),
    SummarizedArticle(
        title="Frequency regulation market opens to private aggregators in Korea — KEPCO mandate ends",
        url="https://www.kea.kr/news/2026/frequency-regulation-private-aggregator",
        source_name="Korea Energy Agency",
        category="energy",
        published_at=_dt("2026-06-21T09:30:00"),
        matched_keywords=["frequency regulation", "demand response", "power system", "smart grid", "VPP"],
        llm_summary=(
            "Korea's Ministry of Trade, Industry and Energy issued new rules allowing private "
            "demand response aggregators to participate directly in frequency regulation markets "
            "starting October 2026, ending KEPCO's exclusive role. "
            "Source: https://www.kea.kr/news/2026/frequency-regulation-private-aggregator"
        ),
        en_summary_steps=[
            "**Overview:** South Korea's electricity market is undergoing a structural reform "
            "that will, for the first time, allow private companies to earn revenue by helping "
            "to keep the electric grid frequency stable — a function previously reserved for "
            "state utility KEPCO alone. This opens a new revenue stream for owners of BESS, "
            "EVs, and industrial flexible loads.",
            "**What's the Development:** Effective October 2026, private demand response "
            "aggregators with a minimum portfolio of 5 MW and certified metering infrastructure "
            "can register with Korea Power Exchange (KPX) to bid into the Frequency Containment "
            "Reserve (FCR) and Automatic Frequency Restoration Reserve (aFRR) markets. "
            "KEPCO will retain system operator status but lose its monopoly on frequency "
            "regulation dispatch.",
            "**Why It Stands Out:** This is the first major deregulation of Korea's ancillary "
            "services market in 15 years. In comparable markets (UK, Germany, Australia), "
            "private aggregator entry reduced FCR market clearing prices by 15–30% within "
            "two years, dramatically improving economics for BESS owners.",
            "**Market Potential:** Korea's annual FCR and aFRR market value is approximately "
            "₩1.2 T ($870 M). If private aggregators capture 30% of this within 3 years "
            "(consistent with UK Balancing Mechanism experience), that implies $260 M/year "
            "in new revenue opportunities. BESS systems co-located with industrial facilities "
            "stand to benefit most given their rapid response capability.",
            "**Investment Outlook:** Korean BESS integrators (Samsung SDI ESS, LG CNS, Doosan "
            "Enerbility) and energy management software providers are direct beneficiaries. "
            "For international VPP platforms like GridMind, this deregulation opens the "
            "Korean market at an attractive entry point. Regulatory implementation risk is "
            "moderate — KPX's IT systems require an upgrade to handle distributed bidding.",
        ],
        key_trends=[
            "Korean ancillary services market deregulation",
            "Private aggregators entering frequency regulation for first time",
            "BESS economics improving through new revenue stacking",
        ],
        ko_summary_steps=[
            "**개요:** 한국 전력시장이 구조적 개혁 단계에 진입함. 2026년 10월부터 민간 수요반응 사업자가 "
            "주파수 조절 보조서비스 시장에 직접 참여할 수 있게 되어, BESS·전기차·산업용 수요조절이 가능한 시설·기업에 "
            "새로운 수익원이 생김.",
            "**핵심 내용:** 2026년 10월부터 최소 5MW 포트폴리오와 인증 계량 인프라를 갖춘 민간 수요반응 "
            "집합체가 한국전력거래소(KPX)에 등록해 주파수 유지 예비력(FCR)과 자동 주파수 복구 예비력(aFRR) "
            "시장에 입찰할 수 있음. KEPCO는 계통 운영자 지위를 유지하나 주파수 조정 독점권을 상실함.",
            "**기술적 차별성:** 한국 보조서비스 시장의 15년 만에 첫 규제 완화임. 영국·독일·호주의 유사 사례에서 "
            "민간 사업자 진입 후 2년 내 FCR 시장 정산 가격이 15~30% 하락하며 BESS 수익성이 크게 개선됨.",
            "**시장 파급력:** 한국 FCR·aFRR 시장 연간 규모는 약 1.2조 원(8억 7,000만 달러)임. "
            "영국 밸런싱 메커니즘 경험 참고 시 3년 내 민간 사업자 점유율 30% 달성 가정 시 "
            "연 2,600억 원($1억 9,000만 달러)의 신규 수익 기회가 형성됨. "
            "빠른 응답 특성을 지닌 산업 시설 併設 BESS가 최대 수혜 대상임.",
            "**투자·미래 전망:** 삼성SDI ESS·LG CNS·두산에너빌리티 등 국내 BESS 통합기업과 "
            "에너지 관리 소프트웨어 기업이 직접 수혜를 입을 전망임. "
            "GridMind 등 글로벌 VPP 플랫폼 기업에도 한국 시장 진출의 유리한 접점이 생김. "
            "KPX IT 시스템 업그레이드 지연이 중간 수준의 규제 이행 리스크로 작용할 수 있음.",
        ],
        keyword_relevance=(
            "**`frequency regulation` 관련성**\n\n"
            "주파수 조정(frequency regulation)은 전력망 내 전기의 '맥박'을 60Hz로 일정하게 유지하는 작업임. "
            "주파수가 조금이라도 벗어나면 발전기와 모터가 오작동해 대규모 정전(블랙아웃)으로 이어질 수 있음. "
            "스마트폰이 배터리를 충·방전하며 전압을 안정시키는 것처럼, BESS가 전력망 전체의 주파수를 "
            "순간적으로 조절함.\n\n"
            "이 뉴스의 시장적 의미는 KEPCO의 독점이 깨지면서 민간 사업자의 BESS 투자 수익성이 '주파수 조정 "
            "수익'이라는 새로운 수익원으로 강화된다는 점임. BESS 경제성을 높이는 '수익 적층(revenue "
            "stacking)' 전략이 한국에서도 본격화될 전망임.\n\n"
            "**`demand response` 관련성**\n\n"
            "수요반응(demand response)은 전기 요금이 비싸거나 전력망이 불안정한 시간에 공장·건물·가정이 "
            "자발적으로 전력 소비를 줄여 전력망을 안정시키는 프로그램임. 이에 참여한 소비자는 보상을 받음.\n\n"
            "이번 규제 개혁으로 민간 수요반응 사업자가 주파수 조정 시장에 직접 참여하는 것이 가능해짐. "
            "이는 수요반응의 가치가 단순 피크 절감에서 고부가가치 계통 서비스로 확장됨을 의미하며, "
            "에너지 AI 플랫폼 기업에게 새로운 수익화 경로가 열리는 중요한 시장 변화임."
        ),
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# May 2026 monthly sample logs (same as generate_sample_monthly.py)
# ─────────────────────────────────────────────────────────────────────────────

MAY_LOGS: list[dict] = [
    {
        "log_date": "2026-05-03",
        "title": "Hyperscalers pledge $120B in AI data center capex — and utilities are scrambling",
        "url": "https://www.ft.com/content/ai-datacenter-capex-utilities-2026",
        "source_name": "Financial Times Tech",
        "category": "tech_news",
        "llm_summary": (
            "Combined AI data center capex commitments from Microsoft, Google, Amazon, and Meta "
            "reached $120B in Q1-Q2 2026, straining power grids near major cloud regions. "
            "Utilities are fast-tracking grid upgrades to retain large load customers."
        ),
        "ko_summary": (
            "마이크로소프트, 구글, 아마존, 메타 등 하이퍼스케일러들의 AI 데이터센터 설비투자(capex) 합계가 "
            "2026년 상반기 기준 1,200억 달러에 달하며 주요 클라우드 거점 인근 전력망에 상당한 부담을 주고 있음. "
            "전력회사들은 대형 부하 고객을 유지하기 위해 전력망 고도화를 서두르는 상황임."
        ),
        "key_trends": ["AI Infrastructure Capex", "Grid Stress", "Data Center Expansion"],
        "matched_keywords": ["data center", "power grid", "AI infrastructure"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-06",
        "title": "TSMC confirms Japan and Arizona fab expansions to feed AI chip demand",
        "url": "https://arstechnica.com/tech-policy/2026/05/tsmc-fab-expansion-ai/",
        "source_name": "Ars Technica",
        "category": "tech_news",
        "llm_summary": (
            "TSMC announced accelerated timelines for its Kumamoto Phase 2 and Arizona N2 fabs, "
            "targeting volume production by late 2027. The expansions are specifically designed "
            "for AI accelerator die with advanced CoWoS packaging."
        ),
        "ko_summary": (
            "TSMC가 일본 구마모토 2단계 팹과 미국 애리조나 N2 팹의 일정을 앞당겨 2027년 말 양산을 목표로 한다고 발표했음. "
            "해당 팹들은 AI 가속기용 다이와 CoWoS 첨단 패키징 생산에 특화해 설계됨."
        ),
        "key_trends": ["Semiconductor Supply Chain", "AI Chip Demand", "Advanced Packaging"],
        "matched_keywords": ["supply chain", "AI infrastructure"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-08",
        "title": "Grid-scale BESS hits record 8 GWh deployed in a single month",
        "url": "https://venturebeat.com/2026/05/08/bess-record-8gwh-monthly/",
        "source_name": "VentureBeat",
        "category": "energy",
        "llm_summary": (
            "Global battery energy storage deployments set a monthly record in May 2026, "
            "driven by renewable integration mandates in the US, EU, and South Korea. "
            "AI-powered energy management systems are reducing curtailment by up to 18%."
        ),
        "ko_summary": (
            "2026년 5월 글로벌 배터리 에너지 저장장치(BESS) 배포량이 월 단위 신기록을 세웠음. "
            "미국, EU, 한국의 재생에너지 통합 의무화 정책이 주된 동인임. "
            "AI 기반 에너지 관리 시스템(EMS) 도입으로 재생에너지 출력 제한(커튼먼트)이 최대 18%까지 감소했음."
        ),
        "key_trends": ["BESS Deployment Record", "Renewable Integration", "AI-powered EMS"],
        "matched_keywords": ["BESS", "battery energy storage", "energy management system"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-12",
        "title": "Inside the race to build liquid-cooled AI data centers at gigawatt scale",
        "url": "https://www.technologyreview.com/2026/05/12/liquid-cooled-ai-datacenters/",
        "source_name": "MIT Technology Review",
        "category": "tech_news",
        "llm_summary": (
            "Hyperscalers are investing billions in next-generation liquid-cooled facilities "
            "as AI GPU power densities exceed 100 kW per rack. Microsoft and Google are piloting "
            "direct liquid cooling at scale, targeting a 30% reduction in PUE."
        ),
        "ko_summary": (
            "AI GPU의 랙당 전력 밀도가 100kW를 초과하면서 하이퍼스케일러들이 차세대 액체 냉각 시설에 수십억 달러를 투자하고 있음. "
            "마이크로소프트와 구글은 대규모 직접 액체 냉각 방식을 시범 운영 중이며, "
            "PUE(전력 사용 효율) 30% 개선을 목표로 함."
        ),
        "key_trends": ["Liquid Cooling", "Data Center Efficiency", "PUE Optimization"],
        "matched_keywords": ["data center", "AI infrastructure"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-15",
        "title": "Virtual power plants cross 50 GW milestone in Europe",
        "url": "https://venturebeat.com/2026/05/15/vpp-50gw-europe/",
        "source_name": "VentureBeat",
        "category": "energy",
        "llm_summary": (
            "European VPP aggregators surpassed 50 GW of combined flexible capacity, making "
            "distributed energy resources a meaningful grid stability tool. Demand response "
            "automation is cutting peak load by 12% in pilot regions."
        ),
        "ko_summary": (
            "유럽 가상발전소(VPP) 집합체의 합산 조절 가능 용량이 50GW를 돌파해 분산 에너지 자원이 "
            "실질적인 전력망 안정화 수단으로 자리 잡았음. "
            "수요반응(DR) 자동화로 시범 지역의 첨두 부하가 12% 감소했음."
        ),
        "key_trends": ["Virtual Power Plant", "Demand Response", "Grid Flexibility"],
        "matched_keywords": ["virtual power plant", "VPP", "demand response", "grid stability"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-18",
        "title": "HBM supply crunch is the new bottleneck for AI training clusters",
        "url": "https://arstechnica.com/hardware/2026/05/hbm-supply-crunch-ai/",
        "source_name": "Ars Technica",
        "category": "tech_news",
        "llm_summary": (
            "With GPU die supply improving, HBM4 memory bandwidth has become the critical "
            "constraint for large-scale AI training. SK Hynix and Micron are racing to ramp "
            "capacity, with lead times stretching to 18 months."
        ),
        "ko_summary": (
            "GPU 다이 공급이 개선되면서 HBM4 메모리 대역폭이 대규모 AI 학습의 새로운 병목으로 부상했음. "
            "SK하이닉스와 마이크론이 생산 능력 확대에 속도를 내고 있지만 "
            "납기 기간이 18개월까지 늘어나는 상황임."
        ),
        "key_trends": ["HBM Supply Shortage", "AI Training Infrastructure", "Memory Bandwidth"],
        "matched_keywords": ["supply chain", "AI infrastructure"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-20",
        "title": "The EU AI Act is reshaping how enterprises buy software",
        "url": "https://www.technologyreview.com/2026/05/20/eu-ai-act-enterprise-software/",
        "source_name": "MIT Technology Review",
        "category": "enterprise",
        "llm_summary": (
            "With enforcement deadlines approaching, vendors are bundling compliance dashboards "
            "and audit trails into enterprise AI platforms. Legal teams now sit alongside CTOs "
            "in AI procurement decisions."
        ),
        "ko_summary": (
            "EU AI Act 시행 마감일이 다가오면서 벤더들이 기업용 AI 플랫폼에 컴플라이언스 대시보드와 "
            "감사 추적 기능을 기본으로 탑재하고 있음. "
            "AI 구매 결정에 법무팀이 CTO와 나란히 참여하는 구조가 자리 잡고 있음."
        ),
        "key_trends": ["EU AI Act Compliance", "Enterprise AI Governance", "Regulatory Tech"],
        "matched_keywords": ["market size", "M&A"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-22",
        "title": "Energy-tech M&A: Three grid software acquisitions exceed $1B each in May",
        "url": "https://venturebeat.com/2026/05/22/grid-software-ma-may2026/",
        "source_name": "VentureBeat",
        "category": "enterprise",
        "llm_summary": (
            "Utilities and infrastructure funds closed three major acquisitions of grid management "
            "software firms, betting on the convergence of AI and energy systems. Deal multiples "
            "averaged 12x ARR, signaling high growth expectations."
        ),
        "ko_summary": (
            "전력회사와 인프라 펀드들이 전력망 관리 소프트웨어 기업 3곳을 각각 10억 달러 이상에 인수했음. "
            "AI와 에너지 시스템의 융합에 베팅한 것임. "
            "평균 인수 배수는 ARR의 12배로, 높은 성장 기대치를 반영함."
        ),
        "key_trends": ["Grid Software M&A", "Energy-Tech Consolidation", "AI-Energy Convergence"],
        "matched_keywords": ["smart grid", "M&A", "market size"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-25",
        "title": "Tesla and BYD deepen stakes in grid-edge hardware startups",
        "url": "https://www.theverge.com/2026/05/25/tesla-byd-grid-edge-investment/",
        "source_name": "The Verge",
        "category": "enterprise",
        "llm_summary": (
            "Both EV giants made strategic investments in microgrid controller and smart inverter "
            "startups in May, signaling a push to monetize energy infrastructure beyond vehicles. "
            "Analysts see parallels to the Powerwall-to-Megapack evolution."
        ),
        "ko_summary": (
            "테슬라와 BYD가 5월 마이크로그리드 컨트롤러 및 스마트 인버터 스타트업에 전략적 투자를 단행했음. "
            "자동차를 넘어 에너지 인프라에서 수익을 창출하겠다는 의도로 풀이됨. "
            "전문가들은 이를 Powerwall에서 Megapack으로 이어지는 테슬라의 에너지 사업 확장 패턴과 유사하다고 봄."
        ),
        "key_trends": ["Grid-Edge Hardware", "EV-Energy Convergence", "Microgrid Investment"],
        "matched_keywords": ["microgrid", "startup funding", "smart grid"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-27",
        "title": "AI governance compliance costs reshape enterprise IT budgets",
        "url": "https://www.ft.com/content/ai-governance-compliance-costs-2026",
        "source_name": "Financial Times Tech",
        "category": "enterprise",
        "llm_summary": (
            "Large enterprises are allocating 8-12% of AI project budgets to governance and "
            "compliance tooling following EU AI Act enforcement. Startups offering automated "
            "audit trails and explainability APIs are seeing 5x growth in ARR."
        ),
        "ko_summary": (
            "대형 기업들이 EU AI Act 시행 이후 AI 프로젝트 예산의 8~12%를 거버넌스 및 컴플라이언스 도구에 배정하고 있음. "
            "자동화된 감사 추적과 설명 가능성(explainability) API를 제공하는 스타트업들이 ARR 5배 성장을 기록 중임."
        ),
        "key_trends": ["AI Compliance Budget", "Explainability Tools", "Governance Spending"],
        "matched_keywords": ["market size", "market forecast", "startup funding"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
    {
        "log_date": "2026-05-29",
        "title": "Startup funding in demand response and microgrid controls hits $2.3B in May",
        "url": "https://www.theverge.com/2026/05/29/demand-response-microgrid-funding/",
        "source_name": "The Verge",
        "category": "energy",
        "llm_summary": (
            "VC and corporate investors poured a record $2.3B into demand response automation "
            "and microgrid control startups in May, triple the year-ago figure. AI-native grid "
            "orchestration platforms captured the majority of funding."
        ),
        "ko_summary": (
            "VC와 기업 투자자들이 5월 수요반응 자동화 및 마이크로그리드 제어 스타트업에 "
            "전년 대비 3배 수준인 23억 달러를 투자했음. "
            "AI 기반 전력망 오케스트레이션 플랫폼이 투자금의 대부분을 흡수했음."
        ),
        "key_trends": ["Demand Response Funding", "Microgrid Controls", "AI Grid Orchestration"],
        "matched_keywords": ["demand response", "microgrid", "startup funding", "M&A"],
        "ko_summary_steps": [],
        "en_summary_steps": [],
        "keyword_relevance": "",
    },
]


def generate_daily() -> None:
    from datetime import date
    settings = load_settings()
    target = date(2026, 6, 21)
    top_kw = list(settings.analysis_keywords)

    print(f"Generating daily report for {target} ({len(DAILY_ARTICLES)} articles)...")
    path = save_daily_report(target, DAILY_ARTICLES, top_keywords=top_kw)
    print(f"  -> {path}")


def generate_monthly(*, en: bool = True, ko: bool = True) -> None:
    settings = load_settings()
    generator = ReportGenerator(settings)

    if en:
        print("Generating English monthly report for 2026-05...")
        en_path = generator.generate_monthly_report(2026, 5, MAY_LOGS)
        print(f"  -> {en_path}")

    if ko:
        print("Generating Korean monthly report for 2026-05...")
        ko_path = generator.generate_monthly_report_ko(2026, 5, MAY_LOGS)
        print(f"  -> {ko_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate sample reports")
    parser.add_argument("--daily-only", action="store_true")
    parser.add_argument("--monthly-only", action="store_true")
    parser.add_argument("--ko-only", action="store_true", help="Generate Korean monthly report only")
    parser.add_argument("--en-only", action="store_true", help="Generate English monthly report only")
    args = parser.parse_args()

    if args.ko_only:
        generate_monthly(en=False, ko=True)
    elif args.en_only:
        generate_monthly(en=True, ko=False)
    elif args.monthly_only:
        generate_monthly()
    elif args.daily_only:
        generate_daily()
    else:
        generate_daily()
        print()
        generate_monthly()

    print("\nDone!")
