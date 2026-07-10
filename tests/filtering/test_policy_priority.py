from datetime import datetime, timezone

from src.filter import filter_articles
from src.models import RawArticle
from src.policy_priority import (
    gov_target_pass_label,
    gov_target_score,
    has_energy_grid_domain,
    is_gov_target,
    is_plan_document,
    passes_gov_collection_exception,
)


def _article(title: str, source: str = "산업통상부 보도자료", summary: str = "") -> RawArticle:
    return RawArticle(
        title=title,
        url="https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/1/view",
        summary=summary,
        source_name=source,
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )


def test_gov_target_detects_national_standard_plan() -> None:
    article = _article("산업부 등 18개 부·처·청 합동 제6차 국가표준기본계획('26~'30) 발표")
    assert is_gov_target(article)
    assert gov_target_score(article) >= 100


def test_gov_target_detects_fraunhofer_mou() -> None:
    article = _article("프라운호퍼·ETRI, AI 반도체 공동연구 MOU 체결", source="과기정통부 보도자료")
    assert is_gov_target(article)
    assert gov_target_score(article) >= 60


def test_gov_target_detects_rd_program() -> None:
    article = _article("과기정통부, 스마트그리드 R&D 지원사업 공고", source="과기정통부 보도자료")
    assert is_gov_target(article)


def test_energy_domain_required_for_gov_collection_bypass() -> None:
    plan = _article("제6차 국가표준기본계획 확정 발표")
    assert is_gov_target(plan)
    assert not has_energy_grid_domain(plan)
    assert not passes_gov_collection_exception(plan)

    grid = _article("과기정통부, 스마트그리드 R&D 지원사업 공고")
    assert passes_gov_collection_exception(grid)

    fraunhofer = _article("프라운호퍼·ETRI, AI 반도체 공동연구 MOU 체결", source="과기정통부 보도자료")
    assert passes_gov_collection_exception(fraunhofer)


def test_filter_passes_gov_target_with_core_keyword() -> None:
    article = _article("과기정통부, 스마트그리드 R&D 지원사업 공고")
    result = filter_articles(
        [article],
        keywords=["전력계통", "스마트그리드"],
        required_keywords=["전력계통", "스마트그리드"],
    )
    assert len(result) == 1


def test_filter_passes_gov_target_with_energy_domain_without_core_keyword() -> None:
    article = _article(
        "기후에너지환경부, 에너지전환 로드맵 발표",
        source="정책브리핑 기후에너지환경부",
        summary="재생에너지 확대와 전력망 보강 계획을 확정함.",
    )
    result = filter_articles(
        [article],
        keywords=["전력계통"],
        required_keywords=["전력계통"],
    )
    assert len(result) == 1
    assert gov_target_pass_label() in result[0].matched_keywords or result[0].matched_keywords


def test_filter_excludes_gov_target_without_energy_domain() -> None:
    article = _article("제6차 국가표준기본계획 확정 발표")
    result = filter_articles(
        [article],
        keywords=["전력계통"],
        required_keywords=["전력계통"],
    )
    assert result == []


def test_filter_passes_mou_from_official_source_with_energy_domain() -> None:
    article = _article("KISTEP·독일 연구기관, 에너지 기술협력 MOU", source="KISTEP")
    result = filter_articles(
        [article],
        keywords=["전력계통"],
        required_keywords=["전력계통"],
    )
    assert len(result) == 1


def test_filter_excludes_health_mou_without_energy_domain() -> None:
    article = _article("한-몽 보건의료 협력 MOU 체결", source="정책브리핑 보건복지부")
    result = filter_articles(
        [article],
        keywords=["전력계통", "MOU"],
        required_keywords=["전력계통"],
    )
    assert result == []


def test_filter_passes_fraunhofer_without_energy_domain() -> None:
    article = _article("프라운호퍼·ETRI, AI 반도체 공동연구 MOU 체결", source="과기정통부 보도자료")
    result = filter_articles(
        [article],
        keywords=["전력계통"],
        required_keywords=["전력계통"],
    )
    assert len(result) == 1


def test_filter_excludes_rd_only_match_without_core_top5() -> None:
    article = _article("이화여대, 소아암 연구개발 결과 발표", source="연합뉴스")
    result = filter_articles(
        [article],
        keywords=["전력계통", "연구개발"],
        required_keywords=["전력계통", "스마트그리드", "파워그리드", "bess", "에너지저장"],
    )
    assert result == []


def test_filter_excludes_epidemiology_meta_analysis_without_funder() -> None:
    article = RawArticle(
        title='"자동차 매연, 소아암 최악" 암 위험 최대 68%↑',
        url="https://example.com/childhood-cancer-meta",
        summary=(
            "이화여대·국립암센터·미네소타대 공동 연구팀이 교통 대기오염과 소아암 "
            "상관관계를 규명한 메타분석 결과를 발표함."
        ),
        source_name="연합뉴스",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    result = filter_articles(
        [article],
        keywords=["전력계통", "연구개발", "대기오염"],
        required_keywords=["전력계통"],
    )
    assert result == []


def test_filter_excludes_non_energy_budget_program_without_core() -> None:
    article = RawArticle(
        title="환경부, 국내 대기오염 저감 R&D 500억 예산 편성",
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=99",
        summary="환경부가 국내 미세먼지·대기오염 저감 기술 개발 지원 사업에 예산을 편성함.",
        source_name="환경부 보도자료",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    result = filter_articles(
        [article],
        keywords=["전력계통", "대기오염"],
        required_keywords=["전력계통"],
    )
    assert result == []


def test_filter_keeps_energy_budget_program_without_core_top5() -> None:
    article = RawArticle(
        title="기후에너지환경부, 전력망 보강 R&D 500억 예산 편성",
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=100",
        summary="전력계통 안정화 및 스마트그리드 실증 지원 사업에 예산을 편성함.",
        source_name="기후에너지환경부 보도자료",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    result = filter_articles(
        [article],
        keywords=["전력계통"],
        required_keywords=["전력계통"],
    )
    assert len(result) == 1


def test_is_plan_document_expdoc_url() -> None:
    article = RawArticle(
        title="2026 디지털정부 전망",
        url="https://www.korea.kr/archive/expDocView.do?docId=41730",
        summary="",
        source_name="정책브리핑 전문자료 행정안전부",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    assert is_plan_document(article)


def test_filter_still_requires_keywords_for_general_news() -> None:
    article = _article("유통업체 매출 동향 발표", source="연합뉴스 경제")
    result = filter_articles([article], keywords=["전력계통"])
    assert result == []


def test_filter_excludes_student_field_trip_program() -> None:
    article = RawArticle(
        title="제주·경남 대학생 45명 에너지 산업현장으로",
        url="https://example.com/jeju-field-trip",
        summary=(
            "제주대·경상국립대·창원대 학생 45명이 2026 제주-경남 협력형 "
            "비교과 프로그램에 참여해 산업체 방문 현장교육을 받았음."
        ),
        source_name="연합뉴스",
        category="korean",
        published_at=datetime.now(tz=timezone.utc),
    )
    result = filter_articles(
        [article],
        keywords=["전력계통", "스마트그리드", "에너지"],
        required_keywords=["전력계통"],
    )
    assert result == []
