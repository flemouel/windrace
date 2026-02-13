#!/usr/bin/env python3
"""
Visualization script for benchmark results.

Generates:
1. Heatmaps: parameter combinations (alpha vs horizon, horizon vs beam-width, etc.)
2. Algorithm comparison: bar charts comparing the algorithms
3. Parameter sensitivity plots
4. Scatter plots: total_sailed vs each parameter

Most plots use finished races (distance_to_mark <= goal).
Some diagnostics compare finished vs unfinished runs.
"""

import argparse
import json
import os
import textwrap

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

# Set style
plt.style.use('seaborn-v0_8-whitegrid')


DISPLAY = False
INPUT_MTIME = None


def apply_prefix(prefix, name):
    return f"{prefix}{name}" if prefix else name


def close_fig():
    if not DISPLAY:
        plt.close()


def render_progress(label, current, total):
    if total <= 0:
        return
    width = 20
    ratio = min(max(current / total, 0.0), 1.0)
    filled = int(round(ratio * width))
    bar = "█" * filled + "░" * (width - filled)
    percent = int(round(ratio * 100))
    print(f"\r  {label} [{bar}] {percent:3d}% ({current}/{total})", end="", flush=True)


def should_skip(filepath):
    if INPUT_MTIME is None:
        return False
    if not os.path.exists(filepath):
        return False
    try:
        return os.path.getmtime(filepath) >= INPUT_MTIME
    except OSError:
        return False


def save_figure(filepath, **kwargs):
    plt.savefig(filepath, **kwargs)
    close_fig()
    return True


ALGO_PARAMS = {
    "mpc_simplemove": ["horizon", "alpha"],
    "mpc_realmove": ["horizon", "alpha"],
    "beam_realmove": ["horizon", "alpha", "beam_width"],
    "spst_realmove": ["horizon", "alpha", "scenarios", "dir_noise", "speed_noise"],
    "adp_realmove": [
        "horizon",
        "alpha",
        "gamma",
        "lr",
        "goal_penalty",
        "epsilon",
        "epsilon_decay",
        "epsilon_min",
        "approx",
        "hidden_size",
        "l2",
        "normalize_features",
    ],
}


def algo_params_union(df):
    algos_present = df["algorithm"].unique()
    params = set()
    for algo in algos_present:
        params.update(ALGO_PARAMS.get(algo, []))
    return list(params)


def load_results(json_path):
    """Load benchmark results from JSON file.

    Returns both finished runs and all runs for extra analysis.
    Works with partial/incomplete benchmark runs.
    """
    with open(json_path, "r") as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    results = data.get("results", [])

    if not results:
        print("WARNING: No results found in file")
        return pd.DataFrame(), metadata

    df_all = pd.DataFrame(results)
    total_results = len(df_all)

    # Only keep successful runs where the race was finished
    df = df_all
    if "success" in df_all.columns:
        df = df[df["success"] == True].copy()
    if "finished" in df_all.columns:
        df = df[df["finished"] == True].copy()

    finished_results = len(df)

    # Add partial results info to metadata
    metadata["_viz_total_results"] = total_results
    metadata["_viz_finished_results"] = finished_results
    metadata["_viz_is_partial"] = metadata.get("interrupted", False) or metadata.get("status") != "completed"

    return df, metadata, df_all


def create_heatmap(df, algo, x_param, y_param, metric, output_dir, fixed_params=None, agg="mean", prefix=""):
    """
    Create a heatmap for a specific algorithm and parameter combination.
    """
    fixed_suffix = "_".join(f"{k}{v}" for k, v in (fixed_params or {}).items())
    filename = f"heatmap_{algo}_{x_param}_vs_{y_param}_{agg}_{metric}"
    if fixed_suffix:
        filename += f"_{fixed_suffix}"
    filename += ".png"
    filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
    if should_skip(filepath):
        return filepath

    algo_df = df[df["algorithm"] == algo].copy()

    if fixed_params:
        for param, value in fixed_params.items():
            if param in algo_df.columns and param not in [x_param, y_param]:
                algo_df = algo_df[algo_df[param] == value]

    if algo_df.empty:
        return None

    # Pivot for heatmap
    pivot = algo_df.pivot_table(
        values=metric,
        index=y_param,
        columns=x_param,
        aggfunc=agg
    )

    if pivot.empty:
        return None

    fig, ax = plt.subplots(figsize=(12, 8))

    # Custom colormap (green = good/low, red = bad/high for distance)
    cmap = LinearSegmentedColormap.from_list("custom", ["#2ecc71", "#f1c40f", "#e74c3c"])

    im = ax.imshow(pivot.values, cmap=cmap, aspect="auto")

    # Labels
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_yticks(range(len(pivot.index)))
    ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.columns])
    ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.index])

    ax.set_xlabel(x_param.replace("_", " ").title())
    ax.set_ylabel(y_param.replace("_", " ").title())

    metric_label = metric.replace("_", " ").title()
    fixed_str = ""
    if fixed_params:
        fixed_str = " | " + ", ".join(f"{k}={v}" for k, v in fixed_params.items())
    ax.set_title(f"Heatmap: {metric_label} ({agg}) — {algo}\n{x_param} vs {y_param}{fixed_str}")

    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label(metric_label)

    # Add text annotations
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                text_color = "white" if val > pivot.values[~np.isnan(pivot.values)].mean() else "black"
                ax.text(j, i, f"{val:.0f}" if val > 10 else f"{val:.2f}",
                        ha="center", va="center", color=text_color, fontsize=8)

    plt.tight_layout()

    # Save
    save_figure(filepath, dpi=150, bbox_inches="tight")
    return filepath


def _coverage_expected_values(metadata, algo, param):
    ranges = (metadata or {}).get("param_ranges", {})
    if param not in ranges:
        return []
    if param == "beam_width" and algo != "beam_realmove":
        return [None]
    return ranges[param]


def create_coverage_heatmap(df_all, metadata, algo, x_param, y_param, output_dir, prefix=""):
    """
    Create coverage heatmap for a specific algorithm and parameter pair.
    Coverage = tested combinations / total possible combinations of remaining params.
    """
    filename = f"coverage_heatmap_{algo}_{x_param}_vs_{y_param}.png"
    filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
    if should_skip(filepath):
        return filepath

    algo_df = df_all[df_all["algorithm"] == algo].copy()
    if algo_df.empty:
        return None

    params = ALGO_PARAMS.get(algo, ["horizon", "alpha", "beam_width"])
    remaining = [p for p in params if p not in (x_param, y_param)]
    remaining_ranges = []
    for p in remaining:
        values = _coverage_expected_values(metadata, algo, p)
        if not values:
            values = sorted(algo_df[p].dropna().unique().tolist())
        remaining_ranges.append(values)

    total_possible = 1
    for values in remaining_ranges:
        total_possible *= max(1, len(values))

    x_values = sorted(algo_df[x_param].dropna().unique().tolist())
    y_values = sorted(algo_df[y_param].dropna().unique().tolist())
    if not x_values or not y_values:
        return None

    grid = np.full((len(y_values), len(x_values)), np.nan)
    for yi, y_val in enumerate(y_values):
        for xi, x_val in enumerate(x_values):
            subset = algo_df[(algo_df[x_param] == x_val) & (algo_df[y_param] == y_val)]
            if subset.empty:
                continue
            tuples = set()
            for _, row in subset.iterrows():
                tuples.add(tuple(row[p] for p in remaining))
            coverage = len(tuples) / total_possible if total_possible else 0
            grid[yi, xi] = coverage

    pivot = pd.DataFrame(grid, index=y_values, columns=x_values)
    if pivot.empty:
        return None

    fig, ax = plt.subplots(figsize=(12, 8))
    cmap = LinearSegmentedColormap.from_list("coverage", ["#e74c3c", "#f1c40f", "#2ecc71"])
    im = ax.imshow(pivot.values, cmap=cmap, aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_yticks(range(len(pivot.index)))
    ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.columns])
    ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.index])
    ax.set_xlabel(x_param.replace("_", " ").title())
    ax.set_ylabel(y_param.replace("_", " ").title())
    ax.set_title(f"Heatmap: Coverage Rate — {algo}\n{x_param} vs {y_param} (% coverage of remaining params)")

    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Coverage Rate (%)")
    cbar.set_ticks([0, 0.25, 0.5, 0.75, 1.0])
    cbar.set_ticklabels(["0%", "25%", "50%", "75%", "100%"])

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val*100:.0f}%", ha="center", va="center", color="black", fontsize=8)

    plt.tight_layout()
    save_figure(filepath, dpi=150, bbox_inches="tight")
    return filepath


