"""
One-off script: generate sample May 2026 monthly reports (English + Korean)
using the src/report_generator.py pipeline with realistic sample data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Force output to output/monthly regardless of .env
os.environ["REPORTS_OUTPUT_DIR"] = "output/monthly"

sys.path.insert(0, str(Path(__file__).parent))

from src.config import load_settings
from src.report_generator import ReportGenerator

YEAR, MONTH = 2026, 5

SAMPLE_LOGS: list[dict] = [
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
            "마이크로소프트, 구글, 아마존, 메타 등 하이퍼스케일러들의 AI 데이터 센터 설비투자(capex) 합계가 "
            "2026년 상반기 기준 1,200억 달러에 달하며 주요 클라우드 거점 인근 전력망에 상당한 부담을 주고 있다. "
            "전력회사들은 대형 부하 고객을 유지하기 위해 전력망 고도화를 서두르는 상황이다."
        ),
        "key_trends": ["AI Infrastructure Capex", "Grid Stress", "Data Center Expansion"],
    },
    {
        "log_date": "2026-05-06",
        "title": "TSMC confirms Japan and Arizona fab expansions to feed AI chip demand",
        "url": "https://arstechnica.com/tech-policy/2026/05/tsmc-fab-expansion-ai/",
        "source_name": "Ars Technica",
        "category": "semiconductor",
        "llm_summary": (
            "TSMC announced accelerated timelines for its Kumamoto Phase 2 and Arizona N2 fabs, "
            "targeting volume production by late 2027. The expansions are specifically designed "
            "for AI accelerator die with advanced CoWoS packaging."
        ),
        "ko_summary": (
            "TSMC가 일본 구마모토 2단계 팹과 미국 애리조나 N2 팹의 일정을 앞당겨 2027년 말 양산을 목표로 한다고 발표했다. "
            "해당 팹들은 AI 가속기용 다이와 CoWoS 첨단 패키징 생산에 특화해 설계된 것이다."
        ),
        "key_trends": ["Semiconductor Supply Chain", "AI Chip Demand", "Advanced Packaging"],
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
            "2026년 5월 글로벌 배터리 에너지 저장장치(BESS) 배포량이 월 단위 신기록을 세웠다. "
            "미국, EU, 한국의 재생에너지 통합 의무화 정책이 주된 동인이다. "
            "AI 기반 에너지 관리 시스템(EMS) 도입으로 재생에너지 출력 제한(커튼먼트)이 최대 18%까지 감소했다."
        ),
        "key_trends": ["BESS Deployment Record", "Renewable Integration", "AI-powered EMS"],
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
            "AI GPU의 랙당 전력 밀도가 100kW를 초과하면서 하이퍼스케일러들이 차세대 액체 냉각 시설에 수십억 달러를 투자하고 있다. "
            "마이크로소프트와 구글은 대규모 직접 액체 냉각 방식을 시범 운영 중이며, "
            "PUE(전력 사용 효율) 30% 개선을 목표로 한다."
        ),
        "key_trends": ["Liquid Cooling", "Data Center Efficiency", "PUE Optimization"],
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
            "실질적인 전력망 안정화 수단으로 자리 잡았다. "
            "수요반응(DR) 자동화로 시범 지역의 첨두 부하가 12% 감소했다."
        ),
        "key_trends": ["Virtual Power Plant", "Demand Response", "Grid Flexibility"],
    },
    {
        "log_date": "2026-05-18",
        "title": "HBM supply crunch is the new bottleneck for AI training clusters",
        "url": "https://arstechnica.com/hardware/2026/05/hbm-supply-crunch-ai/",
        "source_name": "Ars Technica",
        "category": "semiconductor",
        "llm_summary": (
            "With GPU die supply improving, HBM4 memory bandwidth has become the critical "
            "constraint for large-scale AI training. SK Hynix and Micron are racing to ramp "
            "capacity, with lead times stretching to 18 months."
        ),
        "ko_summary": (
            "GPU 다이 공급이 개선되면서 HBM4 메모리 대역폭이 대규모 AI 학습의 새로운 병목으로 부상했다. "
            "SK하이닉스와 마이크론이 생산 능력 확대에 속도를 내고 있지만 "
            "납기 기간이 18개월까지 늘어나는 상황이다."
        ),
        "key_trends": ["HBM Supply Shortage", "AI Training Infrastructure", "Memory Bandwidth"],
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
            "감사 추적 기능을 기본으로 탑재하고 있다. "
            "AI 구매 결정에 법무팀이 CTO와 나란히 참여하는 구조가 자리 잡고 있다."
        ),
        "key_trends": ["EU AI Act Compliance", "Enterprise AI Governance", "Regulatory Tech"],
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
            "전력회사와 인프라 펀드들이 전력망 관리 소프트웨어 기업 3곳을 각각 10억 달러 이상에 인수했다. "
            "AI와 에너지 시스템의 융합에 베팅한 것이다. "
            "평균 인수 배수는 ARR의 12배로, 높은 성장 기대치를 반영한다."
        ),
        "key_trends": ["Grid Software M&A", "Energy-Tech Consolidation", "AI-Energy Convergence"],
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
            "테슬라와 BYD가 5월 마이크로그리드 컨트롤러 및 스마트 인버터 스타트업에 전략적 투자를 단행했다. "
            "자동차를 넘어 에너지 인프라에서 수익을 창출하겠다는 의도로 풀이된다. "
            "전문가들은 이를 Powerwall에서 Megapack으로 이어지는 테슬라의 에너지 사업 확장 패턴과 유사하다고 본다."
        ),
        "key_trends": ["Grid-Edge Hardware", "EV-Energy Convergence", "Microgrid Investment"],
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
            "대형 기업들이 EU AI Act 시행 이후 AI 프로젝트 예산의 8~12%를 거버넌스 및 컴플라이언스 도구에 배정하고 있다. "
            "자동화된 감사 추적과 설명 가능성(explainability) API를 제공하는 스타트업들이 ARR 5배 성장을 기록 중이다."
        ),
        "key_trends": ["AI Compliance Budget", "Explainability Tools", "Governance Spending"],
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
            "전년 대비 3배 수준인 23억 달러를 투자했다. "
            "AI 기반 전력망 오케스트레이션 플랫폼이 투자금의 대부분을 흡수했다."
        ),
        "key_trends": ["Demand Response Funding", "Microgrid Controls", "AI Grid Orchestration"],
    },
]


def main() -> None:
    settings = load_settings()
    generator = ReportGenerator(settings)

    print(f"Generating English report for {YEAR}-{MONTH:02d}...")
    en_path = generator.generate_monthly_report(YEAR, MONTH, SAMPLE_LOGS)
    print(f"  -> {en_path}")

    print(f"Generating Korean report for {YEAR}-{MONTH:02d}...")
    ko_path = generator.generate_monthly_report_ko(YEAR, MONTH, SAMPLE_LOGS)
    print(f"  -> {ko_path}")

    print("\nDone! Both reports saved to output/monthly/")


if __name__ == "__main__":
    main()
