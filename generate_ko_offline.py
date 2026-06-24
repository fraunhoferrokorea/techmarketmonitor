"""Build May 2026 Korean monthly report from cached structured data (no LLM)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("REPORTS_OUTPUT_DIR", "output/monthly")
sys.path.insert(0, str(Path(__file__).parent))

from generate_sample_reports import MAY_LOGS
from src.config import load_settings
from src.report_generator import ReportGenerator

STRUCTURED_KO = {
    "technology_name": "AI 및 에너지 융합",
    "monthly_headline": (
        "하이퍼스케일러들이 AI 데이터센터 설비투자(capex) 1,200억 달러를 약속하면서 "
        "전력망에 부담을 주고, 그리드 스케일 에너지 저장 및 AI 기반 에너지 관리 시스템 수요를 "
        "견인하고 있음 [1]."
    ),
    "monthly_context": (
        "마이크로소프트·구글·아마존·메타 등 4개 하이퍼스케일러의 AI 데이터센터 설비투자 합계가 "
        "2026년 상반기 기준 1,200억 달러에 달하며, 주요 클라우드 거점 인근 전력망에 상당한 부담을 "
        "주고 있음 [1]. 전력회사들은 대형 부하 고객을 유지하기 위해 전력망 고도화를 서두르는 "
        "상황임."
    ),
    "sec1": {
        "snapshot": (
            "AI와 에너지 융합 트렌드가 AI 데이터센터 설비투자, 그리드 스케일 에너지 저장, "
            "AI 기반 에너지 관리 시스템(EMS) 분야의 대규모 투자를 견인하고 있음 [1]. "
            "하이퍼스케일러들은 차세대 액체 냉각 시설 등 인프라 확장에 수십억 달러를 투입 중임 [4]. "
            "유럽 가상발전소(VPP) 집합체의 합산 유연 용량이 50GW를 돌파하며 분산 에너지 자원이 "
            "실질적인 전력망 안정화 수단으로 자리 잡고 있음 [5]."
        ),
        "key_findings": [
            "시장 신호: 재생에너지 통합 및 계통 안정성 수요에 힘입어 AI 기반 에너지 관리 시스템(EMS) "
            "글로벌 시장이 크게 성장할 것으로 전망됨 [3].",
            "경쟁 신호: TSMC가 일본 구마모토 2단계 및 미국 애리조나 N2 팹의 일정을 앞당겨 "
            "2027년 말 양산을 목표로 한다고 발표함 [2].",
            "한국 특화 신호: 한국이 재생에너지 통합 의무화 정책을 시행하면서 그리드 스케일 에너지 "
            "저장 및 AI 기반 EMS 수요가 견인되고 있음 [3].",
            "리스크 신호: HBM(고대역폭 메모리) 공급 부족이 대규모 AI 학습의 핵심 병목으로 부상했으며, "
            "납기가 18개월까지 늘어나는 상황임 [6].",
        ],
        "metrics": [
            {"metric": "글로벌 시장 규모", "value": "N/A", "yoy": "–", "forecast": "N/A", "source": "N/A"},
            {"metric": "한국 시장 규모", "value": "N/A", "yoy": "–", "forecast": "N/A", "source": "N/A"},
            {"metric": "TRL 단계", "value": "N/A", "yoy": "–", "forecast": "N/A", "source": "N/A"},
            {"metric": "주요 특허 출원국", "value": "N/A", "yoy": "–", "forecast": "–", "source": "N/A"},
            {"metric": "선도 벤더 시장점유율", "value": "N/A", "yoy": "–", "forecast": "–", "source": "N/A"},
        ],
    },
    "sec2": {
        "definition": (
            "AI 및 에너지 융합(AI and energy convergence)은 인공지능과 에너지 시스템을 통합해 "
            "에너지 소비와 생산을 최적화하는 기술 영역임 [1]."
        ),
        "trl_table": [],
        "differentiation": "N/A",
        "comparison_table": [],
        "patents": [],
    },
    "sec3": {"overview": "N/A", "segmentation": [], "regional": [], "drivers_barriers": []},
    "sec4": {"vendors": [], "korea_context": "N/A", "swot": {}, "five_forces": []},
    "sec5": {"publications": [], "funding": [], "emerging_directions": []},
    "sec6": {"policies": [], "compliance": []},
    "sec7": {"hype_cycle_phase": "N/A", "predictions": [], "roadmap": []},
    "sec8": {"opportunities": [], "risks": [], "actions": []},
    "sec9": {"methodology": "N/A", "quality": "N/A"},
}


def main() -> None:
    settings = load_settings()
    generator = ReportGenerator.__new__(ReportGenerator)
    generator.output_dir = settings.reports_output_dir
    generator.output_dir.mkdir(parents=True, exist_ok=True)

    document = generator._build_document_ko(2026, 5, MAY_LOGS, STRUCTURED_KO)
    output_path = generator.output_dir / "tech-market-report-2026-05-ko.docx"
    document.save(output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
