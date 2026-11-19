#!/usr/bin/env python3
"""Trophy Dilution Forecaster v12.

Forecasts each PlayStation 5 trophy's earn rate on Exophase for Grand Theft
Auto VI at a case's target time, as five quantiles (5/25/50/75/95) of the
rate as the page prints it, to 2 decimals.

Two regimes, chosen per case from its own history:

Flat history (every read identical, e.g. launch night before the first
refresh): the page is stale, so the forecast models the refresh itself.
Earned counts are carried in whole players with half-up rounding. The
target player count is the last count grown by the documented first
refresh factor. The median adds a small whole-player gain for the first
thirty trophies in list order plus a rate-proportional newcomer gain for
the trophies whose last rates are among the top three distinct sub-100
values. The spread is wide on purpose: with earned counts of only a few
players, plus or minus one or two players is a large logit move, and the
live practice scores showed a wide spread beats a tight one.

Moving history: separate least-squares growth fits of log tracked players
and log earned counts against log time since release; the ratio is the
median. The spread grows with horizon and fit residual, and never falls
below the count-noise floor.

Only the Python 3.13 standard library is used. No network access.
Reads every *.in in $MAKEFUN_INPUT_DIR (else /input) and writes one
*.out per case to $MAKEFUN_OUTPUT_DIR (else /output).
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

# Standard normal quantiles at the five output levels.
Z_VALUES = [-1.6448536269514722, -0.6744897501960817, 0.0,
            0.6744897501960817, 1.6448536269514722]
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# Documented first refresh of the game's counts (RULES.txt): tracked
# players grew from 638 to 3868 while every rate but 100% fell. The
# flat regime reuses that growth factor, never an absolute player count.
REFRESH_GROWTH = 3868.0 / 638.0
# Whole-player gain credited to the first thirty trophies in list order
# in the flat regime (early trophies pick up a couple of new earners).
EARLY_GAIN_PLAYERS = 2
EARLY_TROPHY_COUNT = 30
# Newcomer earn fraction for the fastest trophies in the flat regime.
FAST_EARN_FRACTION = 0.20
# Spread on the logit scale, measured as the q95 minus q05 distance.
BASE_SPREAD = 0.30
MAX_FLAT_SPREAD = 0.80
MAX_SPREAD = 1.10
# The count-noise floor: plus or minus this many players of earned-count
# noise must fit inside the [q05, q95] band.
NOISE_PLAYERS = 2.0


def half_up(x):
    """Round half up to the nearest whole number."""
    return math.floor(x + 0.5)


def round_two(x):
    """Round half up to two decimals (the page prints 2 decimals)."""
    return math.floor(x * 100.0 + 0.5) / 100.0


def clamp(x, low, high):
    if x < low:
        return low
    if x > high:
        return high
    return x


def logit_of_percent(rate):
    """Logit of a percent rate, clamped so 0 and 100 have a logit."""
    p = clamp(rate, 0.01, 99.99) / 100.0
    return math.log(p / (1.0 - p))


def percent_of_logit(value):
    return 100.0 / (1.0 + math.exp(-value))


def parse_time(text):
    """Parse an ISO timestamp or a plain date as UTC-aware datetime."""
    if not text:
        return None
    text = text.strip()
    if len(text) == 10:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def least_squares(xs, ys):
    """Least-squares line through (x, y); returns slope, intercept, resid std."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        return 0.0, mean_y, 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
    intercept = mean_y - slope * mean_x
    if n > 2:
        resid = math.sqrt(sum((y - (slope * x + intercept)) ** 2
                              for x, y in zip(xs, ys)) / (n - 2))
    else:
        resid = 0.0
    return slope, intercept, resid


def count_noise_spread(median_rate, target_players, noise_players=NOISE_PLAYERS):
    """Total logit spread needed so the band covers +/- noise_players.

    A change of a few players moves a rare trophy's logit a long way,
    because its earned count is only a handful of players.
    """
    p = clamp(median_rate, 0.01, 99.99) / 100.0
    if target_players <= 0 or p <= 0.0 or p >= 1.0:
        return BASE_SPREAD
    one_sided = noise_players / (target_players * p * (1.0 - p))
    return clamp(2.0 * one_sided, BASE_SPREAD, MAX_FLAT_SPREAD)


def quantiles_from_median(median_rate, total_spread):
    """Five quantiles around a median rate on the logit scale, 2 decimals."""
    if median_rate >= 100.0:
        return [100.0, 100.0, 100.0, 100.0, 100.0]
    centre = logit_of_percent(median_rate)
    step = total_spread / 2.0 / 1.6448536269514722
    out = []
    running = 0.01
    for z in Z_VALUES:
        value = round_two(percent_of_logit(centre + z * step))
        value = clamp(value, 0.01, 99.99)
        if value < running:
            value = running
        running = value
        out.append(value)
    return out


