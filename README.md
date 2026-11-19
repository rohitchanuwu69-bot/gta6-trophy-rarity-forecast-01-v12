# Trophy Dilution Forecaster v12

[![make.fun](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/rohitchanuwu69-bot/gta6-trophy-rarity-forecast-01-v12/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/rohitchanuwu69-bot/gta6-trophy-rarity-forecast-01-v12/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)

Bounty: [gta6-trophy-rarity-forecast-01 on make.fun](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)

Forecasts each Grand Theft Auto VI PlayStation 5 trophy's earn rate on
Exophase at the target time, as five quantiles per trophy.

## How it works

When the history is flat, the page is stale, so the forecast models the
refresh itself: earned counts are carried in whole players, the tracked
player count grows by the documented first-refresh factor, and the median
credits a small whole-player gain to the early trophies plus a modest
newcomer gain to the fastest ones. When the history moves, separate
log-time growth fits of tracked players and earned counts give the
median as their ratio. Spreads stay wide on purpose: with only a handful
of players per trophy, one or two players is a large logit move.

## Run

    python3 main.py

Reads every case file from $MAKEFUN_INPUT_DIR (else /input) and writes
one forecast per case to $MAKEFUN_OUTPUT_DIR (else /output). Python 3.13
standard library only, no network access. Deterministic.

## License

MIT — see LICENSE.
