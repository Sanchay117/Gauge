import numpy as np
import pytest

from gauge.budget import BudgetExceeded, Ledger, RateLimited, VisitorLimiter, sam_cost
from gauge.laws import fit_law, select_law, verify
from gauge.measure import (Series, active_window, build_series, clean_track, motion_window, quality_warnings,
                           scale_from_reference)
from gauge.meta_api import parse_tracks, point_prompt

RNG = np.random.default_rng(7)


def noisy(values, sd=0.001):
    return values + RNG.normal(0, sd, len(values))


def fall(g=9.81, n=30, fps=60, v0=0.0):
    t = np.arange(n) / fps
    return t, noisy(-0.5 * g * t**2 + v0 * t + 1)


def swing(omega=4.0, gamma=0.05, seconds=6, fps=30, amp=0.2, phase=0.4):
    t = np.arange(int(seconds * fps)) / fps
    return t, noisy(amp * np.exp(-gamma * t) * np.cos(omega * t + phase) + 0.5)


def test_parse_tracks_sorts_propagation_output():
    raw = "<2f>1<|box;x1=1;y1=2;x2=3;y2=4;w=9;h=9|>\n<0f>1<|box;x1=5;y1=6;x2=7;y2=8;w=9;h=9|>,3<|box;x1=1;y1=1;x2=2;y2=2;w=9;h=9|>"
    tracks = parse_tracks(raw)
    assert [p["frame"] for p in tracks[1]] == [0, 2]
    assert sorted(tracks) == [1, 3]


def test_point_prompt_format():
    assert point_prompt(24, 393, 396, 1268, 960) == "<24f>1<|point;x=393;y=396;w=1268;h=960|>"


def test_series_flips_y_and_uses_real_timestamps():
    track = [{"frame": 0, "x1": 0, "y1": 0, "x2": 2, "y2": 2}, {"frame": 2, "x1": 0, "y1": 10, "x2": 2, "y2": 12}]
    series = build_series(track, [1.0, 1.1, 1.5], 0.01)
    assert series.t.tolist() == [0.0, 0.5]
    assert series.y[1] < series.y[0]


def test_scale_rejects_bad_reference():
    assert scale_from_reference((0, 0), (0, 100), 0.5) == 0.005
    with pytest.raises(ValueError):
        scale_from_reference((1, 1), (1, 1), 0.5)


def test_active_window_trims_hold_and_landing():
    t = np.arange(90) / 60
    fall_t = np.clip(t - 0.5, 0, 0.5)
    y = -0.5 * 9.81 * fall_t**2
    start, end = active_window(Series(t, np.zeros(90), y), "y")
    assert 0.45 <= start <= 0.6
    assert 0.9 <= end <= 1.05


def test_motion_window_isolates_a_jump_from_walking():
    t = np.linspace(0, 3, 90)
    flight = (t > 1) & (t < 2.2)
    y = 0.05 * np.sin(9 * t) + np.where(flight, 1.3 * (t - 1) - 0.81 * (t - 1) ** 2, 0)
    start, end = motion_window(Series(t, np.zeros(90), y), "y")
    assert 0.9 < start < 1.3
    assert 1.9 < end < 2.3


def test_motion_window_leaves_a_clean_toss_alone():
    t = np.linspace(0, 1, 60)
    y = 2 * t - 4.9 * t**2
    start, end = motion_window(Series(t, np.zeros(60), y), "y")
    assert (start, end) == pytest.approx((0, 1), abs=0.05)


def test_active_window_keeps_the_top_of_a_toss():
    t = np.arange(90) / 60
    y = 3 * t - 0.5 * 9.81 * t**2
    start, end = active_window(Series(t, np.zeros(90), y), "y")
    assert start == pytest.approx(0, abs=0.05)
    assert end == pytest.approx(t[-1], abs=0.05)


def box(frame, x, y, half=10):
    return {"frame": frame, "x1": x - half, "y1": y - half, "x2": x + half, "y2": y + half}


def test_clean_track_drops_edge_clipped_boxes():
    track = [box(i, 100, 100 + 40 * i) for i in range(5)] + [{"frame": 5, "x1": 90, "y1": 475, "x2": 110, "y2": 479}]
    assert [p["frame"] for p in clean_track(track, 640, 480)] == [0, 1, 2, 3, 4]


def test_clean_track_drops_a_jump_to_another_object():
    track = [box(i, 100 + 10 * i, 100) for i in range(6)] + [box(6, 300, 400)] + [box(7, 170, 100)]
    assert [p["frame"] for p in clean_track(track, 640, 480)] == [0, 1, 2, 3, 4, 5, 7]


def test_clean_track_accepts_a_real_relocation_eventually():
    track = [box(i, 100, 100) for i in range(3)] + [box(i, 400, 300) for i in range(3, 9)]
    assert len(clean_track(track, 640, 480)) > 3


def test_selects_acceleration_and_recovers_g():
    t, y = fall()
    best = select_law(t, y)[0]
    assert best.law == "constant_acceleration"
    assert best.values["a"] == pytest.approx(-9.81, rel=0.03)


def test_selects_damped_oscillation():
    t, y = swing()
    best = select_law(t, y)[0]
    assert best.law == "damped_oscillation"
    assert best.derived["period_s"] == pytest.approx(2 * np.pi / 4, rel=0.01)


def test_does_not_overfit_straight_line():
    t = np.arange(40) / 30
    assert select_law(t, noisy(0.7 * t + 0.2))[0].law == "constant_velocity"


def test_verify_passes_true_law_on_new_conditions():
    fit = fit_law("constant_acceleration", *fall())
    verdict = verify(fit, *fall(v0=-0.4, n=34))
    assert verdict.passed, verdict.reason


def test_verify_fails_when_the_law_changes():
    fit = fit_law("constant_acceleration", *fall())
    verdict = verify(fit, *fall(g=6.0))
    assert not verdict.passed
    assert verdict.constants["a"]["agrees"] is False


def test_verify_oscillation_with_different_amplitude():
    fit = fit_law("damped_oscillation", *swing())
    assert verify(fit, *swing(amp=0.1, phase=1.2)).passed
    assert not verify(fit, *swing(omega=5.5)).passed


def test_zigzag_data_is_flagged():
    t = np.arange(30) / 60
    y = -0.5 * 9.81 * t**2
    swapped = y.copy()
    swapped[::2], swapped[1::2] = y[1::2], y[::2]
    series = Series(t, np.zeros(30), swapped)
    assert any("zigzag" in w for w in quality_warnings(series, "y", 30))
    assert quality_warnings(Series(t, np.zeros(30), y), "y", 30) == []


def test_ledger_blocks_and_persists(tmp_path):
    path = tmp_path / "spend.json"
    ledger = Ledger(path, limit_usd=0.02)
    ledger.record(sam_cost(50))
    with pytest.raises(BudgetExceeded):
        ledger.check(0.02)
    assert Ledger(path, 0.02).spent == pytest.approx(0.01)


def test_visitor_limit_window():
    limiter = VisitorLimiter(2, 60)
    limiter.hit("a", now=0)
    limiter.hit("a", now=1)
    with pytest.raises(RateLimited):
        limiter.hit("a", now=2)
    limiter.hit("b", now=2)
    limiter.hit("a", now=100)
