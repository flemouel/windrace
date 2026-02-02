#!/usr/bin/env python3
"""
Visualization script for benchmark results.

Generates:
1. Heatmaps: parameter combinations (alpha vs horizon, horizon vs beam-width, etc.)
2. Algorithm comparison: bar charts comparing the 3 algorithms
3. Parameter sensitivity plots
4. Scatter plots: total_sailed vs each parameter

Most plots use finished races (distance_to_mark <= goal).
Some diagnostics compare finished vs unfinished runs.
"""

import argparse
import json
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

# Set style
plt.style.use('seaborn-v0_8-whitegrid')


DISPLAY = False


def apply_prefix(prefix, name):
    return f"{prefix}{name}" if prefix else name


def close_fig():
    if not DISPLAY:
        close_fig()


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


def _extract_singleton_line(pivot, x_param, y_param):
    if pivot.shape[0] == 1:
        return {
            "x_values": pivot.columns,
            "y_values": pivot.iloc[0].values,
            "x_label": x_param,
            "fixed_param": y_param,
            "fixed_value": pivot.index[0],
        }
    if pivot.shape[1] == 1:
        return {
            "x_values": pivot.index,
            "y_values": pivot.iloc[:, 0].values,
            "x_label": y_param,
            "fixed_param": x_param,
            "fixed_value": pivot.columns[0],
        }
    return None


def _plot_singleton_line(
    pivot,
    x_param,
    y_param,
    output_dir,
    filename,
    prefix,
    title_template,
    y_label,
    color="#3498db",
):
    line = _extract_singleton_line(pivot, x_param, y_param)
    if not line:
        return None

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(line["x_values"], line["y_values"], marker="o", color=color)
    ax.set_xlabel(line["x_label"].replace("_", " ").title())
    ax.set_ylabel(y_label)
    ax.set_title(
        title_template.format(
            x_label=line["x_label"],
            fixed_param=line["fixed_param"],
            fixed_value=line["fixed_value"],
        )
    )
    if line["x_label"] == "horizon":
        ax.set_xscale("log")
    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()
    return filepath


def create_heatmap(df, algo, x_param, y_param, metric, output_dir, fixed_params=None, agg="mean", prefix=""):
    """
    Create a heatmap for a specific algorithm and parameter combination.
    """
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

    if prefix.startswith("ta43_") and (pivot.shape[0] == 1 or pivot.shape[1] == 1):
        metric_label = metric.replace("_", " ").title()
        fixed_suffix = "_".join(f"{k}{v}" for k, v in (fixed_params or {}).items())
        filename = f"heatmap_{algo}_{x_param}_vs_{y_param}_{agg}_{metric}"
        if fixed_suffix:
            filename += f"_{fixed_suffix}"
        filename += ".png"
        title_template = f"Line: {metric_label} ({agg}) — {algo}\n{{x_label}} (fixed {{fixed_param}}={{fixed_value}})"
        return _plot_singleton_line(
            pivot,
            x_param,
            y_param,
            output_dir,
            filename,
            prefix,
            title_template,
            metric_label,
            color="#3498db",
        )

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
    fixed_suffix = "_".join(f"{k}{v}" for k, v in (fixed_params or {}).items())
    filename = f"heatmap_{algo}_{x_param}_vs_{y_param}_{agg}_{metric}"
    if fixed_suffix:
        filename += f"_{fixed_suffix}"
    filename += ".png"
    filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()
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
    algo_df = df_all[df_all["algorithm"] == algo].copy()
    if algo_df.empty:
        return None

    params = ["horizon", "alpha", "beam_width"]
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

    if prefix.startswith("ta43_") and (pivot.shape[0] == 1 or pivot.shape[1] == 1):
        filename = f"coverage_heatmap_{algo}_{x_param}_vs_{y_param}.png"
        title_template = f"Line: Coverage Rate — {algo}\n{{x_label}} (fixed {{fixed_param}}={{fixed_value}})"
        line = _extract_singleton_line(pivot, x_param, y_param)
        if not line:
            return None
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(line["x_values"], line["y_values"] * 100, marker="o", color="#8e44ad")
        ax.set_xlabel(line["x_label"].replace("_", " ").title())
        ax.set_ylabel("Coverage Rate (%)")
        ax.set_title(
            title_template.format(
                x_label=line["x_label"],
                fixed_param=line["fixed_param"],
                fixed_value=line["fixed_value"],
            )
        )
        if line["x_label"] == "horizon":
            ax.set_xscale("log")
        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()
        return filepath

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
    filename = f"coverage_heatmap_{algo}_{x_param}_vs_{y_param}.png"
    filepath = os.path.join(output_dir, apply_prefix(prefix, filename))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()
    return filepath


