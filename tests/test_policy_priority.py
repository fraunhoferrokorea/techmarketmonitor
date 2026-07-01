import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.filter import filter_articles
from src.models import RawArticle
from src.policy_priority import gov_target_pass_label, gov_target_score, is_gov_target


def _article(title: str, source: str = "정책브리핑 산업통상부") -> RawArticle:
    return RawArticle(
        title=title,
        url="https://www.korea.kr/briefing/pressReleaseView.do?newsId=1",
        summary="",
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


def test_filter_passes_gov_target_without_keyword_match() -> None:
    article = _article("제6차 국가표준기본계획 확정 발표")
    result = filter_articles([article], keywords=["전력계통"])
    assert len(result) == 1
    assert result[0].matched_keywords == [gov_target_pass_label()]


def test_filter_passes_mou_without_keyword_match() -> None:
    article = _article("KISTEP·독일 연구기관, 에너지 기술협력 MOU", source="KISTEP")
    result = filter_articles([article], keywords=["전력계통"])
    assert len(result) == 1


def test_filter_still_requires_keywords_for_general_news() -> None:
    article = _article("유통업체 매출 동향 발표", source="연합뉴스 경제")
    result = filter_articles([article], keywords=["전력계통"])
    assert result == []


if __name__ == "__main__":
    test_gov_target_detects_national_standard_plan()
    test_gov_target_detects_fraunhofer_mou()
    test_gov_target_detects_rd_program()
    test_filter_passes_gov_target_without_keyword_match()
    test_filter_passes_mou_without_keyword_match()
    test_filter_still_requires_keywords_for_general_news()
    print("ok")
