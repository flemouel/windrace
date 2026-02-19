# Analysis

This folder contains scripts that analyze and visualize benchmark results produced by `benchmark_algorithms.py`.

## Files
- `benchmark_algorithms.py`: Runs benchmark campaigns across algorithms and parameters (full grid or adaptive `space-search`), saving results to CSV/JSON.
- `visualize_algorithms.py`: Generates heatmaps, comparisons, sensitivity plots, execution-time charts, unfinished-rate visuals, and coverage-dispersion summaries from JSON results.
- `extract_trajectories.py`: Extracts planned/sailed trajectories from logs for comparison and visualization.
- `compare_trajectories.py`: Compares planned vs sailed trajectories (if extracted trajectories are available).
- `visualize_trajectories.py`: Optional trajectory visualization (if present in results).

## Typical workflow - trajectories comparison
1) Extract trajectories from logs:
```bash
python3 extract_trajectories.py --input ../../logs/frontend.log --output trajectories.json
```

2) Compare planned vs sailed:
```bash
python3 compare_trajectories.py --input trajectories.json --output-dir .
```

3) Visualize trajectories (if available in the extracted data):
```bash
python3 visualize_trajectories.py --input trajectories.json --output-dir .
```

## Parameters
`extract_trajectories.py` uses:
- `--input` (log file, e.g. `../../logs/frontend.log`)
- `--output` (`trajectories.json`)
- `--method` (`mpc`, `beam`, or `all`)

`compare_trajectories.py` uses:
- `--input` (`trajectories.json`)
- `--output-dir` (`.`)

`visualize_trajectories.py` uses:
- `--input` (`trajectories.json`)
- `--output-dir` (`.`)
- `--display` (show figures after saving)

## Example output
From `extract_trajectories.py`:
```
Processing .../logs/frontend.log...
  MPC Planned Trajectory (2026-01-26 00:58:22):
    Steps: 900 to 2636 (1737 points)
```

From `compare_trajectories.py`:
```
Comparing trajectories...
  MPC planned vs sailed: mean deviation = 12.4 m
```

From `visualize_trajectories.py`:
```
Saved trajectory plot to trajectories_mpc.png
```

## Output files
Trajectory outputs:
- `trajectories.json`
- `trajectories_<method>.png`
- `compare_trajectories_<method>.png`

## Typical workflow - algorithms benchmarking
1) Run benchmarks (partial runs are supported):
```bash
python3 benchmark_algorithms.py --algo spst_realmove --order quota-window-coverage --workers 12 --resume
```

2) Generate visualizations:
```bash
python3 visualize_algorithms.py --input benchmark_results.json --output-dir .
```

## Parameters
`benchmark_algorithms.py` supports common options:
- `--output` (`benchmark_results.csv`)
- `--json-output` (`benchmark_results.json`)
- `--workers` (`12`)
- `--algo` (`all` or comma-separated: `adp_realmove,beam_realmove,mpc_realmove,mpc_simplemove,spst_realmove`)
- `--order` (`quota-window-coverage` by default: local greedy per algo + windowed merge with per-algo quotas and head gain selection; stratified across chunks with workers, `global-coverage` = global greedy coverage ordering, `shuffle` = random across algos/params, or comma-separated algo list with sequential params per algo, e.g. `adp_realmove,spst_realmove`)
- `--resume` (continue from previous JSON results)
- `--save-interval` (`10`)
- `--verbose` (`0` = summary, `1` = details)
- `--window-size` (`500`): window size used by `quota-window-coverage` and ETA EWMA (`alpha = 2/(W+1)`)
- `--search-mode` (`grid` or `space-search`)
- `--space-coarse-step` (`4`)
- `--space-refine-step` (`2`)
- `--space-eta` (`3`)
- `--space-early-stop-delta` (`0.0`)

- fixed params: `goal=20`, `start_index=600`, `tackangle=43`, `near_threshold=200`, `near_delay=10`, `far_delay=20`, `seed=42`
- parameter ranges live in `PARAM_RANGES`:
  `gamma`, `lr`, `goal_penalty`, `epsilon`, `epsilon_decay`, `epsilon_min`, `approx`, `hidden_size`, `l2`, `normalize_features` for `adp_realmove`,
  add `beam_width` for `beam_realmove`,
  add `horizon` + `alpha` for `mpc_simplemove`/`mpc_realmove`,
  add `scenarios`, `dir_noise`, `speed_noise` for `spst_realmove`.

