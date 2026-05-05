from __future__ import annotations

from oqe.analytics.iv_metrics import mid_price


def test_mid_price_normal_no_flags():
    m = mid_price(1.0, 3.0)
    assert m.value == 2.0
    assert m.flags == ()


def test_mid_price_fallback_to_last_marks_not_from_bidask():
    m = mid_price(None, None, last=2.5)
    assert m.value == 2.5
    assert "MID_NOT_FROM_BIDASK" in m.flags
    assert "MID_FROM_LAST" in m.flags


def test_mid_price_fallback_to_bid_only_marks_not_from_bidask():
    m = mid_price(1.25, None)
    assert m.value == 1.25
    assert "MID_NOT_FROM_BIDASK" in m.flags
    assert "MID_FROM_BID_ONLY" in m.flags


def test_mid_price_fallback_to_ask_only_marks_not_from_bidask():
    m = mid_price(None, 3.0)
    assert m.value == 3.0
    assert "MID_NOT_FROM_BIDASK" in m.flags
    assert "MID_FROM_ASK_ONLY" in m.flags


def test_mid_price_negative_last_is_rejected():
    # Per spec: last must be non-negative to be used as fallback.
    m = mid_price(None, None, last=-1.0)
    assert m.value is None
    assert "NEGATIVE_LAST" in m.flags
    assert "MID_MISSING" in m.flags


def test_mid_price_invalid_bid_ask_propagates_into_fallback_flags():
    # bid > ask is invalid; fallback to last should preserve the diagnostic flags.
    m = mid_price(5.0, 3.0, last=4.0)
    assert m.value == 4.0
    assert "INVALID_BID_ASK" in m.flags
    assert "MID_NOT_FROM_BIDASK" in m.flags
    assert "MID_FROM_LAST" in m.flags


def test_mid_price_negative_bid_propagates_into_fallback_flags():
    m = mid_price(-1.0, 5.0, last=4.0)
    assert m.value == 4.0
    assert "NEGATIVE_BID" in m.flags
    assert "INVALID_BID_ASK" in m.flags
    assert "MID_FROM_LAST" in m.flags


def test_mid_price_all_missing_emits_mid_missing():
    m = mid_price(None, None, None)
    assert m.value is None
    assert "MID_MISSING" in m.flags
    assert "MISSING_BID" in m.flags
    assert "MISSING_ASK" in m.flags
    assert "MISSING_LAST" in m.flags
