# MPC (Offline Planners)

This folder contains offline Model Predictive Control (MPC) planners for the WindGame.
Each script simulates a receding-horizon tack/no-tack planner that minimizes sailed
distance while reaching the mark.

## What they do
- Load wind direction/speed from a `--wind` JSON file.
- At each time step, compare two options:
  - keep the current tack
  - tack immediately
- For each option, simulate a short horizon and compute a cost:
  - `cost = traveled_distance + alpha * distance_to_mark`
- Choose the lower-cost option, advance one step, and repeat.

## Scripts

### mpc_simplemove.py
Simplified movement model:
- Heading is `wind_direction +/- tackangle`.
- Speed is `windspeed / 2.2` meters per second (same as the game).
- No layline clipping, no tack delay, no tack speed penalty.

### mpc_realmove.py
Game-like movement model:
- Layline clamping against the bearing to mark.
- Tack delay (with distance-based adjustment).
- 10-second speed reduction after a tack.
- Uses the same speed conversion (`windspeed / 2.2`).

## Usage
Run the commands from inside `research/OR`:
```bash
python3 mpc_simplemove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.3814282 --start-lng -64.5666047 \
  --finish-lat 18.4085703 --finish-lng -64.5333926
```

```bash
python3 mpc_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.3814282 --start-lng -64.5666047 \
  --finish-lat 18.4085703 --finish-lng -64.5333926
```

### Detailed examples
```bash
python3 mpc_simplemove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.3814282 --start-lng -64.5666047 \
  --finish-lat 18.4085703 --finish-lng -64.5333926 \
  --horizon 90 \
  --tackangle 43 \
  --goal 15 \
  --alpha 1.2
```

```bash
python3 mpc_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.3814282 --start-lng -64.5666047 \
  --finish-lat 18.4085703 --finish-lng -64.5333926 \
  --horizon 90 \
  --tackangle 43 \
  --goal 15 \
  --alpha 1.2 \
  --near-threshold 200 \
  --near-delay 10 \
  --far-delay 20
```

## Key parameters
- `--horizon`: lookahead window (seconds).
- `--tackangle`: tack angle in degrees (default 43).
- `--goal`: stop when distance to mark is below this threshold (meters).
- `--alpha`: weight for remaining distance in the cost function.
- `--near-threshold`, `--near-delay`, `--far-delay` (real move only): tack delay tuning.

## Output
- `steps`: number of simulated steps.
- `distance_to_mark`: final distance to the mark.
- `total_sailed`: total sailed distance in meters.
- `tacks`: list of tack decisions in the game format (`P123` or `S123`).
- `total X tack decisions`: total count of tack events in the log.

## Notes
- These are offline analysis tools, not integrated into the game loop.
- `mpc_realmove.py` mirrors the in-game logic more closely.
