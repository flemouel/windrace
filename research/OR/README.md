# OR (Offline Planners)

This folder contains offline Operation Research (OR) planners for the WindGame,
including MPC, beam search, and ADP. Each script simulates tack/no-tack planning
that minimizes sailed distance while reaching the mark.

## What they do
- Load wind direction/speed from a `--wind` JSON file.
- At each time step, compare two options:
  - keep the current tack
  - tack immediately
- For each option, simulate a short horizon and compute a cost:
  - `cost = traveled_distance + alpha * distance_to_mark`
- Choose the lower-cost option, advance one step, and repeat.

## OR classification (with current algorithms)
- Mathematical optimization (deterministic optimization) *(not used here because the game dynamics are nonlinear with discrete tack decisions, making exact formulations heavy in practice)*
  - *Linear Programming (LP)*
  - *Mixed-Integer Linear Programming (MILP)*
  - *Mixed-Integer Programming (MIP)*
  - *Quadratic Programming (QP)*
  - *Mixed-Integer Quadratic Programming (MIQP)*
  - *Nonlinear Programming (NLP)*
  - *Mixed-Integer Nonlinear Programming (MINLP)*
  - *Second-Order Cone Programming (SOCP)*
  - *Semidefinite Programming (SDP)*
- Dynamic programming (sequential decision optimization)
  - *Dynamic Programming (DP) (not used here because of the curse of dimensionality)*
  - Approximate Dynamic Programming (ADP) (here: `adp_realmove.py`)
- Optimal control / planning (receding horizon control)
  - Model Predictive Control (MPC) (here: `mpc_simplemove.py`, `mpc_realmove.py`)
  - *Differential Dynamic Programming (DDP) (not used here because the dynamics are not differentiable due to discrete tack decisions)*
- Constraint programming (combinatorial constraints) *(not used here because the state is continuous and the horizon is long, so a discrete CP model would be overly approximate or too large)*
  - *Constraint Programming (CP)*
  - *Constraint Programming SAT (CP-SAT)*
- Stochastic optimization (uncertainty-aware optimization)
  - Scenario Tree / Stochastic Programming (here: `spst_realmove.py`)
  - *Robust Optimization (not used here)*
  - *Chance-Constrained (not used here)*
  - *SAA (not used here)*
- Heuristic search / meta-heuristics (approximate search)
  - *A* (not used here)*
  - *D* (not used here)*
  - *Iterative Deepening A* (IDA*) (not used here)*
  - *Best-First (not used here)*
  - Beam Search (here: `beam_search.py`, `beam_realmove.py`)
  - *Genetic Algorithms (GA) (not used here)*
  - *Particle Swarm Optimization (PSO) (not used here)*
  - *Simulated Annealing (SA) (not used here)*
  - *Tabu Search (TS) (not used here)*
  - *Greedy Randomized Adaptive Search Procedure (GRASP) (not used here)*
  - *Variable Neighborhood Search (VNS) (not used here)*
  - *Iterated Local Search (ILS) (not used here)*
- Simulation (optimization via repeated runs)
  - *Monte-Carlo Optimization (not used here)*
  - *Stochastic Simulation Optimization (SimOpt) (not used here)*
  - *Response Surface Methodology (RSM) (not used here)*
- Decomposition & advanced methods (large-scale decomposition) *(not used here because there is no clear separable structure into master/subproblems in this sequential dynamics)*
  - *Benders*
  - *Column Generation*
  - *Lagrangian Relaxation*
  - *Branch-and-Bound / Branch-and-Cut*

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

### beam_search.py
Global search approximation:
- Explores tack/no-tack branches each step.
- Keeps the best K states (beam width).
- Uses the same movement logic as `mpc_realmove.py`.

### adp_realmove.py
Approximate Dynamic Programming baseline:
- Two actions (keep vs tack) with mini-horizon lookahead.
- Value-function approximation (linear, polynomial, or small network).
- Optional epsilon-greedy exploration.
- Uses the same movement logic as `mpc_realmove.py`.