def create_algorithm_comparison(df, output_dir, prefix=""):
    """Create bar charts comparing algorithms (total_sailed only)."""
    metric = "total_sailed"

    fig, ax = plt.subplots(figsize=(10, 6))

    # Group by algorithm and compute stats
    stats = df.groupby("algorithm")[metric].agg(["mean", "std", "min", "max"])
    stats = stats.sort_values("mean")

    colors = {"beam_realmove": "#3498db", "mpc_realmove": "#e74c3c", "mpc_simplemove": "#2ecc71"}
    bar_colors = [colors.get(algo, "#95a5a6") for algo in stats.index]

    x = range(len(stats))
    bars = ax.bar(x, stats["mean"], yerr=stats["std"], capsize=5, color=bar_colors, alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(stats.index, rotation=15)
    ax.set_ylabel("Total Sailed (m)")
    ax.set_title("Comparison: Total Sailed Distance (mean ± std) — Algorithms")

    # Add value labels
    for i, (bar, mean_val) in enumerate(zip(bars, stats["mean"])):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + stats["std"].iloc[i] + 0.02 * stats["mean"].max(),
                f"{mean_val:.1f}", ha="center", va="bottom", fontsize=10)

    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, "compare_total_sailed_mean.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    # Median +/- IQR
    fig, ax = plt.subplots(figsize=(10, 6))
    median_stats = df.groupby("algorithm")[metric].agg(
        median="median",
        q1=lambda s: s.quantile(0.25),
        q3=lambda s: s.quantile(0.75)
    )
    median_stats["iqr"] = median_stats["q3"] - median_stats["q1"]
    median_stats = median_stats.sort_values("median")

    bar_colors = [colors.get(algo, "#95a5a6") for algo in median_stats.index]
    x = range(len(median_stats))
    bars = ax.bar(x, median_stats["median"], yerr=median_stats["iqr"], capsize=5, color=bar_colors, alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(median_stats.index, rotation=15)
    ax.set_ylabel("Total Sailed (m)")
    ax.set_title("Comparison: Total Sailed Distance (median ± IQR) — Algorithms")

    for i, (bar, median_val) in enumerate(zip(bars, median_stats["median"])):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + median_stats["iqr"].iloc[i] + 0.02 * median_stats["median"].max(),
                f"{median_val:.1f}", ha="center", va="bottom", fontsize=10)

    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, "compare_total_sailed_median.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    # Best results per algorithm
    fig, ax = plt.subplots(figsize=(10, 6))

    best_per_algo = df.loc[df.groupby("algorithm")[metric].idxmin()]

    bar_colors = [colors.get(algo, "#95a5a6") for algo in best_per_algo["algorithm"]]

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
        ax.text(i, bars[i].get_height() + 0.01 * best_per_algo[metric].max(),
                f"{row[metric]:.1f}\n({params})", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, "compare_total_sailed_min.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()


def create_parameter_sensitivity(df, output_dir, prefix="", skip_params=None):
    """Create plots showing how each parameter affects total_sailed."""
    params = ["horizon", "alpha"]
    skip_params = skip_params or set()
    metric = "total_sailed"
    algos = df["algorithm"].unique()
    colors = {"beam_realmove": "#3498db", "mpc_realmove": "#e74c3c", "mpc_simplemove": "#2ecc71"}

    for param in params:
        if param in skip_params:
            continue
        fig, ax = plt.subplots(figsize=(10, 6))

        for algo in algos:
            algo_df = df[df["algorithm"] == algo]
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
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"sensitivity_{param}_mean_total_sailed.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        # Median (IQR) total_sailed
        fig, ax = plt.subplots(figsize=(10, 6))

        for algo in algos:
            algo_df = df[df["algorithm"] == algo]
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
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"sensitivity_{param}_median_total_sailed.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        # Best (min) total_sailed
        fig, ax = plt.subplots(figsize=(10, 6))

        for algo in algos:
            algo_df = df[df["algorithm"] == algo]
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
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"sensitivity_{param}_min_total_sailed.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

    # Special plot for beam_width (only beam_realmove)
    beam_df = df[df["algorithm"] == "beam_realmove"]
    if not beam_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))

        grouped = beam_df.groupby("beam_width")[metric].agg(["mean", "std"])

        ax.errorbar(
            grouped.index,
            grouped["mean"],
            yerr=grouped["std"],
            marker="o",
            color="#3498db",
            capsize=3
        )

        ax.set_xlabel("Beam Width")
        ax.set_ylabel("Total Sailed (m)")
        ax.set_title("Sensitivity: Total Sailed Distance (mean ± std) — beam_realmove (Beam Width)")

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, "sensitivity_beam_width_mean_total_sailed.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        fig, ax = plt.subplots(figsize=(10, 6))

        grouped = beam_df.groupby("beam_width")[metric].agg(
            median="median",
            q1=lambda s: s.quantile(0.25),
            q3=lambda s: s.quantile(0.75)
        )
        grouped["iqr"] = grouped["q3"] - grouped["q1"]

        ax.errorbar(
            grouped.index,
            grouped["median"],
            yerr=grouped["iqr"],
            marker="o",
            color="#3498db",
            capsize=3
        )

        ax.set_xlabel("Beam Width")
        ax.set_ylabel("Total Sailed (m)")
        ax.set_title("Sensitivity: Total Sailed Distance (median ± IQR) — beam_realmove (Beam Width)")

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, "sensitivity_beam_width_median_total_sailed.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        fig, ax = plt.subplots(figsize=(10, 6))

        grouped = beam_df.groupby("beam_width")[metric].agg(["min"])

        ax.plot(
            grouped.index,
            grouped["min"],
            marker="o",
            color="#3498db"
        )

        ax.set_xlabel("Beam Width")
        ax.set_ylabel("Total Sailed (m)")
        ax.set_title("Sensitivity: Best Total Sailed Distance — beam_realmove (Beam Width)")

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, "sensitivity_beam_width_min_total_sailed.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()