def create_algorithm_comparison(df, output_dir, prefix=""):
    """Create bar charts comparing algorithms (total_sailed only)."""
    metric = "total_sailed"
    mean_path = os.path.join(output_dir, apply_prefix(prefix, "compare_total_sailed_mean.png"))
    median_path = os.path.join(output_dir, apply_prefix(prefix, "compare_total_sailed_median.png"))
    min_path = os.path.join(output_dir, apply_prefix(prefix, "compare_total_sailed_min.png"))
    total_plots = 3
    done = 0
    if should_skip(mean_path) and should_skip(median_path) and should_skip(min_path):
        render_progress("algorithm comparisons", total_plots, total_plots)
        print()
        return

    # Group by algorithm and compute stats
    stats = df.groupby("algorithm")[metric].agg(["mean", "std", "min", "max"])
    stats = stats.sort_values("mean")

    colors = {
        "beam_realmove": "#3498db",
        "mpc_realmove": "#e74c3c",
        "mpc_simplemove": "#2ecc71",
        "spst_realmove": "#9b59b6",
        "adp_realmove": "#f39c12",
    }
    bar_colors = [colors.get(algo, "#95a5a6") for algo in stats.index]

    if not should_skip(mean_path):
        fig, ax = plt.subplots(figsize=(10, 6))
        x = range(len(stats))
        bars = ax.bar(x, stats["mean"], yerr=stats["std"], capsize=5, color=bar_colors, alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(stats.index, rotation=15)
        ax.set_ylabel("Total Sailed (m)")
        ax.set_title("Comparison: Total Sailed Distance (mean ± std) — Algorithms")
        # Add value labels
        for i, (bar, mean_val) in enumerate(zip(bars, stats["mean"])):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + stats["std"].iloc[i] + 0.02 * stats["mean"].max(),
                f"{mean_val:.1f}",
                ha="center",
                va="bottom",
                fontsize=10,
            )
        plt.tight_layout()
        save_figure(mean_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("algorithm comparisons", done, total_plots)
    else:
        done += 1
        render_progress("algorithm comparisons", done, total_plots)

    # Median +/- IQR
    if not should_skip(median_path):
        fig, ax = plt.subplots(figsize=(10, 6))
    median_stats = df.groupby("algorithm")[metric].agg(
        median="median",
        q1=lambda s: s.quantile(0.25),
        q3=lambda s: s.quantile(0.75)
    )
    median_stats["iqr"] = median_stats["q3"] - median_stats["q1"]
    median_stats = median_stats.sort_values("median")

    if not should_skip(median_path):
        bar_colors = [colors.get(algo, "#95a5a6") for algo in median_stats.index]
        x = range(len(median_stats))
        bars = ax.bar(x, median_stats["median"], yerr=median_stats["iqr"], capsize=5, color=bar_colors, alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(median_stats.index, rotation=15)
        ax.set_ylabel("Total Sailed (m)")
        ax.set_title("Comparison: Total Sailed Distance (median ± IQR) — Algorithms")
        for i, (bar, median_val) in enumerate(zip(bars, median_stats["median"])):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + median_stats["iqr"].iloc[i] + 0.02 * median_stats["median"].max(),
                f"{median_val:.1f}",
                ha="center",
                va="bottom",
                fontsize=10,
            )
        plt.tight_layout()
        save_figure(median_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("algorithm comparisons", done, total_plots)
    else:
        done += 1
        render_progress("algorithm comparisons", done, total_plots)

    # Best results per algorithm
    if not should_skip(min_path):
        fig, ax = plt.subplots(figsize=(10, 6))

    best_per_algo = df.loc[df.groupby("algorithm")[metric].idxmin()].sort_values(metric)

    bar_colors = [colors.get(algo, "#95a5a6") for algo in best_per_algo["algorithm"]]

    if not should_skip(min_path):
        x = range(len(best_per_algo))
        bars = ax.bar(x, best_per_algo[metric], color=bar_colors, alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(best_per_algo["algorithm"], rotation=15)
        ax.set_ylabel("Total Sailed (m)")
        ax.set_title("Comparison: Best Total Sailed Distance — Algorithms")
        # Add parameter info
        for i, (_, row) in enumerate(best_per_algo.iterrows()):
            params = f"h={row['horizon']}, a={row['alpha']}"
            if row["algorithm"] == "beam_realmove":
                params += f", bw={row['beam_width']}"
            elif row["algorithm"] == "spst_realmove":
                params += f", sc={row['scenarios']}, dn={row['dir_noise']}, sn={row['speed_noise']}"
            elif row["algorithm"] == "adp_realmove":
                params += (
                    f", g={row.get('gamma')}, lr={row.get('lr')}, gp={row.get('goal_penalty')}, "
                    f"e={row.get('epsilon')}, ed={row.get('epsilon_decay')}, emin={row.get('epsilon_min')}, "
                    f"ap={row.get('approx')}, hs={row.get('hidden_size')}, l2={row.get('l2')}, "
                    f"nf={row.get('normalize_features')}"
                )
            wrapped = textwrap.fill(params, width=18)
            ax.text(
                i,
                bars[i].get_height() + 0.01 * best_per_algo[metric].max(),
                f"{row[metric]:.1f}\n({wrapped})",
                ha="center",
                va="bottom",
                fontsize=6,
                rotation=90,
                clip_on=True,
            )
        ax.margins(y=0.25)
        plt.tight_layout()
        save_figure(min_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("algorithm comparisons", done, total_plots)
    else:
        done += 1
        render_progress("algorithm comparisons", done, total_plots)

    print()


def create_parameter_sensitivity(df, output_dir, prefix="", skip_params=None):
    """Create plots showing how each parameter affects total_sailed."""
    params = algo_params_union(df)
    skip_params = skip_params or set()
    metric = "total_sailed"
    algos = df["algorithm"].unique()
    colors = {
        "beam_realmove": "#3498db",
        "mpc_realmove": "#e74c3c",
        "mpc_simplemove": "#2ecc71",
        "spst_realmove": "#9b59b6",
        "adp_realmove": "#f39c12",
    }

    params = [param for param in params if param not in skip_params]
    total_plots = len(params) * 3
    done = 0

    for param in params:
        if param in skip_params:
            continue
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"sensitivity_{param}_mean_total_sailed.png"))
        if should_skip(filepath):
            done += 1
            render_progress("param sensitivity (total_sailed)", done, total_plots)
        else:
            fig, ax = plt.subplots(figsize=(10, 6))

            for algo in algos:
                algo_df = df[df["algorithm"] == algo]
                if param not in algo_df.columns:
                    continue
                grouped = algo_df.groupby(param)[metric].agg(["mean", "std"])

                ax.errorbar(
                    grouped.index,
                    grouped["mean"],
                    yerr=grouped["std"],
                    label=algo,
                    marker="o",
                    color=colors.get(algo, "#95a5a6"),
                    capsize=3
                )

            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Total Sailed (m)")
            ax.set_title(f"Sensitivity: Total Sailed Distance (mean ± std) — {param.replace('_', ' ').title()}")
            ax.legend()

            if param == "horizon":
                ax.set_xscale("log")

            plt.tight_layout()
            save_figure(filepath, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("param sensitivity (total_sailed)", done, total_plots)

        # Median (IQR) total_sailed
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"sensitivity_{param}_median_total_sailed.png"))
        if should_skip(filepath):
            done += 1
            render_progress("param sensitivity (total_sailed)", done, total_plots)
        else:
            fig, ax = plt.subplots(figsize=(10, 6))

            for algo in algos:
                algo_df = df[df["algorithm"] == algo]
                if param not in algo_df.columns:
                    continue
                grouped = algo_df.groupby(param)[metric].agg(
                    median="median",
                    q1=lambda s: s.quantile(0.25),
                    q3=lambda s: s.quantile(0.75)
                )
                grouped["iqr"] = grouped["q3"] - grouped["q1"]

                ax.errorbar(
                    grouped.index,
                    grouped["median"],
                    yerr=grouped["iqr"],
                    label=algo,
                    marker="o",
                    color=colors.get(algo, "#95a5a6"),
                    capsize=3
                )

            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Total Sailed (m)")
            ax.set_title(f"Sensitivity: Total Sailed Distance (median ± IQR) — {param.replace('_', ' ').title()}")
            ax.legend()

            if param == "horizon":
                ax.set_xscale("log")

            plt.tight_layout()
            save_figure(filepath, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("param sensitivity (total_sailed)", done, total_plots)

        # Best (min) total_sailed
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"sensitivity_{param}_min_total_sailed.png"))
        if should_skip(filepath):
            done += 1
            render_progress("param sensitivity (total_sailed)", done, total_plots)
        else:
            fig, ax = plt.subplots(figsize=(10, 6))

            for algo in algos:
                algo_df = df[df["algorithm"] == algo]
                if param not in algo_df.columns:
                    continue
                grouped = algo_df.groupby(param)[metric].agg(["min"])

                ax.plot(
                    grouped.index,
                    grouped["min"],
                    label=algo,
                    marker="o",
                    color=colors.get(algo, "#95a5a6")
                )

            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Total Sailed (m)")
            ax.set_title(f"Sensitivity: Best Total Sailed Distance — {param.replace('_', ' ').title()}")
            ax.legend()

            if param == "horizon":
                ax.set_xscale("log")

            plt.tight_layout()
            save_figure(filepath, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("param sensitivity (total_sailed)", done, total_plots)

    if total_plots > 0:
        print()


def create_execution_time_analysis(df, output_dir, prefix="", skip_heatmaps=None, skip_params=None):
    """Analyze execution times."""
    colors = {
        "beam_realmove": "#3498db",
        "mpc_realmove": "#e74c3c",
        "mpc_simplemove": "#2ecc71",
        "spst_realmove": "#9b59b6",
        "adp_realmove": "#f39c12",
    }

    skip_heatmaps = skip_heatmaps or set()
    skip_params = skip_params or set()
    params = [param for param in algo_params_union(df) if param not in skip_params]
    heatmap_pairs = 0
    for algo in df["algorithm"].unique():
        algo_params = ALGO_PARAMS.get(algo, ["horizon", "alpha"])
        heatmap_pairs += len(algo_params) * (len(algo_params) - 1) // 2
    total_plots = 1 + len(params) * 2 + heatmap_pairs * 2 + 2 + 2
    done = 0

    # 1. Time distribution per algorithm
    dist_path = os.path.join(output_dir, apply_prefix(prefix, "exec_time_distribution.png"))
    algos_present = df["algorithm"].unique()
    if should_skip(dist_path):
        done += 1
        render_progress("execution time plots", done, total_plots)
    else:
        fig, ax = plt.subplots(figsize=(10, 6))
        data_to_plot = [df[df["algorithm"] == algo]["elapsed_time"].dropna() for algo in algos_present]
        colors_list = [colors.get(algo, "#95a5a6") for algo in algos_present]
        bp = ax.boxplot(data_to_plot, patch_artist=True)
        for patch, color in zip(bp["boxes"], colors_list):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        ax.set_xticklabels(algos_present, rotation=15)
        ax.set_ylabel("Execution Time (s)")
        ax.set_title("Distribution: Execution Time — Algorithms")
        plt.tight_layout()
        save_figure(dist_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("execution time plots", done, total_plots)

    # 3. Time vs parameters (generic across all params/algorithms)
    for param in params:
        if param in skip_params:
            continue
        mean_path = os.path.join(output_dir, apply_prefix(prefix, f"exec_time_vs_{param}_mean.png"))
        if should_skip(mean_path):
            done += 1
            render_progress("execution time plots", done, total_plots)
        else:
            fig, ax = plt.subplots(figsize=(10, 6))
            for algo in algos_present:
                algo_df = df[df["algorithm"] == algo]
                if param not in algo_df.columns:
                    continue
                grouped = algo_df.groupby(param)["elapsed_time"].agg(["mean", "std"])
                ax.errorbar(
                    grouped.index,
                    grouped["mean"],
                    yerr=grouped["std"],
                    marker="o",
                    color=colors.get(algo, "#95a5a6"),
                    capsize=3,
                    label=algo,
                )
            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Execution Time (s)")
            ax.set_title(f"Sensitivity: Execution Time (mean ± std) — {param.replace('_', ' ').title()}")
            ax.legend()
            if param == "horizon":
                ax.set_xscale("log")
            plt.tight_layout()
            save_figure(mean_path, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("execution time plots", done, total_plots)

        median_path = os.path.join(output_dir, apply_prefix(prefix, f"exec_time_vs_{param}_median.png"))
        if should_skip(median_path):
            done += 1
            render_progress("execution time plots", done, total_plots)
        else:
            fig, ax = plt.subplots(figsize=(10, 6))
            for algo in algos_present:
                algo_df = df[df["algorithm"] == algo]
                if param not in algo_df.columns:
                    continue
                grouped = algo_df.groupby(param)["elapsed_time"].agg(
                    median="median",
                    q1=lambda s: s.quantile(0.25),
                    q3=lambda s: s.quantile(0.75),
                )
                grouped["iqr"] = grouped["q3"] - grouped["q1"]
                ax.errorbar(
                    grouped.index,
                    grouped["median"],
                    yerr=grouped["iqr"],
                    marker="o",
                    color=colors.get(algo, "#95a5a6"),
                    capsize=3,
                    label=algo,
                )
            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Execution Time (s)")
            ax.set_title(f"Sensitivity: Execution Time (median ± IQR) — {param.replace('_', ' ').title()}")
            ax.legend()
            if param == "horizon":
                ax.set_xscale("log")
            plt.tight_layout()
            save_figure(median_path, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("execution time plots", done, total_plots)

    # 4. Time heatmaps: all parameter pairs per algorithm
    for algo in df["algorithm"].unique():
        algo_df = df[df["algorithm"] == algo]
        params = ALGO_PARAMS.get(algo, ["horizon", "alpha"])
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                if (algo, x_param, y_param) in skip_heatmaps or (algo, y_param, x_param) in skip_heatmaps:
                    continue
                mean_heatmap_path = os.path.join(
                    output_dir,
                    apply_prefix(prefix, f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_mean.png")
                )
                if should_skip(mean_heatmap_path):
                    done += 1
                    render_progress("execution time plots", done, total_plots)
                else:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    if not algo_df.empty:
                        pivot = algo_df.pivot_table(
                            values="elapsed_time",
                            index=y_param,
                            columns=x_param,
                            aggfunc="mean"
                        )
                        im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto")
                        ax.set_xticks(range(len(pivot.columns)))
                        ax.set_yticks(range(len(pivot.index)))
                        ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.columns], rotation=45)
                        ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.index])
                        ax.set_xlabel(x_param.replace("_", " ").title())
                        ax.set_ylabel(y_param.replace("_", " ").title())
                        ax.set_title(f"Heatmap: Execution Time (mean) — {algo}")
                        plt.colorbar(im, ax=ax, label="Time (s)")
                        for row in range(len(pivot.index)):
                            for col in range(len(pivot.columns)):
                                val = pivot.values[row, col]
                                if not np.isnan(val):
                                    text_color = "white" if val > pivot.values.max() * 0.5 else "black"
                                    ax.text(col, row, f"{val:.1f}", ha="center", va="center", fontsize=7, color=text_color)
                    else:
                        ax.text(0.5, 0.5, f"No {algo} data", ha="center", va="center", transform=ax.transAxes)
                        ax.set_title(f"Heatmap: Execution Time (mean) — {algo}")
                    plt.tight_layout()
                    save_figure(mean_heatmap_path, dpi=150, bbox_inches="tight")
                    done += 1
                    render_progress("execution time plots", done, total_plots)

                median_heatmap_path = os.path.join(
                    output_dir,
                    apply_prefix(prefix, f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_median.png")
                )
                if should_skip(median_heatmap_path):
                    done += 1
                    render_progress("execution time plots", done, total_plots)
                    continue
                if not algo_df.empty:
                    pivot = algo_df.pivot_table(
                        values="elapsed_time",
                        index=y_param,
                        columns=x_param,
                        aggfunc="median"
                    )
                    if pivot.empty:
                        done += 1
                        render_progress("execution time plots", done, total_plots)
                        continue
                    fig, ax = plt.subplots(figsize=(10, 6))
                    im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto")
                    ax.set_xticks(range(len(pivot.columns)))
                    ax.set_yticks(range(len(pivot.index)))
                    ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.columns], rotation=45)
                    ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.index])
                    ax.set_xlabel(x_param.replace("_", " ").title())
                    ax.set_ylabel(y_param.replace("_", " ").title())
                    ax.set_title(f"Heatmap: Execution Time (median) — {algo}")
                    plt.colorbar(im, ax=ax, label="Time (s)")
                    for row in range(len(pivot.index)):
                        for col in range(len(pivot.columns)):
                            val = pivot.values[row, col]
                            if not np.isnan(val):
                                text_color = "white" if val > pivot.values.max() * 0.5 else "black"
                                ax.text(col, row, f"{val:.1f}", ha="center", va="center", fontsize=7, color=text_color)
                    plt.tight_layout()
                    save_figure(median_heatmap_path, dpi=150, bbox_inches="tight")
                    done += 1
                    render_progress("execution time plots", done, total_plots)

    # === Figure 3: Algorithm comparison - time efficiency ===
    # Time per step (efficiency)
    per_step_mean_path = os.path.join(output_dir, apply_prefix(prefix, "exec_time_per_step_mean.png"))
    if should_skip(per_step_mean_path):
        done += 1
        render_progress("execution time plots", done, total_plots)
    else:
        fig, ax = plt.subplots(figsize=(10, 6))
        df_with_efficiency = df.copy()
        df_with_efficiency["time_per_step"] = df_with_efficiency["elapsed_time"] / df_with_efficiency["steps"]
        for algo in df["algorithm"].unique():
            algo_df = df_with_efficiency[df_with_efficiency["algorithm"] == algo]
            grouped = algo_df.groupby("horizon")["time_per_step"].agg(["mean", "std"])
            ax.errorbar(grouped.index, grouped["mean"] * 1000, yerr=grouped["std"] * 1000,
                        marker="o", label=algo, color=colors.get(algo, "#95a5a6"), capsize=3)
        ax.set_xlabel("Horizon")
        ax.set_ylabel("Time per Step (ms)")
        ax.set_title("Efficiency: Time per Step (mean ± std) — Algorithms")
        ax.set_xscale("log")
        ax.legend()
        plt.tight_layout()
        save_figure(per_step_mean_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("execution time plots", done, total_plots)

    per_step_median_path = os.path.join(output_dir, apply_prefix(prefix, "exec_time_per_step_median.png"))
    if should_skip(per_step_median_path):
        done += 1
        render_progress("execution time plots", done, total_plots)
    else:
        fig, ax = plt.subplots(figsize=(10, 6))
        for algo in df["algorithm"].unique():
            algo_df = df_with_efficiency[df_with_efficiency["algorithm"] == algo]
            grouped = algo_df.groupby("horizon")["time_per_step"].agg(
                median="median",
                q1=lambda s: s.quantile(0.25),
                q3=lambda s: s.quantile(0.75)
            )
            grouped["iqr"] = grouped["q3"] - grouped["q1"]
            ax.errorbar(grouped.index, grouped["median"] * 1000, yerr=grouped["iqr"] * 1000,
                        marker="o", label=algo, color=colors.get(algo, "#95a5a6"), capsize=3)
        ax.set_xlabel("Horizon")
        ax.set_ylabel("Time per Step (ms)")
        ax.set_title("Efficiency: Time per Step (median ± IQR) — Algorithms")
        ax.set_xscale("log")
        ax.legend()
        plt.tight_layout()
        save_figure(per_step_median_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("execution time plots", done, total_plots)

    # Total time comparison by horizon (bar chart)
    by_horizon_mean_path = os.path.join(output_dir, apply_prefix(prefix, "exec_time_by_horizon_comparison_mean.png"))
    if should_skip(by_horizon_mean_path):
        done += 1
        render_progress("execution time plots", done, total_plots)
    else:
        fig, ax = plt.subplots(figsize=(10, 6))
        horizons = sorted(df["horizon"].unique())
        x = np.arange(len(horizons))
        width = 0.25
        algos_list = list(df["algorithm"].unique())

        for i, algo in enumerate(algos_list):
            algo_df = df[df["algorithm"] == algo]
            means = [algo_df[algo_df["horizon"] == h]["elapsed_time"].mean() for h in horizons]
            stds = [algo_df[algo_df["horizon"] == h]["elapsed_time"].std() for h in horizons]
            # Handle NaN values
            means = [m if not np.isnan(m) else 0 for m in means]
            stds = [s if not np.isnan(s) else 0 for s in stds]
            ax.bar(x + i * width, means, width, label=algo, color=colors.get(algo, "#95a5a6"),
                   alpha=0.8, yerr=stds, capsize=3)

        ax.set_xlabel("Horizon")
        ax.set_ylabel("Execution Time (s)")
        ax.set_title("Comparison: Execution Time by Horizon (mean ± std) — Algorithms")
        ax.set_xticks(x + width)
        ax.set_xticklabels([str(h) for h in horizons], rotation=45)
        ax.legend()
        ax.set_yscale("log")

        plt.tight_layout()
        save_figure(by_horizon_mean_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("execution time plots", done, total_plots)

    by_horizon_median_path = os.path.join(output_dir, apply_prefix(prefix, "exec_time_by_horizon_comparison_median.png"))
    if should_skip(by_horizon_median_path):
        done += 1
        render_progress("execution time plots", done, total_plots)
    else:
        fig, ax = plt.subplots(figsize=(10, 6))
        for i, algo in enumerate(algos_list):
            algo_df = df[df["algorithm"] == algo]
            medians = [algo_df[algo_df["horizon"] == h]["elapsed_time"].median() for h in horizons]
            q1s = [algo_df[algo_df["horizon"] == h]["elapsed_time"].quantile(0.25) for h in horizons]
            q3s = [algo_df[algo_df["horizon"] == h]["elapsed_time"].quantile(0.75) for h in horizons]
            iqrs = [(q3 - q1) if not np.isnan(q3) and not np.isnan(q1) else 0 for q1, q3 in zip(q1s, q3s)]
            medians = [m if not np.isnan(m) else 0 for m in medians]
            ax.bar(x + i * width, medians, width, label=algo, color=colors.get(algo, "#95a5a6"),
                   alpha=0.8, yerr=iqrs, capsize=3)

        ax.set_xlabel("Horizon")
        ax.set_ylabel("Execution Time (s)")
        ax.set_title("Comparison: Execution Time by Horizon (median ± IQR) — Algorithms")
        ax.set_xticks(x + width)
        ax.set_xticklabels([str(h) for h in horizons], rotation=45)
        ax.legend()
        ax.set_yscale("log")

        plt.tight_layout()
        save_figure(by_horizon_median_path, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("execution time plots", done, total_plots)

    if total_plots > 0:
        print()


def create_summary_table(df, df_all, output_dir, prefix=""):
    """Create a summary table of results per algorithm."""
    def format_mean_std(series, decimals=1):
        mean = series.mean()
        std = series.std()
        if np.isnan(mean) or np.isnan(std):
            return "n/a"
        return f"{mean:.{decimals}f} ± {std:.{decimals}f}"
    def format_median_iqr(series, decimals=1):
        median = series.median()
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        if np.isnan(median) or np.isnan(q1) or np.isnan(q3):
            return "n/a"
        iqr = q3 - q1
        return f"{median:.{decimals}f} ± {iqr:.{decimals}f}"
    summary_data = []

    preferred_order = ["mpc_simplemove", "mpc_realmove", "adp_realmove", "spst_realmove", "beam_realmove"]
    algos = preferred_order + [algo for algo in df_all["algorithm"].unique() if algo not in preferred_order]
    for algo in algos:
        algo_df = df[df["algorithm"] == algo]
        algo_all = df_all[df_all["algorithm"] == algo]

        if algo_all.empty:
            continue

        # Best by total_sailed
        best_sailed = None
        if not algo_df.empty:
            best_sailed_idx = algo_df["total_sailed"].idxmin()
            best_sailed = algo_df.loc[best_sailed_idx]

        best_elapsed = best_sailed["elapsed_time"] if best_sailed is not None else np.nan
        best_distance = best_sailed["total_sailed"] if best_sailed is not None else np.nan
        best_params = (
            f"h={best_sailed['horizon']}, a={best_sailed['alpha']}" +
            (f", bw={best_sailed['beam_width']}" if algo == "beam_realmove" else "")
        ) if best_sailed is not None else "n/a"

        finished_count = len(algo_df)
        total_count = len(algo_all)
        success_rate = finished_count / total_count if total_count > 0 else 0
        summary_data.append({
            "Algorithm": algo,
            "Mean Dist\n(m ± std)": format_mean_std(algo_df["total_sailed"]),
            "Median Dist\n(m ± IQR)": format_median_iqr(algo_df["total_sailed"]),
            "Mean Time\n(s ± std)": format_mean_std(algo_df["elapsed_time"]),
            "Median Time\n(s ± IQR)": format_median_iqr(algo_df["elapsed_time"]),
            "Best Dist\n(m)": f"{best_distance:.1f}" if not np.isnan(best_distance) else "n/a",
            "Best Dist Time\n(s)": f"{best_elapsed:.2f}" if not np.isnan(best_elapsed) else "n/a",
            "Params": best_params,
            "Finished": f"{finished_count}/{total_count}",
            "Success": f"{(success_rate * 100):.1f}%",
        })

    summary_df = pd.DataFrame(summary_data)

    # Create figure with table
    fig_width = max(14, 1.6 * len(summary_df.columns))
    fig, ax = plt.subplots(figsize=(fig_width, 4))
    ax.axis("off")

    table = ax.table(
        cellText=summary_df.values,
        colLabels=summary_df.columns,
        cellLoc="center",
        loc="center",
        colColours=["#3498db"] * len(summary_df.columns)
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.1, 1.5)

    # Style header
    for i in range(len(summary_df.columns)):
        table[(0, i)].set_text_props(color="white", weight="bold")

    plt.title("Summary: Results — Algorithms", fontsize=14, pad=20)
    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, "summary_results_table.png"))
    if should_skip(filepath):
        close_fig()
        render_progress("summary table", 1, 1)
        print()
        return summary_df
    save_figure(filepath, dpi=150, bbox_inches="tight")
    render_progress("summary table", 1, 1)
    print()

    return summary_df


def create_scatter_plots(df, output_dir, prefix="", skip_params=None):
    """Scatter plots: all parameter pairs, colored by each remaining parameter."""
    params = algo_params_union(df)
    skip_params = skip_params or set()
    targets = ["total_sailed", "elapsed_time"]
    params = [param for param in params if param not in skip_params]
    work = []
    for y_param in targets:
        for x_param in params:
            for color_param in params:
                if color_param == x_param:
                    continue
                subset = df[[x_param, y_param, color_param]].dropna()
                if subset.empty:
                    continue
                work.append((y_param, x_param, color_param))
    total_plots = len(work)
    done = 0
    for y_param, x_param, color_param in work:
        subset = df[[x_param, y_param, color_param]].dropna()
        if subset.empty:
            continue
        filename = f"scatter_{y_param}_vs_{x_param}_by_{color_param}.png"
        filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
        if should_skip(filepath):
            done += 1
            render_progress("scatter plots", done, total_plots)
            continue
        fig, ax = plt.subplots(figsize=(10, 7))
        x_vals = subset[x_param]
        y_vals = subset[y_param]
        color_vals = subset[color_param]

        x_labels = None
        if not pd.api.types.is_numeric_dtype(x_vals):
            x_cats = pd.Categorical(x_vals)
            x_vals = x_cats.codes.astype(float)
            x_labels = list(x_cats.categories)

        color_labels = None
        if not pd.api.types.is_numeric_dtype(color_vals):
            color_cats = pd.Categorical(color_vals)
            color_vals = color_cats.codes.astype(float)
            color_labels = list(color_cats.categories)

        x_range = x_vals.max() - x_vals.min()
        jitter = np.random.uniform(-x_range * 0.01, x_range * 0.01, len(subset)) if x_range > 0 else 0
        scatter = ax.scatter(
            x_vals + jitter,
            y_vals,
            c=color_vals,
            cmap="plasma",
            alpha=0.5,
            s=25,
            edgecolors='none'
        )
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label(color_param.replace("_", " ").title())
        if color_labels is not None:
            cbar.set_ticks(range(len(color_labels)))
            cbar.set_ticklabels(color_labels)

        ax.set_xlabel(x_param.replace("_", " ").title())
        if x_labels is not None:
            ax.set_xticks(range(len(x_labels)))
            ax.set_xticklabels(x_labels, rotation=30)
        ax.set_ylabel(y_param.replace("_", " ").title())
        ax.set_title(
            f"Scatter: {y_param.replace('_', ' ').title()} vs {x_param.replace('_', ' ').title()} — "
            f"{color_param.replace('_', ' ').title()}\n({len(subset)} runs)"
        )
        plt.tight_layout()
        save_figure(filepath, dpi=150, bbox_inches="tight")
        done += 1
        render_progress("scatter plots", done, total_plots)
    if total_plots > 0:
        print()


def compute_finished_mask(df_all, metadata):
    """Return a boolean mask for finished runs, or None if unavailable."""
    if "finished" in df_all.columns:
        return df_all["finished"] == True
    if "success" in df_all.columns:
        return df_all["success"] == True
    if "distance_to_mark" in df_all.columns:
        if "goal" in df_all.columns:
            return df_all["distance_to_mark"] <= df_all["goal"]
        if "goal" in metadata:
            return df_all["distance_to_mark"] <= metadata["goal"]
    return None


def create_unfinished_rate_heatmaps(df_all, metadata, output_dir, prefix="", skip_params=None):
    """Create heatmaps of unfinished rate for each parameter pair, per algorithm."""
    if df_all.empty:
        return
    skip_params = skip_params or set()

    params = algo_params_union(df_all)
    work = []
    for algo in df_all["algorithm"].unique():
        algo_df = df_all[df_all["algorithm"] == algo]
        finished_mask = compute_finished_mask(algo_df, metadata)
        if finished_mask is None:
            continue
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                if x_param in skip_params or y_param in skip_params:
                    continue
                if x_param not in algo_df.columns or y_param not in algo_df.columns:
                    continue
                subset = algo_df[[x_param, y_param]].copy()
                subset["unfinished"] = (~finished_mask).astype(int)
                if subset.empty:
                    continue
                pivot = subset.pivot_table(
                    values="unfinished",
                    index=y_param,
                    columns=x_param,
                    aggfunc="mean"
                )
                if pivot.empty:
                    continue
                pivot_median = subset.pivot_table(
                    values="unfinished",
                    index=y_param,
                    columns=x_param,
                    aggfunc="median"
                )
                if pivot_median.empty:
                    continue
                work.append((algo, x_param, y_param))
    total_plots = len(work) * 2
    done = 0
    for algo in df_all["algorithm"].unique():
        algo_df = df_all[df_all["algorithm"] == algo]
        finished_mask = compute_finished_mask(algo_df, metadata)
        if finished_mask is None:
            continue
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                if x_param in skip_params or y_param in skip_params:
                    continue
                if x_param not in algo_df.columns or y_param not in algo_df.columns:
                    continue
                subset = algo_df[[x_param, y_param]].copy()
                subset["unfinished"] = (~finished_mask).astype(int)
                if subset.empty:
                    continue
                pivot = subset.pivot_table(
                    values="unfinished",
                    index=y_param,
                    columns=x_param,
                    aggfunc="mean"
                )
                if pivot.empty:
                    continue
                filename = f"unfinished_rate_heatmap_{algo}_{x_param}_vs_{y_param}_mean.png"
                filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
                if should_skip(filepath):
                    done += 1
                    render_progress("unfinished rate heatmaps", done, total_plots)
                else:
                    fig, ax = plt.subplots(figsize=(10, 7))
                    im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto", vmin=0, vmax=1)
                    ax.set_xticks(range(len(pivot.columns)))
                    ax.set_yticks(range(len(pivot.index)))
                    ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.columns], rotation=45)
                    ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.index])
                    ax.set_xlabel(x_param.replace("_", " ").title())
                    ax.set_ylabel(y_param.replace("_", " ").title())
                    ax.set_title(f"Heatmap: Unfinished Rate (mean) — {algo}\n{x_param} vs {y_param}")
                    plt.colorbar(im, ax=ax, label="Unfinished Rate")
                    for row in range(len(pivot.index)):
                        for col in range(len(pivot.columns)):
                            val = pivot.values[row, col]
                            if not np.isnan(val):
                                text_color = "white" if val > 0.5 else "black"
                                ax.text(col, row, f"{val:.2f}", ha="center", va="center", fontsize=7, color=text_color)
                    plt.tight_layout()
                    save_figure(filepath, dpi=150, bbox_inches="tight")
                    done += 1
                    render_progress("unfinished rate heatmaps", done, total_plots)

                pivot_median = subset.pivot_table(
                    values="unfinished",
                    index=y_param,
                    columns=x_param,
                    aggfunc="median"
                )
                if pivot_median.empty:
                    continue
                filename = f"unfinished_rate_heatmap_{algo}_{x_param}_vs_{y_param}_median.png"
                filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
                if should_skip(filepath):
                    done += 1
                    render_progress("unfinished rate heatmaps", done, total_plots)
                    continue
                fig, ax = plt.subplots(figsize=(10, 7))
                im = ax.imshow(pivot_median.values, cmap="YlOrRd", aspect="auto", vmin=0, vmax=1)
                ax.set_xticks(range(len(pivot_median.columns)))
                ax.set_yticks(range(len(pivot_median.index)))
                ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_median.columns], rotation=45)
                ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_median.index])
                ax.set_xlabel(x_param.replace("_", " ").title())
                ax.set_ylabel(y_param.replace("_", " ").title())
                ax.set_title(f"Heatmap: Unfinished Rate (median) — {algo}\n{x_param} vs {y_param}")
                plt.colorbar(im, ax=ax, label="Unfinished Rate")
                for row in range(len(pivot_median.index)):
                    for col in range(len(pivot_median.columns)):
                        val = pivot_median.values[row, col]
                        if not np.isnan(val):
                            text_color = "white" if val > 0.5 else "black"
                            ax.text(col, row, f"{val:.2f}", ha="center", va="center", fontsize=7, color=text_color)
                plt.tight_layout()
                save_figure(filepath, dpi=150, bbox_inches="tight")
                done += 1
                render_progress("unfinished rate heatmaps", done, total_plots)
    if total_plots > 0:
        print()


