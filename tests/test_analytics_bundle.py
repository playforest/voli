from oqe.analytics.metrics_bundle import compute_v1_metrics_bundle


def test_compute_v1_metrics_bundle_smoke(synth_market):
    spot, contracts, greeks_by_symbol, *_ = synth_market

    b = compute_v1_metrics_bundle(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks_by_symbol,
        right="call",
    )

    assert b.term_structure.atm_strike is not None
    assert b.term_structure.front_expiry is not None
    assert b.skew_slope.slope is not None