def create_execution_time_analysis(df, output_dir, prefix="", skip_heatmaps=None, skip_params=None):
    """Analyze execution times."""
    colors = {"beam_realmove": "#3498db", "mpc_realmove": "#e74c3c", "mpc_simplemove": "#2ecc71"}

    # 1. Time distribution per algorithm
    fig, ax = plt.subplots(figsize=(10, 6))
    algos_present = df["algorithm"].unique()
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
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_distribution.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    # 3. Time vs beam_width (beam_realmove only)
    fig, ax = plt.subplots(figsize=(10, 6))
    beam_df = df[df["algorithm"] == "beam_realmove"]
    if not beam_df.empty:
        grouped = beam_df.groupby("beam_width")["elapsed_time"].agg(["mean", "std"])
        ax.errorbar(grouped.index, grouped["mean"], yerr=grouped["std"],
                    marker="o", color="#3498db", capsize=3)
        ax.set_xlabel("Beam Width")
        ax.set_ylabel("Execution Time (s)")
        ax.set_title("Sensitivity: Execution Time (mean ± std) — beam_realmove (Beam Width)")
    else:
        ax.text(0.5, 0.5, "No beam_realmove data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Sensitivity: Execution Time (mean ± std) — beam_realmove (Beam Width)")
    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_vs_beam_width_mean.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    fig, ax = plt.subplots(figsize=(10, 6))
    if not beam_df.empty:
        grouped = beam_df.groupby("beam_width")["elapsed_time"].agg(
            median="median",
            q1=lambda s: s.quantile(0.25),
            q3=lambda s: s.quantile(0.75)
        )
        grouped["iqr"] = grouped["q3"] - grouped["q1"]
        ax.errorbar(grouped.index, grouped["median"], yerr=grouped["iqr"],
                    marker="o", color="#3498db", capsize=3)
        ax.set_xlabel("Beam Width")
        ax.set_ylabel("Execution Time (s)")
        ax.set_title("Sensitivity: Execution Time (median ± IQR) — beam_realmove (Beam Width)")
    else:
        ax.text(0.5, 0.5, "No beam_realmove data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Sensitivity: Execution Time (median ± IQR) — beam_realmove (Beam Width)")
    plt.tight_layout()
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_vs_beam_width_median.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    # 4. Time heatmaps: all parameter pairs per algorithm
    skip_heatmaps = skip_heatmaps or set()
    skip_params = skip_params or set()
    for algo in df["algorithm"].unique():
        algo_df = df[df["algorithm"] == algo]
        if algo == "beam_realmove":
            params = ["horizon", "alpha", "beam_width"]
        else:
            params = ["horizon", "alpha"]
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                if (algo, x_param, y_param) in skip_heatmaps or (algo, y_param, x_param) in skip_heatmaps:
                    continue
                fig, ax = plt.subplots(figsize=(10, 6))
                if not algo_df.empty:
                    pivot = algo_df.pivot_table(
                        values="elapsed_time",
                        index=y_param,
                        columns=x_param,
                        aggfunc="mean"
                    )
                    if prefix.startswith("ta43_") and (pivot.shape[0] == 1 or pivot.shape[1] == 1):
                        filepath = _plot_singleton_line(
                            pivot,
                            x_param,
                            y_param,
                            output_dir,
                            f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_mean.png",
                            prefix,
                            f"Line: Execution Time (mean) — {algo}\n{{x_label}} (fixed {{fixed_param}}={{fixed_value}})",
                            "Time (s)",
                            color="#3498db",
                        )
                        if filepath:
                            continue
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
                filepath = os.path.join(
                    output_dir,
                    apply_prefix(prefix, f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_mean.png")
                )
                plt.savefig(filepath, dpi=150, bbox_inches="tight")
                close_fig()

                if not algo_df.empty:
                    pivot = algo_df.pivot_table(
                        values="elapsed_time",
                        index=y_param,
                        columns=x_param,
                        aggfunc="median"
                    )
                    if pivot.empty:
                        continue
                    if prefix.startswith("ta43_") and (pivot.shape[0] == 1 or pivot.shape[1] == 1):
                        filepath = _plot_singleton_line(
                            pivot,
                            x_param,
                            y_param,
                            output_dir,
                            f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_median.png",
                            prefix,
                            f"Line: Execution Time (median) — {algo}\n{{x_label}} (fixed {{fixed_param}}={{fixed_value}})",
                            "Time (s)",
                            color="#3498db",
                        )
                        if filepath:
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
                    filepath = os.path.join(
                        output_dir,
                        apply_prefix(prefix, f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_median.png")
                    )
                    plt.savefig(filepath, dpi=150, bbox_inches="tight")
                    close_fig()

    # === Figure 2: Per-parameter sensitivity (separate files) ===
    params = ["horizon", "alpha"]
    for param in params:
        if param in skip_params:
            continue
        fig, ax = plt.subplots(figsize=(10, 6))
        for algo in df["algorithm"].unique():
            algo_df = df[df["algorithm"] == algo]
            grouped = algo_df.groupby(param)["elapsed_time"].agg(["mean", "std"])
            ax.errorbar(grouped.index, grouped["mean"], yerr=grouped["std"],
                        marker="o", label=algo, color=colors.get(algo, "#95a5a6"), capsize=3)
        ax.set_xlabel(param.replace("_", " ").title())
        ax.set_ylabel("Execution Time (s)")
        ax.set_title(f"Sensitivity: Execution Time (mean ± std) — {param.replace('_', ' ').title()}")
        if param == "horizon":
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.legend(fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"exec_time_vs_{param}_mean.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        fig, ax = plt.subplots(figsize=(10, 6))
        for algo in df["algorithm"].unique():
            algo_df = df[df["algorithm"] == algo]
            grouped = algo_df.groupby(param)["elapsed_time"].agg(
                median="median",
                q1=lambda s: s.quantile(0.25),
                q3=lambda s: s.quantile(0.75)
            )
            grouped["iqr"] = grouped["q3"] - grouped["q1"]
            ax.errorbar(grouped.index, grouped["median"], yerr=grouped["iqr"],
                        marker="o", label=algo, color=colors.get(algo, "#95a5a6"), capsize=3)
        ax.set_xlabel(param.replace("_", " ").title())
        ax.set_ylabel("Execution Time (s)")
        ax.set_title(f"Sensitivity: Execution Time (median ± IQR) — {param.replace('_', ' ').title()}")
        if param == "horizon":
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.legend(fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, f"exec_time_vs_{param}_median.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

    # === Figure 3: Algorithm comparison - time efficiency ===
    # Time per step (efficiency)
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
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_per_step_mean.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

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
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_per_step_median.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    # Total time comparison by horizon (bar chart)
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
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_by_horizon_comparison_mean.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

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
    filepath = os.path.join(output_dir, apply_prefix(prefix, "exec_time_by_horizon_comparison_median.png"))
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    # === Figure 4: Beam search specific - horizon x beam_width heatmaps ===
    if not beam_df.empty:
        # Heatmap: total_sailed (mean)
        fig, ax = plt.subplots(figsize=(10, 6))
        pivot_sailed = beam_df.pivot_table(
            values="total_sailed",
            index="beam_width",
            columns="horizon",
            aggfunc="mean"
        )
        im = ax.imshow(pivot_sailed.values, cmap="YlGn_r", aspect="auto")
        ax.set_xticks(range(len(pivot_sailed.columns)))
        ax.set_yticks(range(len(pivot_sailed.index)))
        ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_sailed.columns], rotation=45)
        ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_sailed.index])
        ax.set_xlabel("Horizon")
        ax.set_ylabel("Beam Width")
        ax.set_title("Heatmap: Total Sailed Distance (mean) — beam_realmove")
        plt.colorbar(im, ax=ax, label="Distance (m)")

        # Add text annotations for sailed
        for i in range(len(pivot_sailed.index)):
            for j in range(len(pivot_sailed.columns)):
                val = pivot_sailed.values[i, j]
                if not np.isnan(val):
                    text_color = "white" if val < pivot_sailed.values.min() + (pivot_sailed.values.max() - pivot_sailed.values.min()) * 0.5 else "black"
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=7, color=text_color)

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, "beam_total_sailed_heatmap_mean.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        # Heatmap: total_sailed (median)
        fig, ax = plt.subplots(figsize=(10, 6))
        pivot_sailed_median = beam_df.pivot_table(
            values="total_sailed",
            index="beam_width",
            columns="horizon",
            aggfunc="median"
        )
        im = ax.imshow(pivot_sailed_median.values, cmap="YlGn_r", aspect="auto")
        ax.set_xticks(range(len(pivot_sailed_median.columns)))
        ax.set_yticks(range(len(pivot_sailed_median.index)))
        ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_sailed_median.columns], rotation=45)
        ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_sailed_median.index])
        ax.set_xlabel("Horizon")
        ax.set_ylabel("Beam Width")
        ax.set_title("Heatmap: Total Sailed Distance (median) — beam_realmove")
        plt.colorbar(im, ax=ax, label="Distance (m)")

        # Add text annotations for sailed (median)
        for i in range(len(pivot_sailed_median.index)):
            for j in range(len(pivot_sailed_median.columns)):
                val = pivot_sailed_median.values[i, j]
                if not np.isnan(val):
                    text_color = "white" if val < pivot_sailed_median.values.min() + (pivot_sailed_median.values.max() - pivot_sailed_median.values.min()) * 0.5 else "black"
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=7, color=text_color)

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, "beam_total_sailed_heatmap_median.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()

        # Heatmap: total_sailed (min)
        fig, ax = plt.subplots(figsize=(10, 6))
        pivot_sailed_min = beam_df.pivot_table(
            values="total_sailed",
            index="beam_width",
            columns="horizon",
            aggfunc="min"
        )
        im = ax.imshow(pivot_sailed_min.values, cmap="YlGn_r", aspect="auto")
        ax.set_xticks(range(len(pivot_sailed_min.columns)))
        ax.set_yticks(range(len(pivot_sailed_min.index)))
        ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_sailed_min.columns], rotation=45)
        ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot_sailed_min.index])
        ax.set_xlabel("Horizon")
        ax.set_ylabel("Beam Width")
        ax.set_title("Heatmap: Total Sailed Distance (min) — beam_realmove")
        plt.colorbar(im, ax=ax, label="Distance (m)")

        # Add text annotations for sailed (min)
        for i in range(len(pivot_sailed_min.index)):
            for j in range(len(pivot_sailed_min.columns)):
                val = pivot_sailed_min.values[i, j]
                if not np.isnan(val):
                    text_color = "white" if val < pivot_sailed_min.values.min() + (pivot_sailed_min.values.max() - pivot_sailed_min.values.min()) * 0.5 else "black"
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=7, color=text_color)

        plt.tight_layout()
        filepath = os.path.join(output_dir, apply_prefix(prefix, "beam_total_sailed_heatmap_min.png"))
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        close_fig()


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

    preferred_order = ["mpc_simplemove", "mpc_realmove", "beam_realmove"]
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
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    close_fig()

    return summary_df