`visualize_algorithms.py` uses:
- `--input` (`benchmark_results.json`)
- `--output-dir` (`.`)
- `--display` (show figures after saving)

## Example output
From `benchmark_algorithms.py`:
```
Filtering completed tests from 1190540 cases...
  filter progress [████████████████████] 16/16 chunks (100%)
Ordering 1083456 cases with stratified 15 chunks (workers=15)...
  shuffle global [████████████████████] 100%
  chunk dispatch [████████████████████] 100%
  window-based coverage chunks + warmup [████████████████████] 16/16 (100%) 9.5s
Running 1083456 test cases with 15 workers...
[██░░░░░░░░░░░░░░░░░░]  10.9% | adp:36417/583680 | spst:91874/597740 | ETA: 315.6h (p50:153.6h p90:1068.9h) | run [░░░░░░░░░░░░░░░░░░░░]   0.0% 46/395579 ETA:68.4h
```

From `visualize_algorithms.py`:
```
Loaded 128 finished races (distance_to_mark <= goal)
Generating visualizations...
  Creating heatmaps...
  Creating algorithm comparisons...
  Creating parameter sensitivity plots...
```

## Output files
Common outputs:
- `benchmark_results.json`
- `benchmark_results.csv`
- `summary_results_table.png`
- `compare_total_sailed_mean.png`
- `compare_total_sailed_median.png`
- `compare_total_sailed_min.png`
- `heatmap_<algo>_<param>_vs_<param>_mean_total_sailed.png`
- `heatmap_<algo>_<param>_vs_<param>_median_total_sailed.png`
- `heatmap_<algo>_<param>_vs_<param>_min_total_sailed.png`
- `heatmap_<algo>_<param>_vs_<param>_mean_elapsed_time.png`
- `heatmap_<algo>_<param>_vs_<param>_median_elapsed_time.png`
- `sensitivity_<param>_mean_total_sailed.png`
- `sensitivity_<param>_median_total_sailed.png`
- `sensitivity_<param>_min_total_sailed.png`
- `sensitivity_beam_width_mean_total_sailed.png`
- `sensitivity_beam_width_median_total_sailed.png`
- `sensitivity_beam_width_min_total_sailed.png`
- `exec_time_distribution.png`
- `exec_time_vs_<param>_mean.png`
- `exec_time_vs_<param>_median.png`
- `exec_time_<algo>_<param>_vs_<param>_heatmap_mean.png`
- `exec_time_<algo>_<param>_vs_<param>_heatmap_median.png`
- `exec_time_per_step_mean.png`
- `exec_time_per_step_median.png`
- `exec_time_by_horizon_comparison_mean.png`
- `exec_time_by_horizon_comparison_median.png`
- `beam_total_sailed_heatmap_mean.png`
- `beam_total_sailed_heatmap_median.png`
- `beam_total_sailed_heatmap_min.png`
- `scatter_total_sailed_vs_<param>_by_<param>.png`
- `scatter_elapsed_time_vs_<param>_by_<param>.png`
- `unfinished_rate_heatmap_<algo>_<param>_vs_<param>_mean.png`
- `unfinished_rate_heatmap_<algo>_<param>_vs_<param>_median.png`
- `unfinished_rate_compare_<param>_mean.png`
- `unfinished_rate_compare_<param>_median.png`
- `coverage_dispersion_<algo>.png`
Coverage dispersion metrics:

| Metric | Description |
| --- | --- |
| Mean entropy band (diversity per dimension) | Average per-dimension entropy within the sliding window. |
| Coverage Volume band (unique combos inside window) | Ratio of unique tuples inside the window over the window's possible combos. |
| Effective dimensional coverage progress (Geometric-mean coverage) | Cumulative geometric mean of per-dimension coverage ratios, normalized to finish at 1.0. |
| Coverage imbalance (Gini) | Inequality across per-dimension coverage ratios (0=balanced, 1=uneven). |
| Hyper-rectangle coverage (HRC) | Envelope span across dimensions, normalized to 0–1. |
| Weighted HRC (HRC × geometric mean) | Envelope span weighted by per-dimension coverage. |
| Background zones | K-means (k=2) on smoothed entropy for Space-filling (Exploration) vs Depth-first (Exploitation). |

## Notes
- Visualizations only consider finished races (`distance_to_mark <= goal`).
- If the benchmark run was interrupted, the visualizer still works as long as there are finished runs.
