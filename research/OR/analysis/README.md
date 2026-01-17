# Analysis

This folder contains scripts that analyze and visualize benchmark results produced by `benchmark_algorithms.py`.

## Files
- `benchmark_algorithms.py`: Runs grid searches across algorithms and parameters, saving results to CSV/JSON.
- `benchmark_results.json`: JSON output with metadata and per-run results.
- `benchmark_results.csv`: Flat CSV output for quick inspection.
- `visualize_algorithms.py`: Generates heatmaps, comparisons, and sensitivity plots from JSON results.
- `visualize_trajectories.py`: Optional trajectory visualization (if present in results).

## Typical workflow
1) Run benchmarks (partial runs are supported):
```bash
python3 benchmark_algorithms.py --quick
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
- `--algo` (`all` or comma-separated: `mpc_simplemove,mpc_realmove,beam_realmove`)
- `--order` (`shuffle` or comma-separated algo order, e.g. `mpc_simplemove,mpc_realmove,beam_realmove`)
- `--quick` (reduced parameter ranges for fast runs)
- `--resume` (continue from previous JSON results)
- `--save-interval` (`10`)
- fixed params: `goal=20`, `start_index=600`, `near_threshold=200`, `near_delay=10`, `far_delay=20`

`visualize_algorithms.py` uses:
- `--input` (`benchmark_results.json`)
- `--output-dir` (`.`)

## Example output
From `benchmark_algorithms.py`:
```
[12/640] mpc_realmove h=300 ta=43 a=1.0 bw=- -> OK (ETA: 420s)
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
Common outputs (all PNG):
- `heatmap_<algo>_<param>_vs_<param>_mean_total_sailed.png`
- `heatmap_<algo>_<param>_vs_<param>_median_total_sailed.png`
- `heatmap_<algo>_<param>_vs_<param>_min_total_sailed.png`
- `heatmap_<algo>_<param>_vs_<param>_mean_elapsed_time.png`
- `heatmap_<algo>_<param>_vs_<param>_median_elapsed_time.png`
- `compare_total_sailed_mean.png`
- `compare_total_sailed_median.png`
- `compare_total_sailed_min.png`
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
- `summary_results_table.png`

When a tackangle=43 slice is generated, the same outputs are created with a `ta43_` prefix:
- `ta43_<same filename>.png`
- `ta43_summary_results.csv`
- If a ta43 heatmap collapses to a single row/column, it is rendered as a 1D line plot with the same filename.
- Tackangle-specific plots are omitted for ta43 slices (e.g. `ta43_exec_time_vs_tackangle_*`, `ta43_sensitivity_tackangle_*`,
  `ta43_scatter_*_vs_tackangle_*`, `ta43_unfinished_rate_compare_tackangle_*`).

## Notes
- Visualizations only consider finished races (`distance_to_mark <= goal`).
- If the benchmark run was interrupted, the visualizer still works as long as there are finished runs.
