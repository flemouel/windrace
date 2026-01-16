#!/usr/bin/env python3
"""
Visualization script for benchmark results.

Generates:
1. Heatmaps: parameter combinations (alpha vs horizon, tackangle vs beam-width, etc.)
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


def create_heatmap(df, algo, x_param, y_param, metric, output_dir, fixed_params=None, agg="mean"):
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
    ax.set_title(f"{algo}: {metric_label}\n{x_param} vs {y_param}{fixed_str} ({agg} over other params)")

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
    filepath = os.path.join(output_dir, filename)
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()
    return filepath


def create_algorithm_comparison(df, output_dir):
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
    ax.set_title("Algorithm Comparison: Total Sailed Distance\n(mean +/- std across all parameter combinations, finished races only)")

    # Add value labels
    for i, (bar, mean_val) in enumerate(zip(bars, stats["mean"])):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + stats["std"].iloc[i] + 0.02 * stats["mean"].max(),
                f"{mean_val:.1f}", ha="center", va="bottom", fontsize=10)

    plt.tight_layout()
    filepath = os.path.join(output_dir, "compare_total_sailed_mean.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()

    # Best results per algorithm
    fig, ax = plt.subplots(figsize=(10, 6))

    best_per_algo = df.loc[df.groupby("algorithm")[metric].idxmin()]

    bar_colors = [colors.get(algo, "#95a5a6") for algo in best_per_algo["algorithm"]]

    x = range(len(best_per_algo))
    bars = ax.bar(x, best_per_algo[metric], color=bar_colors, alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(best_per_algo["algorithm"], rotation=15)
    ax.set_ylabel("Total Sailed (m)")
    ax.set_title("Best Total Sailed Distance per Algorithm\n(finished races only)")

    # Add parameter info
    for i, (_, row) in enumerate(best_per_algo.iterrows()):
        params = f"h={row['horizon']}, ta={row['tackangle']}, a={row['alpha']}"
        if row["algorithm"] == "beam_realmove":
            params += f", bw={row['beam_width']}"
        ax.text(i, bars[i].get_height() + 0.01 * best_per_algo[metric].max(),
                f"{row[metric]:.1f}\n({params})", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    filepath = os.path.join(output_dir, "compare_total_sailed_min.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()


def create_parameter_sensitivity(df, output_dir):
    """Create plots showing how each parameter affects total_sailed."""
    params = ["horizon", "tackangle", "alpha"]
    metric = "total_sailed"
    algos = df["algorithm"].unique()
    colors = {"beam_realmove": "#3498db", "mpc_realmove": "#e74c3c", "mpc_simplemove": "#2ecc71"}

    for param in params:
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
        ax.set_title(f"Effect of {param.replace('_', ' ').title()} on Total Sailed\n(finished races only)")
        ax.legend()

        if param == "horizon":
            ax.set_xscale("log")

        plt.tight_layout()
        filepath = os.path.join(output_dir, f"sensitivity_{param}_mean_total_sailed.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()

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
        ax.set_title(f"Best Total Sailed vs {param.replace('_', ' ').title()}\n(finished races only)")
        ax.legend()

        if param == "horizon":
            ax.set_xscale("log")

        plt.tight_layout()
        filepath = os.path.join(output_dir, f"sensitivity_{param}_min_total_sailed.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()

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
        ax.set_title("Effect of Beam Width on Total Sailed\n(beam_realmove only, finished races)")

        plt.tight_layout()
        filepath = os.path.join(output_dir, "sensitivity_beam_width_mean_total_sailed.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()

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
        ax.set_title("Best Total Sailed vs Beam Width\n(beam_realmove only, finished races)")

        plt.tight_layout()
        filepath = os.path.join(output_dir, "sensitivity_beam_width_min_total_sailed.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()


def create_execution_time_analysis(df, output_dir):
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
    ax.set_title("Execution Time Distribution")
    plt.tight_layout()
    filepath = os.path.join(output_dir, "exec_time_distribution.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()

    # 3. Time vs beam_width (beam_realmove only)
    fig, ax = plt.subplots(figsize=(10, 6))
    beam_df = df[df["algorithm"] == "beam_realmove"]
    if not beam_df.empty:
        grouped = beam_df.groupby("beam_width")["elapsed_time"].agg(["mean", "std"])
        ax.errorbar(grouped.index, grouped["mean"], yerr=grouped["std"],
                    marker="o", color="#3498db", capsize=3)
        ax.set_xlabel("Beam Width")
        ax.set_ylabel("Execution Time (s)")
        ax.set_title("Execution Time vs Beam Width\n(beam_realmove)")
    else:
        ax.text(0.5, 0.5, "No beam_realmove data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Execution Time vs Beam Width\n(beam_realmove)")
    plt.tight_layout()
    filepath = os.path.join(output_dir, "exec_time_vs_beam_width_mean.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()

    # 4. Time heatmaps: all parameter pairs per algorithm
    for algo in df["algorithm"].unique():
        algo_df = df[df["algorithm"] == algo]
        if algo == "beam_realmove":
            params = ["horizon", "tackangle", "alpha", "beam_width"]
        else:
            params = ["horizon", "tackangle", "alpha"]
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
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
                    ax.set_title(f"Execution Time Heatmap\n({algo}, mean over other params)")
                    plt.colorbar(im, ax=ax, label="Time (s)")
                    for row in range(len(pivot.index)):
                        for col in range(len(pivot.columns)):
                            val = pivot.values[row, col]
                            if not np.isnan(val):
                                text_color = "white" if val > pivot.values.max() * 0.5 else "black"
                                ax.text(col, row, f"{val:.1f}", ha="center", va="center", fontsize=7, color=text_color)
                else:
                    ax.text(0.5, 0.5, f"No {algo} data", ha="center", va="center", transform=ax.transAxes)
                    ax.set_title(f"Execution Time Heatmap\n({algo}, mean over other params)")
                plt.tight_layout()
                filepath = os.path.join(output_dir, f"exec_time_{algo}_{x_param}_vs_{y_param}_heatmap_mean.png")
                plt.savefig(filepath, dpi=150, bbox_inches="tight")
                plt.close()

    # === Figure 2: Per-parameter sensitivity (separate files) ===
    params = ["horizon", "tackangle", "alpha"]
    for param in params:
        fig, ax = plt.subplots(figsize=(10, 6))
        for algo in df["algorithm"].unique():
            algo_df = df[df["algorithm"] == algo]
            grouped = algo_df.groupby(param)["elapsed_time"].agg(["mean", "std"])
            ax.errorbar(grouped.index, grouped["mean"], yerr=grouped["std"],
                        marker="o", label=algo, color=colors.get(algo, "#95a5a6"), capsize=3)
        ax.set_xlabel(param.replace("_", " ").title())
        ax.set_ylabel("Execution Time (s)")
        ax.set_title(f"Time vs {param.replace('_', ' ').title()}")
        if param == "horizon":
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.legend(fontsize=8)

        plt.tight_layout()
        filepath = os.path.join(output_dir, f"exec_time_vs_{param}.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()

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
    ax.set_title("Computation Efficiency: Time per Step")
    ax.set_xscale("log")
    ax.legend()
    plt.tight_layout()
    filepath = os.path.join(output_dir, "exec_time_per_step.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()

    # Total time comparison by horizon (bar chart)
    fig, ax = plt.subplots(figsize=(10, 6))
    horizons = sorted(df["horizon"].unique())
    x = np.arange(len(horizons))
    width = 0.25
    algos_list = list(df["algorithm"].unique())

    for i, algo in enumerate(algos_list):
        algo_df = df[df["algorithm"] == algo]
        means = [algo_df[algo_df["horizon"] == h]["elapsed_time"].mean() for h in horizons]
        # Handle NaN values
        means = [m if not np.isnan(m) else 0 for m in means]
        ax.bar(x + i * width, means, width, label=algo, color=colors.get(algo, "#95a5a6"), alpha=0.8)

    ax.set_xlabel("Horizon")
    ax.set_ylabel("Execution Time (s)")
    ax.set_title("Execution Time by Horizon (comparison)")
    ax.set_xticks(x + width)
    ax.set_xticklabels([str(h) for h in horizons], rotation=45)
    ax.legend()
    ax.set_yscale("log")

    plt.tight_layout()
    filepath = os.path.join(output_dir, "exec_time_by_horizon_comparison.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()

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
        ax.set_title("Total Sailed (m) - Quality\n(beam_realmove, mean over other params)")
        plt.colorbar(im, ax=ax, label="Distance (m)")

        # Add text annotations for sailed
        for i in range(len(pivot_sailed.index)):
            for j in range(len(pivot_sailed.columns)):
                val = pivot_sailed.values[i, j]
                if not np.isnan(val):
                    text_color = "white" if val < pivot_sailed.values.min() + (pivot_sailed.values.max() - pivot_sailed.values.min()) * 0.5 else "black"
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=7, color=text_color)

        plt.tight_layout()
        filepath = os.path.join(output_dir, "beam_total_sailed_heatmap_mean.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()

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
        ax.set_title("Total Sailed (m) - Quality\n(beam_realmove, min over other params)")
        plt.colorbar(im, ax=ax, label="Distance (m)")

        # Add text annotations for sailed (min)
        for i in range(len(pivot_sailed_min.index)):
            for j in range(len(pivot_sailed_min.columns)):
                val = pivot_sailed_min.values[i, j]
                if not np.isnan(val):
                    text_color = "white" if val < pivot_sailed_min.values.min() + (pivot_sailed_min.values.max() - pivot_sailed_min.values.min()) * 0.5 else "black"
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=7, color=text_color)

        plt.tight_layout()
        filepath = os.path.join(output_dir, "beam_total_sailed_heatmap_min.png")
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()


def create_summary_table(df, df_all, output_dir):
    """Create a summary table of results per algorithm."""
    def format_mean_std(series, decimals=1):
        mean = series.mean()
        std = series.std()
        if np.isnan(mean) or np.isnan(std):
            return "n/a"
        return f"{mean:.{decimals}f} ± {std:.{decimals}f}"
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
            f"h={best_sailed['horizon']}, ta={best_sailed['tackangle']}, a={best_sailed['alpha']}" +
            (f", bw={best_sailed['beam_width']}" if algo == "beam_realmove" else "")
        ) if best_sailed is not None else "n/a"

        finished_count = len(algo_df)
        total_count = len(algo_all)
        success_rate = finished_count / total_count if total_count > 0 else 0
        summary_data.append({
            "Algorithm": algo,
            "Mean Distance (m)": format_mean_std(algo_df["total_sailed"]),
            "Mean Elapsed Time (s)": format_mean_std(algo_df["elapsed_time"]),
            "Best Distance (m)": f"{best_distance:.1f}" if not np.isnan(best_distance) else "n/a",
            "Elapsed Time for Best Distance (s)": f"{best_elapsed:.2f}" if not np.isnan(best_elapsed) else "n/a",
            "Params": best_params,
            "Finished Races": f"{finished_count}/{total_count}",
            "Success Rate": f"{(success_rate * 100):.1f}%",
        })

    summary_df = pd.DataFrame(summary_data)

    # Save as CSV
    summary_df.to_csv(os.path.join(output_dir, "summary_results.csv"), index=False)

    # Create figure with table
    fig, ax = plt.subplots(figsize=(16, 4))
    ax.axis("off")

    table = ax.table(
        cellText=summary_df.values,
        colLabels=summary_df.columns,
        cellLoc="center",
        loc="center",
        colColours=["#3498db"] * len(summary_df.columns)
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.5)

    # Style header
    for i in range(len(summary_df.columns)):
        table[(0, i)].set_text_props(color="white", weight="bold")

    plt.title("Summary: Results per Algorithm", fontsize=14, pad=20)
    plt.tight_layout()
    filepath = os.path.join(output_dir, "summary_results_table.png")
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()

    return summary_df


def create_scatter_plots(df, output_dir):
    """Scatter plots: all parameter pairs, colored by each remaining parameter."""
    params = ["horizon", "tackangle", "alpha", "beam_width"]
    targets = ["total_sailed", "elapsed_time"]
    for y_param in targets:
        for x_param in params:
            for color_param in params:
                if color_param == x_param:
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
                    f"{y_param.replace('_', ' ').title()} vs {x_param.replace('_', ' ').title()} "
                    f"(colored by {color_param.replace('_', ' ').title()})\n({len(subset)} runs)"
                )
                plt.tight_layout()
                filename = f"scatter_{y_param}_vs_{x_param}_by_{color_param}.png"
                plt.savefig(os.path.join(output_dir, filename), dpi=150, bbox_inches="tight")
                plt.close()


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


def create_unfinished_rate_heatmaps(df_all, metadata, output_dir):
    """Create heatmaps of unfinished rate for each parameter pair."""
    if df_all.empty:
        return

    finished_mask = compute_finished_mask(df_all, metadata)
    if finished_mask is None:
        return

    params = ["horizon", "tackangle", "alpha", "beam_width"]
    for i in range(len(params)):
        for j in range(i + 1, len(params)):
            x_param = params[i]
            y_param = params[j]
            if x_param not in df_all.columns or y_param not in df_all.columns:
                continue
            subset = df_all[[x_param, y_param]].copy()
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
            fig, ax = plt.subplots(figsize=(10, 7))
            im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto", vmin=0, vmax=1)
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_yticks(range(len(pivot.index)))
            ax.set_xticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.columns], rotation=45)
            ax.set_yticklabels([f"{v:.2f}" if isinstance(v, float) else str(v) for v in pivot.index])
            ax.set_xlabel(x_param.replace("_", " ").title())
            ax.set_ylabel(y_param.replace("_", " ").title())
            ax.set_title(f"Unfinished Rate\n{x_param} vs {y_param}")
            plt.colorbar(im, ax=ax, label="Unfinished Rate")
            for row in range(len(pivot.index)):
                for col in range(len(pivot.columns)):
                    val = pivot.values[row, col]
                    if not np.isnan(val):
                        text_color = "white" if val > 0.5 else "black"
                        ax.text(col, row, f"{val:.2f}", ha="center", va="center", fontsize=7, color=text_color)
            plt.tight_layout()
            filename = f"unfinished_rate_heatmap_{x_param}_vs_{y_param}.png"
            plt.savefig(os.path.join(output_dir, filename), dpi=150, bbox_inches="tight")
            plt.close()


def create_failure_probability_plots(df_all, metadata, output_dir):
    """Create failure probability vs parameter plots."""
    if df_all.empty:
        return

    finished_mask = compute_finished_mask(df_all, metadata)
    if finished_mask is None:
        return

    params = ["horizon", "tackangle", "alpha", "beam_width"]
    for param in params:
        if param not in df_all.columns:
            continue
        subset = df_all[[param]].copy()
        subset["unfinished"] = (~finished_mask).astype(int)
        subset = subset.dropna()
        if subset.empty:
            continue
        grouped = subset.groupby(param)["unfinished"].mean().reset_index()
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.plot(grouped[param], grouped["unfinished"], marker="o", linestyle="-", color="#e74c3c")
        ax.set_xlabel(param.replace("_", " ").title())
        ax.set_ylabel("Unfinished Rate")
        ax.set_title(f"Unfinished Rate vs {param.replace('_', ' ').title()}")
        ax.set_ylim(0, 1)
        if param == "horizon":
            ax.set_xscale("log")
        plt.tight_layout()
        filename = f"unfinished_rate_vs_{param}.png"
        plt.savefig(os.path.join(output_dir, filename), dpi=150, bbox_inches="tight")
        plt.close()


def main():
    parser = argparse.ArgumentParser(description="Visualize benchmark results")
    parser.add_argument("--input", default="benchmark_results.json", help="Input JSON file")
    parser.add_argument("--output-dir", default=".", help="Output directory for images")
    args = parser.parse_args()

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
            params = ["horizon", "tackangle", "alpha", "beam_width"]
        else:
            params = ["horizon", "tackangle", "alpha"]
        metrics = ["total_sailed", "elapsed_time"]
        for i in range(len(params)):
            for j in range(i + 1, len(params)):
                x_param = params[i]
                y_param = params[j]
                for metric in metrics:
                    create_heatmap(df, algo, x_param, y_param, metric, output_dir, agg="mean")
                if "total_sailed" in metrics:
                    create_heatmap(df, algo, x_param, y_param, "total_sailed", output_dir, agg="min")

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


if __name__ == "__main__":
    main()
