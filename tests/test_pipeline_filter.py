"""Quick sanity check for calendar-day filtering."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from src.models import RawArticle
from src.pipeline import _within_log_date

KST = ZoneInfo("Asia/Seoul")


def _article(title: str, pub_kst: datetime) -> RawArticle:
    return RawArticle(
        title=title,
        url=f"https://example.com/{title.replace(' ', '-').lower()}",
        summary="",
        source_name="Test",
        category="news",
        published_at=pub_kst.astimezone(timezone.utc),
    )


def test_june28_articles_only_on_june28() -> None:
    log_date = date(2026, 6, 28)
    window_end = datetime(2026, 6, 29, 10, 0, tzinfo=KST)
    articles = [
        _article("Firmus", datetime(2026, 6, 28, 14, 1, tzinfo=KST)),
        _article("Prompt injection", datetime(2026, 6, 28, 18, 0, tzinfo=KST)),
        _article("Other day", datetime(2026, 6, 29, 9, 0, tzinfo=KST)),
    ]
    matched = _within_log_date(articles, log_date, window_end=window_end)
    assert len(matched) == 2
    assert all(a.title != "Other day" for a in matched)


def test_june29_does_not_include_june28() -> None:
    log_date = date(2026, 6, 29)
    window_end = datetime(2026, 6, 29, 10, 0, tzinfo=KST)
    articles = [
        _article("Firmus", datetime(2026, 6, 28, 14, 1, tzinfo=KST)),
        _article("Today only", datetime(2026, 6, 29, 9, 0, tzinfo=KST)),
    ]
    matched = _within_log_date(articles, log_date, window_end=window_end)
    assert len(matched) == 1
    assert matched[0].title == "Today only"


if __name__ == "__main__":
    test_june28_articles_only_on_june28()
    test_june29_does_not_include_june28()
    print("OK")
