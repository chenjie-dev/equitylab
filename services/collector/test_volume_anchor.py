"""成交量锚定：跨天 / 跨周 / 节假日 / 量回落。"""

from volume_anchor import VolumeState, next_volume_anchor


def test_first_sight_anchors_without_trade():
    st, delta, reason = next_volume_anchor(None, 1000, trade_date="2026-10-28")
    assert st == VolumeState("2026-10-28", 1000)
    assert delta == 0 and reason == "first"


def test_same_day_increase_emits_delta():
    prev = VolumeState("2026-10-28", 1000)
    st, delta, reason = next_volume_anchor(
        prev, 1500, trade_date="2026-10-28", clock_date="2026-10-28"
    )
    assert st.volume == 1500 and delta == 500 and reason == "delta"


def test_cross_day_date_change():
    prev = VolumeState("2026-10-27", 4_000_000)
    st, delta, reason = next_volume_anchor(
        prev, 800, trade_date="2026-10-28", clock_date="2026-10-28"
    )
    assert reason == "date_change" and delta == 0 and st.volume == 800
    st2, d2, r2 = next_volume_anchor(st, 1200, trade_date="2026-10-28")
    assert r2 == "delta" and d2 == 400


def test_cross_weekend_fri_to_mon():
    prev = VolumeState("2026-10-24", 2_000_000)  # Fri
    st, delta, reason = next_volume_anchor(
        prev, 500, trade_date="2026-10-27", clock_date="2026-10-27"
    )  # Mon
    assert reason == "date_change" and delta == 0
    assert st.trade_date == "2026-10-27"


def test_holiday_gap_date_jump():
    # 例如国庆：9-30 → 10-9
    prev = VolumeState("2026-09-30", 9_000_000)
    st, delta, reason = next_volume_anchor(
        prev, 300, trade_date="2026-10-09", clock_date="2026-10-09"
    )
    assert reason == "date_change" and delta == 0 and st.volume == 300


def test_holiday_freeze_clock_rollover_without_sina_date():
    # 休市日新浪仍回旧交易日累计量；本地已跨到节假日
    prev = VolumeState("2026-10-01", 5_000_000)
    st, delta, reason = next_volume_anchor(
        prev, 5_000_000, trade_date="2026-10-01", clock_date="2026-10-02"
    )
    assert reason == "clock_rollover" and delta == 0
    assert st.trade_date == "2026-10-02"


def test_vol_reset_same_reported_date():
    prev = VolumeState("2026-10-28", 4_000_000)
    st, delta, reason = next_volume_anchor(
        prev, 800, trade_date="2026-10-28", clock_date="2026-10-28"
    )
    assert reason == "vol_reset" and delta == 0 and st.volume == 800


def test_non_trading_day_blocks_delta():
    prev = VolumeState("2026-10-09", 5_000_000)
    st, delta, reason = next_volume_anchor(
        prev,
        5_100_000,
        trade_date="2026-10-10",
        clock_date="2026-10-10",
        is_trading_day=False,
    )
    assert reason == "non_trading" and delta == 0
    assert st.volume == 5_100_000