def create_failure_probability_plots(df_all, metadata, output_dir, prefix="", skip_params=None):
    """Create failure probability vs parameter comparison plots."""
    if df_all.empty:
        return

    skip_params = skip_params or set()
    params = algo_params_union(df_all)
    work = []
    for param in params:
        if param in skip_params:
            continue
        if param not in df_all.columns:
            continue
        plotted = False
        for algo in df_all["algorithm"].unique():
            algo_df = df_all[df_all["algorithm"] == algo]
            finished_mask = compute_finished_mask(algo_df, metadata)
            if finished_mask is None:
                continue
            subset = algo_df[[param]].copy()
            subset["unfinished"] = (~finished_mask).astype(int)
            subset = subset.dropna()
            if subset.empty:
                continue
            plotted = True
            break
        if plotted:
            work.append(param)
    total_plots = len(work) * 2
    done = 0
    for param in params:
        if param in skip_params:
            continue
        if param not in df_all.columns:
            continue
        mean_path = os.path.join(output_dir, apply_prefix(prefix, f"unfinished_rate_compare_{param}_mean.png"))
        median_path = os.path.join(output_dir, apply_prefix(prefix, f"unfinished_rate_compare_{param}_median.png"))
        skip_mean = should_skip(mean_path)
        skip_median = should_skip(median_path)
        if skip_mean and skip_median:
            done += 2
            render_progress("unfinished rate vs param", done, total_plots)
            continue
        if skip_mean:
            done += 1
            render_progress("unfinished rate vs param", done, total_plots)
        if skip_median:
            done += 1
            render_progress("unfinished rate vs param", done, total_plots)

        if not skip_mean:
            fig, ax = plt.subplots(figsize=(9, 6))
            plotted = False
            for algo in df_all["algorithm"].unique():
                algo_df = df_all[df_all["algorithm"] == algo]
                finished_mask = compute_finished_mask(algo_df, metadata)
                if finished_mask is None:
                    continue
                subset = algo_df[[param]].copy()
                subset["unfinished"] = (~finished_mask).astype(int)
                subset = subset.dropna()
                if subset.empty:
                    continue
                grouped = subset.groupby(param)["unfinished"].mean().reset_index()
                ax.plot(grouped[param], grouped["unfinished"], marker="o", linestyle="-", label=algo)
                plotted = True
            if not plotted:
                close_fig()
                continue
            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Unfinished Rate")
            ax.set_title(f"Sensitivity: Unfinished Rate (mean) — {param.replace('_', ' ').title()}")
            ax.set_ylim(0, 1)
            if param == "horizon":
                ax.set_xscale("log")
            ax.legend(fontsize=8)
            plt.tight_layout()
            save_figure(mean_path, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("unfinished rate vs param", done, total_plots)

        if not skip_median:
            fig, ax = plt.subplots(figsize=(9, 6))
            plotted = False
            for algo in df_all["algorithm"].unique():
                algo_df = df_all[df_all["algorithm"] == algo]
                finished_mask = compute_finished_mask(algo_df, metadata)
                if finished_mask is None:
                    continue
                subset = algo_df[[param]].copy()
                subset["unfinished"] = (~finished_mask).astype(int)
                subset = subset.dropna()
                if subset.empty:
                    continue
                grouped = subset.groupby(param)["unfinished"].median().reset_index()
                ax.plot(grouped[param], grouped["unfinished"], marker="o", linestyle="-", label=algo)
                plotted = True
            if not plotted:
                close_fig()
                continue
            ax.set_xlabel(param.replace("_", " ").title())
            ax.set_ylabel("Unfinished Rate")
            ax.set_title(f"Sensitivity: Unfinished Rate (median) — {param.replace('_', ' ').title()}")
            ax.set_ylim(0, 1)
            if param == "horizon":
                ax.set_xscale("log")
            ax.legend(fontsize=8)
            plt.tight_layout()
            save_figure(median_path, dpi=150, bbox_inches="tight")
            done += 1
            render_progress("unfinished rate vs param", done, total_plots)
    if total_plots > 0:
        print()


def create_coverage_dispersion_plot(df_all, metadata, algo, output_dir, prefix=""):
    """Plot global coverage dispersion using a 5% sliding window."""
    filename = f"coverage_dispersion_{algo}.png"
    filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
    if should_skip(filepath):
        return filepath
    algo_df = df_all[df_all["algorithm"] == algo].copy()
    if algo_df.empty:
        return None

    params = ALGO_PARAMS.get(algo, [])
    if len(params) < 2:
        return None

    ranges = (metadata or {}).get("param_ranges", {})
    if not ranges:
        ranges = {p: sorted(algo_df[p].dropna().unique().tolist()) for p in params if p in algo_df.columns}

    total_possible = 1
    for p in params:
        total_possible *= len(ranges.get(p, []))

    n = len(algo_df)
    if n == 0:
        return None

    window_low = max(1, int(50 * len(params)))
    window_high = max(window_low + 1, int(300 * len(params)))

    percent = []
    dim_score = []
    mean_entropy = []
    volume_low = []
    volume_high = []

    def entropy_from_counts(counts):
        total = counts.sum()
        if total == 0 or len(counts) <= 1:
            return 0.0
        probs = counts / total
        return float(-(probs * np.log(probs)).sum())

    def window_metrics(window):
        if window.empty:
            return None, None, None, None
        varied = 0
        entropies = []
        value_sets = []
        marginal_vals = []
        joint_values = []
        for p in params:
            if p not in window.columns:
                continue
            values = window[p].dropna().tolist()
            total_vals = len(ranges.get(p, []))
            if not values:
                entropies.append(0.0)
                value_sets.append(set())
                if total_vals:
                    marginal_vals.append(0.0)
                continue
            counts = pd.Series(values).value_counts().values.astype(float)
            if len(counts) > 1:
                varied += 1
            h = entropy_from_counts(counts)
            h_max = float(np.log(len(counts))) if len(counts) > 1 else 1.0
            entropies.append(h / h_max if h_max else 0.0)
            value_sets.append(set(values))
            if total_vals:
                marginal_vals.append(len(set(values)) / total_vals)
        total_params = len(params)
        dim_val = varied / total_params if total_params else 0.0
        ent_val = float(np.mean(entropies)) if entropies else 0.0

        marginal_val = float(np.mean(marginal_vals)) if marginal_vals else 0.0

        window_clean = window[params].dropna()
        if not window_clean.empty:
            joint_values = list(map(tuple, window_clean.values.tolist()))
        joint_counts = pd.Series(joint_values).value_counts().values.astype(float) if joint_values else np.array([])
        denom = 1
        for s in value_sets:
            denom *= max(1, len(s))
        volume_val = len(set(joint_values)) / denom if denom else 0.0
        combo_val = len(set(joint_values)) / total_possible if total_possible else 0.0
        raw_ratio = marginal_val / max(combo_val, 1e-9)
        ratio_val = raw_ratio / (1.0 + raw_ratio)
        return dim_val, ent_val, volume_val, ratio_val

    dim_low = []
    dim_high = []
    ent_low = []
    ent_high = []

    # Precompute full tuple per test for cumulative weighted coverage.
    tuple_values = []
    if params and all(p in algo_df.columns for p in params):
        for row in algo_df[params].itertuples(index=False, name=None):
            if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in row):
                tuple_values.append(None)
            else:
                tuple_values.append(row)
    else:
        tuple_values = [None] * n

    seen_tuples = set()

    for idx in range(1, n + 1):
        start_low = max(0, idx - window_low)
        start_high = max(0, idx - window_high)
        window_l = algo_df.iloc[start_low:idx]
        window_h = algo_df.iloc[start_high:idx]
        dim_l, ent_l, vol_l, ratio_l = window_metrics(window_l)
        dim_h, ent_h, vol_h, ratio_h = window_metrics(window_h)
        if dim_l is None or dim_h is None:
            return None
        dim_low.append(dim_l)
        dim_high.append(dim_h)
        ent_low.append(ent_l)
        ent_high.append(ent_h)
        volume_low.append(vol_l)
        volume_high.append(vol_h)
        percent.append(idx / n * 100)

        tup = tuple_values[idx - 1]
        if tup is not None and tup not in seen_tuples:
            seen_tuples.add(tup)

    # Effective Dimensional Coverage Progress (cumulative, normalized to end at 1.0).
    dim_progress = []
    if params and all(p in algo_df.columns for p in params):
        ranges_values = {
            p: list(ranges.get(p, sorted(algo_df[p].dropna().unique().tolist()))) for p in params
        }
        ranges_total = {p: len(ranges_values[p]) for p in params}
        index_maps = {p: {v: i for i, v in enumerate(ranges_values[p])} for p in params}
        seen_per_dim = {p: set() for p in params}
        seen_idx_per_dim = {p: set() for p in params}
        dim_util = []
        gini_progress = []
        hrc_progress = []
        hrc_weighted_progress = []
        for row in algo_df[params].itertuples(index=False, name=None):
            for p, v in zip(params, row):
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    seen_per_dim[p].add(v)
                    if v in index_maps[p]:
                        seen_idx_per_dim[p].add(index_maps[p][v])
            ratios = []
            spans = []
            for p in params:
                total_vals = max(1, ranges_total.get(p, 0))
                vals = seen_per_dim[p]
                ratios.append(len(vals) / total_vals)
                idxs = seen_idx_per_dim[p]
                if idxs:
                    spans.append((max(idxs) - min(idxs) + 1) / total_vals)
                else:
                    spans.append(0.0)
            geom = float(np.prod(ratios) ** (1.0 / len(ratios))) if ratios else 0.0
            dim_util.append(geom)
            # Gini coefficient of per-dimension coverage ratios (0=balanced, 1=uneven).
            arr = np.array(ratios, dtype=float)
            if arr.size == 0:
                gini = 0.0
            else:
                arr_sorted = np.sort(arr)
                nvals = arr_sorted.size
                if np.isclose(arr_sorted.sum(), 0.0):
                    gini = 0.0
                else:
                    index = np.arange(1, nvals + 1)
                    gini = float((np.sum((2 * index - nvals - 1) * arr_sorted)) / (nvals * arr_sorted.sum()))
            gini_progress.append(gini)
            # Hyper-rectangle coverage (envelope span normalized to 0-1).
            hrc_val = float(np.prod(spans)) if spans else 0.0
            hrc_progress.append(hrc_val)
            hrc_weighted_progress.append(hrc_val * geom)
        cum_avg = np.cumsum(dim_util) / np.arange(1, len(dim_util) + 1)
        final = cum_avg[-1] if len(cum_avg) else 1.0
        dim_progress = (cum_avg / final) if final > 0 else cum_avg

    fig, ax = plt.subplots(figsize=(10, 6))
    # Auto-detect breadth vs sequential zones using mean entropy band midpoint.
    entropy_mid = (np.array(ent_low) + np.array(ent_high)) / 2.0
    smooth_window = max(5, int(0.02 * n))
    if smooth_window % 2 == 0:
        smooth_window += 1
    smoothed = (
        pd.Series(entropy_mid)
        .rolling(window=smooth_window, center=True, min_periods=1)
        .mean()
        .values
    )

    # k-means (k=2) on smoothed entropy to classify breadth vs depth.
    values = smoothed.astype(float)
    c1, c2 = float(values.min()), float(values.max())
    for _ in range(20):
        d1 = np.abs(values - c1)
        d2 = np.abs(values - c2)
        mask = d2 < d1
        if mask.all() or (~mask).all():
            break
        new_c1 = float(values[~mask].mean())
        new_c2 = float(values[mask].mean())
        if np.isclose([c1, c2], [new_c1, new_c2]).all():
            break
        c1, c2 = new_c1, new_c2

    high_cluster = c1 if c1 > c2 else c2
    labels = np.abs(values - high_cluster) < np.abs(values - (c2 if high_cluster == c1 else c1))

    # Merge short segments to avoid flicker.
    min_segment = max(5, int(0.03 * n))
    segments = []
    start = 0
    for i in range(1, n):
        if labels[i] != labels[i - 1]:
            segments.append((start, i, labels[i - 1]))
            start = i
    segments.append((start, n, labels[-1]))

    merged = []
    for seg in segments:
        if merged and (seg[1] - seg[0]) < min_segment:
            # Merge short segment into previous.
            prev = merged.pop()
            merged.append((prev[0], seg[1], prev[2]))
        else:
            merged.append(seg)

    # Merge contiguous segments with the same label.
    compact = []
    for seg in merged:
        if compact and seg[2] == compact[-1][2]:
            prev = compact.pop()
            compact.append((prev[0], seg[1], prev[2]))
        else:
            compact.append(seg)

    for start, end, is_breadth in compact:
        if end <= start:
            continue
        x0 = percent[start]
        x1 = percent[end - 1] if end - 1 < len(percent) else percent[-1]
        ax.axvspan(
            x0,
            x1,
            color="#1f77b4" if is_breadth else "#d62728",
            alpha=0.16,
            zorder=0,
        )
        # Add dashed boundary line at segment start (except first).
        if start != 0:
            ax.axvline(x0, color="#7f8c8d", linestyle="--", linewidth=1.0, alpha=0.6, zorder=1)

    # Legend for background zones.
    zone_patches = [
        Patch(facecolor="#1f77b4", edgecolor="none", alpha=0.16, label="Space-filling (Exploration)"),
        Patch(facecolor="#d62728", edgecolor="none", alpha=0.16, label="Depth-first (Exploitation)"),
    ]
    ax.fill_between(percent, ent_low, ent_high, alpha=0.4, color="#e67e22", label="Mean entropy band (diversity per dimension)")
    ax.fill_between(percent, volume_low, volume_high, alpha=0.4, color="#3498db", label="Coverage Volume band (unique combos inside window)")
    if len(dim_progress) == len(percent):
        ax.plot(
            percent,
            dim_progress,
            color="#2c3e50",
            linewidth=2.0,
            label="Effective dimensional coverage progress (Geometric-mean coverage)",
        )
    if "gini_progress" in locals() and len(gini_progress) == len(percent):
        ax.plot(
            percent,
            gini_progress,
            color="#8e44ad",
            linewidth=2.0,
            label="Coverage imbalance (Gini)",
        )
    if "hrc_progress" in locals() and len(hrc_progress) == len(percent):
        ax.plot(
            percent,
            hrc_progress,
            color="#27ae60",
            linewidth=2.0,
            label="Hyper-rectangle coverage (HRC)",
        )
    if "hrc_weighted_progress" in locals() and len(hrc_weighted_progress) == len(percent):
        ax.plot(
            percent,
            hrc_weighted_progress,
            color="#1abc9c",
            linewidth=2.0,
            label="Weighted HRC (HRC × geometric mean)",
        )
    ax.set_xlabel("Progress (% of tests)")
    ax.set_ylabel("Exploration metrics (0–1)")
    ax.set_title(
        f"Exploration Breadth (window={window_low}-{window_high} tests) — {algo}"
    )
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(handles=zone_patches + ax.get_legend_handles_labels()[0], loc="upper left")
    plt.tight_layout()

    save_figure(filepath, dpi=150, bbox_inches="tight")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Visualize benchmark results")
    parser.add_argument("--input", default="benchmark_results.json", help="Input JSON file")
    parser.add_argument("--output-dir", default=".", help="Output directory for images")
    parser.add_argument("--display", action="store_true", help="Display figures after saving")
    args = parser.parse_args()
    global DISPLAY
    DISPLAY = args.display
    global INPUT_MTIME

    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, args.input) if not os.path.isabs(args.input) else args.input
    output_dir = os.path.join(script_dir, args.output_dir) if not os.path.isabs(args.output_dir) else args.output_dir

    os.makedirs(output_dir, exist_ok=True)
    try:
        INPUT_MTIME = os.path.getmtime(input_path)
    except OSError:
        INPUT_MTIME = None

    print(f"Loading results from {input_path}...")
    df, metadata, df_all = load_results(input_path)
    print(f"Loaded {len(df)} finished races (distance_to_mark <= goal)")

    print("\nGenerating visualizations...")

    # 1. Heatmaps (all parameter pairs, total_sailed and elapsed_time)
    print("  Creating heatmaps...")
    heatmap_total = 0
    for algo in df["algorithm"].unique():
        params = ALGO_PARAMS.get(algo, ["horizon", "alpha"])
        pairs = len(params) * (len(params) - 1) // 2
        heatmap_total += pairs * 5
    heatmap_done = 0
    for algo in df["algorithm"].unique():
        params = ALGO_PARAMS.get(algo, ["horizon", "alpha"])
        metrics = ["total_sailed", "elapsed_time"]
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                for metric in metrics:
                    create_heatmap(df, algo, x_param, y_param, metric, output_dir, agg="mean")
                    heatmap_done += 1
                    render_progress("heatmaps", heatmap_done, heatmap_total)
                    create_heatmap(df, algo, x_param, y_param, metric, output_dir, agg="median")
                    heatmap_done += 1
                    render_progress("heatmaps", heatmap_done, heatmap_total)
                if "total_sailed" in metrics:
                    create_heatmap(df, algo, x_param, y_param, "total_sailed", output_dir, agg="min")
                    heatmap_done += 1
                    render_progress("heatmaps", heatmap_done, heatmap_total)
    if heatmap_total > 0:
        print()

    print("  Creating coverage heatmaps...")
    coverage_total = 0
    for algo in df_all["algorithm"].unique():
        params = ALGO_PARAMS.get(algo, ["horizon", "alpha"])
        coverage_total += len(params) * (len(params) - 1) // 2
    coverage_done = 0
    for algo in df_all["algorithm"].unique():
        params = ALGO_PARAMS.get(algo, ["horizon", "alpha"])
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                create_coverage_heatmap(df_all, metadata, algo, x_param, y_param, output_dir)
                coverage_done += 1
                render_progress("coverage heatmaps", coverage_done, coverage_total)
    if coverage_total > 0:
        print()

    # 2. Algorithm comparison
    print("  Creating algorithm comparisons...")
    create_algorithm_comparison(df, output_dir)

    # 3. Parameter sensitivity
    print("  Creating parameter sensitivity plots...")
    create_parameter_sensitivity(df, output_dir)

    # 4. Execution time analysis
    print("  Creating execution time analysis...")
    create_execution_time_analysis(df, output_dir)

    # 5. Summary table
    print("  Creating summary table...")
    summary = create_summary_table(df, df_all, output_dir)

    # 6. Scatter plots
    print("  Creating scatter plots...")
    create_scatter_plots(df, output_dir)

    # 7. Unfinished diagnostics
    print("  Creating unfinished rate heatmaps...")
    create_unfinished_rate_heatmaps(df_all, metadata, output_dir)
    print("  Creating unfinished rate vs param plots...")
    create_failure_probability_plots(df_all, metadata, output_dir)
    print("  Creating coverage dispersion plots...")
    dispersion_algos = list(df_all["algorithm"].unique())
    dispersion_done = 0
    for algo in df_all["algorithm"].unique():
        create_coverage_dispersion_plot(df_all, metadata, algo, output_dir)
        dispersion_done += 1
        render_progress("coverage dispersion", dispersion_done, len(dispersion_algos))
    if dispersion_algos:
        print()

    print("\n" + "=" * 60)
    print("VISUALIZATION COMPLETE")
    print("=" * 60)
    print(f"\nOutput directory: {output_dir}")
    print("\nGenerated files:")
    generated = [f for f in sorted(os.listdir(output_dir)) if f.endswith((".png", ".csv"))]
    for f in generated:
        print(f"  - {f}")
    png_count = sum(1 for f in generated if f.endswith(".png"))
    csv_count = sum(1 for f in generated if f.endswith(".csv"))
    print(f"\nTotal figures: {png_count}")
    if csv_count:
        print(f"Total tables: {csv_count}")

    print("\n" + "=" * 60)
    print("SUMMARY OF BEST RESULTS")
    print("=" * 60)
    print(summary.to_string(index=False))

    if args.display:
        plt.show(block=False)
        print("\nPress Enter to close visualizations...")
        input()


if __name__ == "__main__":
    main()