def create_scatter_plots(df, output_dir, prefix="", skip_params=None):
    """Scatter plots: all parameter pairs, colored by each remaining parameter."""
    params = ["horizon", "alpha", "beam_width"]
    skip_params = skip_params or set()
    targets = ["total_sailed", "elapsed_time"]
    for y_param in targets:
        for x_param in params:
            if x_param in skip_params:
                continue
            for color_param in params:
                if color_param == x_param or color_param in skip_params:
                    continue
                subset = df[[x_param, y_param, color_param]].dropna()
                if subset.empty:
                    continue
                fig, ax = plt.subplots(figsize=(10, 7))
                x_vals = subset[x_param]
                y_vals = subset[y_param]
                color_vals = subset[color_param]

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
                ax.set_xlabel(x_param.replace("_", " ").title())
                ax.set_ylabel(y_param.replace("_", " ").title())
                ax.set_title(
                    f"Scatter: {y_param.replace('_', ' ').title()} vs {x_param.replace('_', ' ').title()} — "
                    f"{color_param.replace('_', ' ').title()}\n({len(subset)} runs)"
                )
                plt.tight_layout()
                filename = f"scatter_{y_param}_vs_{x_param}_by_{color_param}.png"
                plt.savefig(os.path.join(output_dir, apply_prefix(prefix, filename)), dpi=150, bbox_inches="tight")
                close_fig()


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

    params = ["horizon", "alpha", "beam_width"]
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
                if prefix.startswith("ta43_") and (pivot.shape[0] == 1 or pivot.shape[1] == 1):
                    filepath = _plot_singleton_line(
                        pivot,
                        x_param,
                        y_param,
                        output_dir,
                        f"unfinished_rate_heatmap_{algo}_{x_param}_vs_{y_param}_mean.png",
                        prefix,
                        f"Line: Unfinished Rate (mean) — {algo}\n{{x_label}} (fixed {{fixed_param}}={{fixed_value}})",
                        "Unfinished Rate",
                        color="#e67e22",
                    )
                    if filepath:
                        continue
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
                filename = f"unfinished_rate_heatmap_{algo}_{x_param}_vs_{y_param}_mean.png"
                plt.savefig(os.path.join(output_dir, apply_prefix(prefix, filename)), dpi=150, bbox_inches="tight")
                close_fig()

                pivot_median = subset.pivot_table(
                    values="unfinished",
                    index=y_param,
                    columns=x_param,
                    aggfunc="median"
                )
                if pivot_median.empty:
                    continue
                if prefix.startswith("ta43_") and (pivot_median.shape[0] == 1 or pivot_median.shape[1] == 1):
                    filepath = _plot_singleton_line(
                        pivot_median,
                        x_param,
                        y_param,
                        output_dir,
                        f"unfinished_rate_heatmap_{algo}_{x_param}_vs_{y_param}_median.png",
                        prefix,
                        f"Line: Unfinished Rate (median) — {algo}\n{{x_label}} (fixed {{fixed_param}}={{fixed_value}})",
                        "Unfinished Rate",
                        color="#e67e22",
                    )
                    if filepath:
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
                filename = f"unfinished_rate_heatmap_{algo}_{x_param}_vs_{y_param}_median.png"
                plt.savefig(os.path.join(output_dir, apply_prefix(prefix, filename)), dpi=150, bbox_inches="tight")
                close_fig()


