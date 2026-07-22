"""Tests for press-evidence attestation and monthly theme intro fact-check."""
from __future__ import annotations

from src.press_evidence import (
    attest_keywords,
    collect_press_evidence,
    looks_like_keyword_dump,
    strip_unattested_monitoring_keywords,
    theme_intro_from_evidence,
)
from src.rd_monthly_report import _factcheck_structured, _theme_intro


PRESS = (
    "능동적인 에너지전환을 통해 기후변화 대응은 물론 지정학적 불안정을 최소화할 수 있도록 "
    "에너지 기술개발을 대폭 강화한다. 태양광·풍력 등 재생에너지 대전환에 나서는 한편, "
    "차세대 원자력, 핵융합 등 무탄소 에너지도 동시에 육성한다. "
    "HVDC(초고압 직류송전) 등 차세대 지능형 전력망 구축, 철강 등 산업계 탄소저감과 "
    "순환경제 구현도 추진한다. ※ 새만금-서화성을 연결하는 서해안 HVDC(초고압 직류송전) "
    "조기 구축(’30)."
)

MONITORING = [
    "전력계통",
    "스마트그리드",
    "파워그리드",
    "에너지고속도로",
    "HVDC",
    "MMC",
    "STATCOM",
    "장주기 ESS",
    "그리드포밍 인버터",
    "Digital Grid",
]


def test_attest_only_keywords_in_press() -> None:
    attested = attest_keywords(PRESS, MONITORING)
    assert attested == ["HVDC"]
    assert "스마트그리드" not in attested
    assert "MMC" not in attested


def test_collect_quotes_wrap_attested_term() -> None:
    evidence = collect_press_evidence(PRESS, MONITORING)
    assert evidence.attested_keywords == ["HVDC"]
    assert evidence.quotes
    assert "HVDC" in evidence.quotes[0]
    assert evidence.quotes[0].startswith("「")


def test_theme_intro_does_not_dump_full_keyword_list() -> None:
    items = [
        {
            "actor": "과기정통부",
            "attested_keywords": ["HVDC"],
        }
    ]
    lead = _theme_intro("전력·그리드", items, MONITORING)
    assert "HVDC" in lead
    assert "스마트그리드" not in lead
    assert "MMC" not in lead
    assert "연계된 국가 R&D·정책 신호를 발표함" not in lead


def test_theme_intro_without_attestation_is_cautious() -> None:
    lead = theme_intro_from_evidence("전력·그리드", ["과기정통부"], [])
    assert "원문 직접 언급은 제한적임" in lead
    assert "스마트그리드" not in lead


def test_strip_unattested_keywords_from_dump() -> None:
    dump = (
        "당월 과기정통부 등이 전력계통 · 스마트그리드 · 파워그리드 · 에너지고속도로 · "
        "HVDC · MMC · STATCOM와 연계된 국가 R&D·정책 신호를 발표함."
    )
    assert looks_like_keyword_dump(dump, MONITORING)
    cleaned = strip_unattested_monitoring_keywords(dump, MONITORING, ["HVDC"])
    assert "HVDC" in cleaned
    assert "스마트그리드" not in cleaned
    assert "MMC" not in cleaned


def test_factcheck_structured_replaces_keyword_dump() -> None:
    entries = [
        {
            "ref": 1,
            "actor": "과기정통부",
            "attested_keywords": ["HVDC"],
            "evidence_quotes": ["「HVDC 등 차세대 지능형 전력망 구축」"],
            "proposable": "에너지 전환",
            "summary": "제6차 과학기술기본계획",
            "title": "제6차 기본계획",
            "purpose": "에너지전환",
            "pain": "",
            "fact": "HVDC",
        }
    ]
    structured = {
        "executive_summary": (
            "전력계통 · 스마트그리드 · 파워그리드 · 에너지고속도로 · HVDC · MMC · "
            "STATCOM · 배전망 디지털화 기준 직접 1건"
        ),
        "opportunities": [
            {
                "field": "전력·그리드",
                "summary": (
                    "당월 과기정통부 등이 전력계통 · 스마트그리드 · 파워그리드 · "
                    "에너지고속도로 · HVDC · MMC · STATCOM와 연계된 국가 R&D·정책 "
                    "신호를 발표함."
                ),
                "items": ["과기정통부 기본계획"],
                "refs": [1],
            }
        ],
    }
    fixed = _factcheck_structured(structured, entries, MONITORING)
    summary = fixed["opportunities"][0]["summary"]
    assert "스마트그리드" not in summary
    assert "MMC" not in summary
    assert "HVDC" in summary or "원문" in summary
