"""Match-day retail intensity factor F(t) for merged stream (feature 006)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fan_events.v2_calendar import MatchContext, shift_match_context_calendar_years


def _shifted(ctx: MatchContext, k: int) -> MatchContext:
    if k == 0:
        return ctx
    return shift_match_context_calendar_years(ctx, k)


def _kickoff_window_utc(
    hc: MatchContext, k: int, pre_td: timedelta, post_td: timedelta
) -> tuple[datetime, datetime]:
    sk = _shifted(hc, k)
    ku = sk.kickoff_utc
    return (ku - pre_td, ku + post_td)


def build_retail_rate_factor_fn(
    template_contexts: list[MatchContext],
    *,
    home_match_day_multiplier: float,
    home_kickoff_pre_minutes: int,
    home_kickoff_post_minutes: int,
    home_kickoff_extra_multiplier: float,
    away_match_day_enable: bool,
    away_match_day_multiplier: float,
) -> Callable[[datetime], float]:
    """
    Return ``f(t_utc) -> F`` with ``F >= 1`` per retail-intensity-006.

    Kickoff windows use UTC; home/away **days** use each row's ``timezone`` local calendar date.
    """
    if not template_contexts:
        return lambda _t: 1.0

    H = home_match_day_multiplier
    E = home_kickoff_extra_multiplier
    A = away_match_day_multiplier
    pre_td = timedelta(minutes=home_kickoff_pre_minutes)
    post_td = timedelta(minutes=home_kickoff_post_minutes)

    home_ctxs = [c for c in template_contexts if c.row.get("home_away") == "home"]
    zone_names = {str(c.row["timezone"]) for c in template_contexts}
    # Precompute ZoneInfo objects to avoid recreating them on every factor_at() call.
    zone_cache: dict[str, ZoneInfo] = {zn: ZoneInfo(zn) for zn in zone_names}
    home_ctx_zones: list[tuple[MatchContext, ZoneInfo]] = [
        (hc, zone_cache[str(hc.row["timezone"])]) for hc in home_ctxs
    ]

    def _approx_k_range(base_kickoff_utc: datetime, tu: datetime) -> range:
        """Return a small range of season indices to check around the approximate year delta."""
        approx_k = max(0, tu.year - base_kickoff_utc.year)
        return range(max(0, approx_k - 1), approx_k + 3)

    def factor_at(t: datetime) -> float:
        tu = t.astimezone(timezone.utc)

        # 1) Inside any home kickoff window (UTC), any season pass
        for hc, _z in home_ctx_zones:
            for k in _approx_k_range(hc.kickoff_utc, tu):
                w0, w1 = _kickoff_window_utc(hc, k, pre_td, post_td)
                if w1 < tu:
                    continue
                if w0 > tu:
                    break
                if w0 <= tu <= w1:
                    return max(1.0, H * E)

        # 2) Home match day outside those windows
        for hc, z in home_ctx_zones:
            local_d = tu.astimezone(z).date()
            for k in _approx_k_range(hc.kickoff_utc, tu):
                sk = _shifted(hc, k)
                kd = sk.kickoff_utc.astimezone(z).date()
                if kd > local_d:
                    break
                if kd == local_d:
                    w0, w1 = _kickoff_window_utc(hc, k, pre_td, post_td)
                    if w0 <= tu <= w1:
                        return max(1.0, H * E)
                    return max(1.0, H)

        # 3) Away-only local day (per timezone), when enabled
        if away_match_day_enable:
            for zn, z in zone_cache.items():
                local_d = tu.astimezone(z).date()
                has_home = False
                has_away = False
                for c in template_contexts:
                    if str(c.row["timezone"]) != zn:
                        continue
                    for kk in _approx_k_range(c.kickoff_utc, tu):
                        sk = _shifted(c, kk)
                        kd = sk.kickoff_utc.astimezone(z).date()
                        if kd > local_d:
                            break
                        if kd == local_d:
                            if c.row.get("home_away") == "home":
                                has_home = True
                            else:
                                has_away = True
                            break
                if has_away and not has_home:
                    return max(1.0, A)

        return 1.0

    return factor_at