def create_failure_probability_plots(df_all, metadata, output_dir, prefix="", skip_params=None):
    """Create failure probability vs parameter comparison plots."""
    if df_all.empty:
        return

    skip_params = skip_params or set()
    params = ["horizon", "alpha", "beam_width"]
    for param in params:
        if param in skip_params:
            continue
        if param not in df_all.columns:
            continue
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
        filename = f"unfinished_rate_compare_{param}_mean.png"
        plt.savefig(os.path.join(output_dir, apply_prefix(prefix, filename)), dpi=150, bbox_inches="tight")
        close_fig()

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
        filename = f"unfinished_rate_compare_{param}_median.png"
        plt.savefig(os.path.join(output_dir, apply_prefix(prefix, filename)), dpi=150, bbox_inches="tight")
        close_fig()


def main():
    parser = argparse.ArgumentParser(description="Visualize benchmark results")
    parser.add_argument("--input", default="benchmark_results.json", help="Input JSON file")
    parser.add_argument("--output-dir", default=".", help="Output directory for images")
    parser.add_argument("--display", action="store_true", help="Display figures after saving")
    args = parser.parse_args()
    global DISPLAY
    DISPLAY = args.display

    # Resolve paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, args.input) if not os.path.isabs(args.input) else args.input
    output_dir = os.path.join(script_dir, args.output_dir) if not os.path.isabs(args.output_dir) else args.output_dir

    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading results from {input_path}...")
    df, metadata, df_all = load_results(input_path)
    print(f"Loaded {len(df)} finished races (distance_to_mark <= goal)")

    print("\nGenerating visualizations...")

    # 1. Heatmaps (all parameter pairs, total_sailed and elapsed_time)
    print("  Creating heatmaps...")
    for algo in df["algorithm"].unique():
        if algo == "beam_realmove":
            params = ["horizon", "alpha", "beam_width"]
        else:
            params = ["horizon", "alpha"]
        metrics = ["total_sailed", "elapsed_time"]
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                for metric in metrics:
                    create_heatmap(df, algo, x_param, y_param, metric, output_dir, agg="mean")
                    create_heatmap(df, algo, x_param, y_param, metric, output_dir, agg="median")
                if "total_sailed" in metrics:
                    create_heatmap(df, algo, x_param, y_param, "total_sailed", output_dir, agg="min")

    print("  Creating coverage heatmaps...")
    for algo in df_all["algorithm"].unique():
        if algo == "beam_realmove":
            params = ["horizon", "alpha", "beam_width"]
        else:
            params = ["horizon", "alpha"]
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                create_coverage_heatmap(df_all, metadata, algo, x_param, y_param, output_dir)

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

    print("\n" + "=" * 60)
    print("VISUALIZATION COMPLETE")
    print("=" * 60)
    print(f"\nOutput directory: {output_dir}")
    print("\nGenerated files:")
    for f in sorted(os.listdir(output_dir)):
        if f.endswith((".png", ".csv")):
            print(f"  - {f}")

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