def history_is_flat(history):
    """True when every read shows the same players and the same rates."""
    if not history:
        return True
    first = history[0]
    for read in history[1:]:
        if read.get("players_tracked") != first.get("players_tracked"):
            return False
        if read.get("rates") != first.get("rates"):
            return False
    return True


def flat_forecast(last, trophies, target_players):
    """Median rates and spreads for a stale, flat history."""
    rates = last["rates"]
    last_players = last["players_tracked"]
    newcomers = max(0.0, target_players - last_players)
    distinct = sorted({r for r in rates if r < 100.0}, reverse=True)
    fast_rates = set(distinct[:3])
    rows = []
    for index, trophy in enumerate(trophies):
        rate = rates[index]
        if rate >= 100.0:
            rows.append((trophy["id"], 100.0, BASE_SPREAD))
            continue
        earned = half_up(rate / 100.0 * last_players)
        gain = EARLY_GAIN_PLAYERS if index < EARLY_TROPHY_COUNT else 0
        noise = NOISE_PLAYERS
        if rate in fast_rates:
            bump = half_up(newcomers * rate / 100.0 * FAST_EARN_FRACTION)
            gain += bump
            # The newcomer fraction is the least certain part of the
            # median: if it is off by ten points either way, the bump
            # moves by half its size, so widen the band by that much.
            noise += bump / 2.0
        median = 100.0 * (earned + gain) / target_players
        spread = count_noise_spread(median, target_players, noise)
        rows.append((trophy["id"], median, spread))
    return rows


def moving_forecast(case, trophies):
    """Median rates and spreads from log-time growth fits.

    Returns None when the history is too short to fit, so the caller
    can fall back to the flat regime.
    """
    history = case["history"]
    if len(history) < 3:
        return None
    release = parse_time(case["game"].get("release_date"))
    target = parse_time(case.get("target"))
    if release is None or target is None:
        return None
    xs = []
    players_log = []
    earned_log = []
    for read in history:
        moment = parse_time(read.get("at") or read.get("slot"))
        if moment is None:
            continue
        hours = max(0.0, (moment - release).total_seconds() / 3600.0)
        xs.append(math.log1p(hours))
        players_log.append(math.log(max(1.0, read["players_tracked"])))
        earned_log.append([math.log(max(0.5, rate / 100.0
                                       * read["players_tracked"]))
                           for rate in read["rates"]])
    if len(xs) < 3:
        return None
    horizon_days = max(0.0, (target - parse_time(history[-1].get("at")
                          or history[-1].get("slot"))).total_seconds() / 86400.0)
    target_x = math.log1p(max(0.0, (target - release).total_seconds()
                              / 3600.0))
    slope_p, intercept_p, resid_p = least_squares(xs, players_log)
    players_target = math.exp(slope_p * target_x + intercept_p)
    if players_target <= 0.0:
        return None
    rows = []
    for index, trophy in enumerate(trophies):
        last_rate = history[-1]["rates"][index]
        if last_rate >= 100.0:
            rows.append((trophy["id"], 100.0, BASE_SPREAD))
            continue
        series = [row[index] for row in earned_log]
        slope_e, intercept_e, resid_e = least_squares(xs, series)
        earned_target = math.exp(slope_e * target_x + intercept_e)
        median = clamp(100.0 * earned_target / players_target, 0.01, 99.99)
        spread = (BASE_SPREAD + 0.25 * math.sqrt(horizon_days)
                  + resid_e + resid_p)
        spread = max(spread, count_noise_spread(median, players_target))
        spread = clamp(spread, BASE_SPREAD, MAX_SPREAD)
        rows.append((trophy["id"], median, spread))
    return rows


def forecast_case(case):
    """Forecast one case; returns the output document for it."""
    trophies = case["trophies"]
    history = case["history"]
    last = history[-1]
    if history_is_flat(history):
        target_players = last["players_tracked"] * REFRESH_GROWTH
        rows = flat_forecast(last, trophies, target_players)
    else:
        rows = moving_forecast(case, trophies)
        if rows is None:
            target_players = last["players_tracked"] * REFRESH_GROWTH
            rows = flat_forecast(last, trophies, target_players)
    out = {"trophies": []}
    for trophy_id, median, spread in rows:
        out["trophies"].append({"id": trophy_id,
                                "q": quantiles_from_median(median, spread)})
    return out


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(name for name in os.listdir(input_dir)
                   if name.endswith(".in"))
    for name in names:
        with open(os.path.join(input_dir, name), "r",
                  encoding="utf-8") as handle:
            case = json.load(handle)
        result = forecast_case(case)
        out_name = name[:-3] + ".out"
        with open(os.path.join(output_dir, out_name), "w",
                  encoding="utf-8") as handle:
            json.dump(result, handle, separators=(",", ":"))
            handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