## Usage
Run the commands from inside `research/OR`:
```bash
python3 mpc_simplemove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
```

```bash
python3 mpc_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
```

```bash
python3 beam_search.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
```

```bash
python3 adp_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
```

```bash
python3 spst_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
```

### Detailed examples
```bash
python3 mpc_simplemove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
  --horizon 90 \
  --tackangle 43 \
  --goal 20 \
  --alpha 1.2 \
  --start-index 600
```

```bash
python3 mpc_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
  --start-index 600 \
  --horizon 90 \
  --tackangle 43 \
  --goal 20 \
  --alpha 1.2 \
  --near-threshold 200 \
  --near-delay 10 \
  --far-delay 20 \
  --verbose 2
```

```bash
python3 beam_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
  --horizon 5401 \
  --tackangle 43 \
  --goal 20 \
  --alpha 0 \
  --near-threshold 200 \
  --near-delay 10 \
  --far-delay 20 \
  --beam-width 200 \
  --start-index 600
```

```bash
python3 spst_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
  --start-index 600 \
  --horizon 90 \
  --tackangle 43 \
  --goal 20 \
  --alpha 1.2 \
  --near-threshold 200 \
  --near-delay 10 \
  --far-delay 20 \
  --scenarios 7 \
  --dir-noise 6 \
  --speed-noise 0.1 \
  --seed 42 \
  --verbose 2
```

```bash
python3 adp_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
  --start-index 600 \
  --tackangle 43 \
  --goal 20 \
  --alpha 1.2 \
  --goal-penalty 50 \
  --near-threshold 200 \
  --near-delay 10 \
  --far-delay 20 \
  --lookahead 120 \
  --epsilon 0.05 \
  --approx linear \
  --normalize-features \
  --verbose 2
```

### Verbose output
```bash
python3 mpc_realmove.py \
  --wind ../../winddata/wind_data.json \
  --start-lat 18.38142820098676 \
  --start-lng -64.56660471988445 \
  --finish-lat 18.40857035782242 \
  --finish-lng -64.53339266400592 \
  --horizon 90 \
  --tackangle 43 \
  --goal 20 \
  --alpha 1.2 \
  --verbose 2
```

## Key parameters
- `--horizon`: lookahead window (seconds).
- `--tackangle`: tack angle in degrees (default 43).
- `--goal`: stop when distance to mark is below this threshold (meters).
- `--alpha`: weight for remaining distance in the cost function.
- `--start-index`: starting index in the wind data trace (default 0). Allows planning from a specific point in the wind history.
- `--near-threshold`, `--near-delay`, `--far-delay` (real move only): tack delay tuning.
- `--beam-width` (beam search only): number of states kept per step.
- `--goal-penalty` (ADP only): extra weight on distance-to-mark inside the lookahead cost.
- `--lookahead` (ADP only): mini-horizon for evaluating keep/tack.
- `--epsilon`, `--epsilon-decay`, `--epsilon-min` (ADP only): exploration settings.
- `--approx` (ADP only): value-function approximation (`linear`, `poly`, `network`).
- `--l2` (ADP only): L2 regularization on value weights.
- `--hidden-size` (ADP only): hidden size for `network` approximation.
- `--normalize-features` (ADP only): normalize angle features to [0, 1].
- `--verbose`: `0` (quiet), `1` (summary), `2` (summary + trajectory).

## Output
- `steps`: number of simulated steps.
- `distance_to_mark`: final distance to the mark.
- `total_sailed`: total sailed distance in meters.
- `tacks`: list of tack decisions in the game format (`P123` or `S123`).
- `total X tack decisions`: total count of tack events in the log.
- `trajectory` (verbose level 2): one line per step, `index decision lat lng` (`KEEP`, `P`, `S`).

## Notes
- These are offline analysis tools, not integrated in real-time into the game loop, just trajectories computed before the race start.
