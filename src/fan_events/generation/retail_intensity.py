"""Build match-day retail intensity multipliers for merged event streams.

The returned callable boosts retail traffic around home kickoffs and, when
enabled, on away-only match days. It is pure computation: callers supply match
contexts and the result can be reused anywhere synthetic retail timing needs to
react to the football calendar.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fan_events.generation.v2_calendar import MatchContext, shift_match_context_calendar_years


def _shifted(ctx: MatchContext, k: int) -> MatchContext:
    """Shift one template match context forward by ``k`` calendar years."""
    if k == 0:
        return ctx
    return shift_match_context_calendar_years(ctx, k)


def _kickoff_window_utc(
    hc: MatchContext, k: int, pre_td: timedelta, post_td: timedelta
) -> tuple[datetime, datetime]:
    """Return the UTC kickoff window for one shifted home match context."""
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
    """Build the retail intensity multiplier function used by merged streams.

    Args:
        template_contexts: Match contexts that act as the repeating calendar
            template for future seasons.
        home_match_day_multiplier: Base multiplier applied on home-match days.
        home_kickoff_pre_minutes: Minutes before kickoff that count as the home
            kickoff window.
        home_kickoff_post_minutes: Minutes after kickoff that remain inside the
            home kickoff window.
        home_kickoff_extra_multiplier: Additional multiplier layered on top of
            the home-match-day multiplier during the kickoff window.
        away_match_day_enable: Whether away-only local match days should receive
            a separate multiplier.
        away_match_day_multiplier: Multiplier used on away-only local dates when
            enabled.

    Returns:
        Callable mapping a UTC datetime to a retail intensity factor ``F >= 1``.

    Note:
        Kickoff windows are evaluated in UTC, while broader home and away match
        days are evaluated in each context row's local timezone.
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
        """Return a small range of season indices to check around the approximate year delta.

        Uses the individual kickoff's UTC year (not the season start year), so cross-year
        matches (e.g., a Jan match in an Aug-May season) each compute their own delta
        correctly. The ``[-1, +3)`` window provides a safety margin for year-boundary edge
        cases without unbounded iteration.
        """
        approx_k = max(0, tu.year - base_kickoff_utc.year)
        return range(max(0, approx_k - 1), approx_k + 3)

    def factor_at(t: datetime) -> float:
        tu = t.astimezone(timezone.utc)

        # Phase 1: kickoff windows take precedence because they represent the
        # sharpest retail spike and should short-circuit broader day rules.
        for hc, _z in home_ctx_zones:
            for k in _approx_k_range(hc.kickoff_utc, tu):
                w0, w1 = _kickoff_window_utc(hc, k, pre_td, post_td)
                if w1 < tu:
                    continue
                if w0 > tu:
                    break
                if w0 <= tu <= w1:
                    return max(1.0, H * E)

        # Phase 2: if the instant lands on a local home-match date but outside
        # the kickoff spike, apply the broader home-match-day uplift.
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

        # Phase 3: away-only local dates are a fallback so home fixtures always
        # win when both types of match land on the same local day.
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
