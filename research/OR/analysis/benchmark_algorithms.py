#!/usr/bin/env python3
"""
Benchmark script for comparing trajectory planning algorithms.

Runs grid search over parameter ranges and collects metric:
- total_sailed: total distance traveled (only for finished races)

Algorithms tested:
- beam_realmove.py
- mpc_realmove.py
- mpc_simplemove.py
- adp_realmove.py
- spst_realmove.py
- sa_realmove.py

Features:
- Incremental save: results saved after each test
- Resume capability: --resume to continue from previous run
- Graceful interruption: Ctrl+C saves current progress
"""

import csv
import itertools
import json
import os
import random
import signal
import shutil
import subprocess
import sys
import time
import heapq
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime
from threading import Lock


# Fixed parameters
FIXED_PARAMS = {
    "start_lat": 18.38142820098676,
    "start_lng": -64.56660471988445,
    "finish_lat": 18.40857035782242,
    "finish_lng": -64.53339266400592,
    "goal": 20,
    "verbose": 1,
    "start_index": 600,
    "tackangle": 43,
    "near_threshold": 200,
    "near_delay": 10,
    "far_delay": 20,
    "seed": 42,
}

# Parameter ranges for grid search
PARAM_RANGES = {
#    "horizon": [10, 20, 30, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 600, 800, 1000, 1200, 1500, 2000],
    "horizon": [10, 20, 30, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 600, 800],
    "alpha": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5],
    "beam_width": [5, 10, 20, 30, 50, 75, 100, 150, 175, 200, 225, 250, 275, 300, 325, 350, 375, 400, 500, 600, 800, 1000],
    "scenarios": [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "dir_noise": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "speed_noise": [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20],
    "gamma": [0.9, 0.95],
    "lr": [1e-6, 1e-5],
    "goal_penalty": [20, 50],
    "epsilon": [0.0, 0.1],
    "epsilon_decay": [1.0, 0.9995],
    "epsilon_min": [0.0, 0.01],
    "approx": ["linear", "poly", "network"],
    "hidden_size": [8, 16],
    "l2": [0.0, 1e-5],
    "normalize_features": [False, True],
    "initial_temp": [10, 25, 50, 75, 100, 150, 200, 300, 500],
    "cooling_rate": [0.98, 0.99, 0.993, 0.995, 0.997, 0.999, 0.9995],
    "min_temp": [0.01, 0.05, 0.1, 0.5, 1.0],
    "reheat_factor": [1.0, 1.5, 2.0],
}
BASE_PARAM_RANGES = {k: list(v) for k, v in PARAM_RANGES.items()}

ALGO_SPECS = {
    "mpc_realmove": {
        "script": "mpc_realmove.py",
        "label": "mpc_r",
        "grid_params": ["horizon", "alpha"],
    },
    "mpc_simplemove": {
        "script": "mpc_simplemove.py",
        "label": "mpc_s",
        "grid_params": ["horizon", "alpha"],
    },
    "beam_realmove": {
        "script": "beam_realmove.py",
        "label": "beam",
        "grid_params": ["horizon", "alpha", "beam_width"],
    },
    "adp_realmove": {
        "script": "adp_realmove.py",
        "label": "adp",
        "grid_params": [
            "horizon", "alpha", "gamma", "lr", "goal_penalty", "epsilon",
            "epsilon_decay", "epsilon_min", "approx", "hidden_size", "l2", "normalize_features",
        ],
    },
    "spst_realmove": {
        "script": "spst_realmove.py",
        "label": "spst",
        "grid_params": ["horizon", "alpha", "scenarios", "dir_noise", "speed_noise"],
    },
    "sa_realmove": {
        "script": "sa_realmove.py",
        "label": "sa",
        "grid_params": ["horizon", "alpha", "initial_temp", "cooling_rate", "min_temp", "reheat_factor"],
    },
}
DEFAULT_ALGO_ORDER = list(ALGO_SPECS.keys())
VALID_ALGOS = set(ALGO_SPECS.keys())
DEFAULT_WINDOW_SIZE = 500

PARAM_RESULT_FIELDS = [
    "horizon", "tackangle", "alpha", "beam_width", "scenarios", "dir_noise", "speed_noise", "seed",
    "gamma", "lr", "goal_penalty", "epsilon", "epsilon_decay", "epsilon_min",
    "approx", "hidden_size", "l2", "normalize_features",
    "initial_temp", "cooling_rate", "min_temp", "reheat_factor",
]
METRIC_RESULT_FIELDS = [
    "total_sailed", "nb_tacks", "steps", "distance_to_mark",
    "elapsed_time", "worker_elapsed_time", "orchestrator_overhead_time", "effective_elapsed_time",
    "finished", "success",
]
RESULT_FIELDNAMES = ["algorithm", *PARAM_RESULT_FIELDS, *METRIC_RESULT_FIELDS]

# Total tests per algorithm (derived from PARAM_RANGES)
def _range_len(name, ranges=None):
    src = ranges if ranges is not None else PARAM_RANGES
    return len(src.get(name, []))


def compute_algo_totals(param_ranges=None):
    src = param_ranges if param_ranges is not None else PARAM_RANGES
    totals = {}
    for algo_name, spec in ALGO_SPECS.items():
        total = 1
        for param_name in spec["grid_params"]:
            total *= _range_len(param_name, src)
        totals[algo_name] = total
    return totals


def _format_allowed_values(values):
    return ", ".join(str(v) for v in values)


def _parse_value_token(token, allowed_values, param_name):
    t = token.strip()
    if t == "":
        raise ValueError(f"Empty value in --range for '{param_name}'")

    if all(isinstance(v, bool) for v in allowed_values):
        s = t.lower()
        if s in {"true", "1", "yes"}:
            val = True
        elif s in {"false", "0", "no"}:
            val = False
        else:
            raise ValueError(
                f"Invalid boolean value '{token}' for '{param_name}'. Allowed: {_format_allowed_values(allowed_values)}"
            )
        if val not in allowed_values:
            raise ValueError(
                f"Value '{token}' not allowed for '{param_name}'. Allowed: {_format_allowed_values(allowed_values)}"
            )
        return val

    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in allowed_values):
        try:
            x = float(t)
        except ValueError:
            raise ValueError(
                f"Invalid numeric value '{token}' for '{param_name}'. Allowed: {_format_allowed_values(allowed_values)}"
            )
        for v in allowed_values:
            if abs(float(v) - x) <= 1e-12:
                return v
        raise ValueError(
            f"Value '{token}' not in allowed values for '{param_name}'. Allowed: {_format_allowed_values(allowed_values)}"
        )

    for v in allowed_values:
        if str(v) == t:
            return v
    raise ValueError(
        f"Value '{token}' not in allowed values for '{param_name}'. Allowed: {_format_allowed_values(allowed_values)}"
    )


def apply_range_overrides(base_ranges, range_overrides):
    effective = {k: list(v) for k, v in base_ranges.items()}
    if not range_overrides:
        return effective

    for spec in range_overrides:
        s = (spec or "").strip()
        if "=" not in s:
            raise ValueError(f"Invalid --range '{spec}'. Expected format: name=v1,v2 or name=min:max")
        name, expr = s.split("=", 1)
        name = name.strip()
        expr = expr.strip()
        if not name:
            raise ValueError(f"Invalid --range '{spec}': missing parameter name")
        if name not in base_ranges:
            all_vars = ", ".join(base_ranges.keys())
            raise ValueError(f"Unknown range variable '{name}'. Available variables: {all_vars}")
        allowed = list(base_ranges[name])
        if not expr:
            raise ValueError(f"Empty range for '{name}'. Allowed values: {_format_allowed_values(allowed)}")

        selected = []
        if ":" in expr:
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in allowed):
                raise ValueError(
                    f"Range interval '{name}={expr}' only supports numeric params. Allowed values: {_format_allowed_values(allowed)}"
                )
            lo_s, hi_s = expr.split(":", 1)
            try:
                lo = float(lo_s.strip())
                hi = float(hi_s.strip())
            except ValueError:
                raise ValueError(
                    f"Invalid numeric interval '{name}={expr}'. Allowed values: {_format_allowed_values(allowed)}"
                )
            if lo > hi:
                lo, hi = hi, lo
            selected = [v for v in allowed if lo <= float(v) <= hi]
            if not selected:
                raise ValueError(
                    f"Interval '{name}={expr}' selects no value. Allowed values: {_format_allowed_values(allowed)}"
                )
        else:
            tokens = [t.strip() for t in expr.split(",") if t.strip() != ""]
            if not tokens:
                raise ValueError(f"Invalid list for '{name}'. Allowed values: {_format_allowed_values(allowed)}")
            seen = set()
            for tok in tokens:
                v = _parse_value_token(tok, allowed, name)
                k = str(v)
                if k in seen:
                    continue
                seen.add(k)
                selected.append(v)
            if not selected:
                raise ValueError(
                    f"List '{name}={expr}' selects no value. Allowed values: {_format_allowed_values(allowed)}"
                )

        effective[name] = selected

    return effective

# Base directory (where the algorithm scripts are located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Root directory (windgame)
ROOT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))


def _build_algorithm_command(algo_name, params):
    script_path = os.path.join(BASE_DIR, ALGO_SPECS[algo_name]["script"])
    wind_path = os.path.join(ROOT_DIR, "winddata", "wind_data.json")

    cmd = [
        sys.executable, script_path,
        "--wind", wind_path,
        "--start-lat", str(FIXED_PARAMS["start_lat"]),
        "--start-lng", str(FIXED_PARAMS["start_lng"]),
        "--finish-lat", str(FIXED_PARAMS["finish_lat"]),
        "--finish-lng", str(FIXED_PARAMS["finish_lng"]),
        "--goal", str(FIXED_PARAMS["goal"]),
        "--verbose", str(FIXED_PARAMS["verbose"]),
        "--start-index", str(FIXED_PARAMS["start_index"]),
        "--horizon", str(params["horizon"]),
        "--tackangle", str(FIXED_PARAMS["tackangle"]),
        "--alpha", str(params["alpha"]),
    ]

    # Add algorithm-specific parameters
    if algo_name == "beam_realmove":
        cmd.extend([
            "--beam-width", str(params["beam_width"]),
            "--near-threshold", str(FIXED_PARAMS["near_threshold"]),
            "--near-delay", str(FIXED_PARAMS["near_delay"]),
            "--far-delay", str(FIXED_PARAMS["far_delay"]),
        ])
    elif algo_name == "mpc_realmove":
        cmd.extend([
            "--near-threshold", str(FIXED_PARAMS["near_threshold"]),
            "--near-delay", str(FIXED_PARAMS["near_delay"]),
            "--far-delay", str(FIXED_PARAMS["far_delay"]),
        ])
    elif algo_name == "adp_realmove":
        cmd.extend([
            "--near-threshold", str(FIXED_PARAMS["near_threshold"]),
            "--near-delay", str(FIXED_PARAMS["near_delay"]),
            "--far-delay", str(FIXED_PARAMS["far_delay"]),
            "--goal-penalty", str(params["goal_penalty"]),
            "--gamma", str(params["gamma"]),
            "--lr", str(params["lr"]),
            "--horizon", str(params["horizon"]),
            "--epsilon", str(params["epsilon"]),
            "--epsilon-decay", str(params["epsilon_decay"]),
            "--epsilon-min", str(params["epsilon_min"]),
            "--approx", str(params["approx"]),
            "--hidden-size", str(params["hidden_size"]),
            "--l2", str(params["l2"]),
        ])
        if params.get("normalize_features"):
            cmd.append("--normalize-features")
    elif algo_name == "spst_realmove":
        cmd.extend([
            "--near-threshold", str(FIXED_PARAMS["near_threshold"]),
            "--near-delay", str(FIXED_PARAMS["near_delay"]),
            "--far-delay", str(FIXED_PARAMS["far_delay"]),
            "--scenarios", str(params["scenarios"]),
            "--dir-noise", str(params["dir_noise"]),
            "--speed-noise", str(params["speed_noise"]),
            "--seed", str(FIXED_PARAMS["seed"]),
        ])
    elif algo_name == "sa_realmove":
        cmd.extend([
            "--near-threshold", str(FIXED_PARAMS["near_threshold"]),
            "--near-delay", str(FIXED_PARAMS["near_delay"]),
            "--far-delay", str(FIXED_PARAMS["far_delay"]),
            "--initial-temp", str(params["initial_temp"]),
            "--cooling-rate", str(params["cooling_rate"]),
            "--min-temp", str(params["min_temp"]),
            "--reheat-factor", str(params["reheat_factor"]),
            "--seed", str(FIXED_PARAMS["seed"]),
        ])
    # mpc_simplemove doesn't have near/far delay parameters
    return cmd


def _parse_algorithm_output(output, elapsed):
    total_sailed = None
    nb_tacks = None
    steps = None
    distance_to_mark = None

    for line in output.strip().split("\n"):
        if line.startswith("total_sailed:"):
            total_sailed = float(line.split(":")[1].strip().replace(" m", ""))
        elif line.startswith("tacks:"):
            # Parse "tacks: ['P123', 'S456'] ... total 5 tack decisions"
            if "total" in line:
                parts = line.split("total")
                nb_tacks = int(parts[1].strip().split()[0])
            else:
                nb_tacks = 0
        elif line.startswith("steps:"):
            steps = int(line.split(":")[1].strip())
        elif line.startswith("distance_to_mark:"):
            dist_str = line.split(":")[1].strip().replace(" m", "")
            if dist_str != "-":
                distance_to_mark = float(dist_str)

    finished = distance_to_mark is not None and distance_to_mark <= FIXED_PARAMS["goal"]
    return {
        "total_sailed": total_sailed,
        "nb_tacks": nb_tacks,
        "steps": steps,
        "distance_to_mark": distance_to_mark,
        "elapsed_time": elapsed,
        "finished": finished,
        "success": True
    }


def _truncate_text(text, limit=400):
    if text is None:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def run_algorithm(algo_name, params, timeout=300):
    """
    Run a single algorithm with given parameters.
    Returns dict with results or None on failure.
    """
    cmd = _build_algorithm_command(algo_name, params)

    try:
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=BASE_DIR
        )
        elapsed = time.time() - start_time

        if result.returncode != 0:
            return {
                "success": False,
                "error": (
                    f"{algo_name} exited with code {result.returncode}"
                    + (
                        f": {_truncate_text(result.stderr)}"
                        if result.stderr and result.stderr.strip()
                        else ""
                    )
                ),
                "elapsed_time": elapsed,
                "finished": False,
            }
        return _parse_algorithm_output(result.stdout, elapsed)

    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"{algo_name} timeout after {timeout}s", "finished": False}
    except Exception as e:
        return {"success": False, "error": f"{algo_name} failed: {e}", "finished": False}


def run_single_test(args):
    """Wrapper for parallel execution."""
    algo_name, params, test_id = args
    result = run_algorithm(algo_name, params)
    return algo_name, params, result, test_id


def _init_worker_ignore_sigint():
    """Worker initializer: let main process handle Ctrl+C."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass


def generate_test_cases(verbose=0, param_ranges=None, algo_totals=None):
    """Generate all test cases for grid search."""
    effective_ranges = param_ranges if param_ranges is not None else PARAM_RANGES
    effective_totals = algo_totals if algo_totals is not None else compute_algo_totals(effective_ranges)
    test_cases = []
    test_id = 0
    total_expected = sum(effective_totals.values())
    print(f"Generating test cases (expected total: {total_expected})...")
    if total_expected <= 0:
        return test_cases

    counts = {}
    last_pct = -1
    for algo_name in DEFAULT_ALGO_ORDER:
        spec = ALGO_SPECS[algo_name]
        start_count = test_id
        value_lists = [effective_ranges[param_name] for param_name in spec["grid_params"]]
        for combo in itertools.product(*value_lists):
            params = {"tackangle": FIXED_PARAMS["tackangle"], "beam_width": None}
            params.update(dict(zip(spec["grid_params"], combo)))
            test_cases.append((algo_name, params, test_id))
            test_id += 1
            pct = 100.0 * test_id / total_expected
            if int(pct) != last_pct and int(pct) % 10 == 0:
                print(render_progress_line("generation", pct, width=20), end="", flush=True)
                last_pct = int(pct)
        counts[algo_name] = test_id - start_count

    print(render_progress_line("generation", 100.0, suffix="   ", width=20), end="", flush=True)
    print()
    if verbose > 0:
        for algo in DEFAULT_ALGO_ORDER:
            if algo in counts:
                print(f"  {algo}: {counts[algo]}")
        print(f"  generated {len(test_cases)} test cases")

    return test_cases


def algo_param_pairs(algo_name):
    params = algo_param_list(algo_name)
    return [(params[i], params[j]) for i in range(len(params)) for j in range(i + 1, len(params))]

def algo_param_list(algo_name):
    spec = ALGO_SPECS.get(algo_name)
    if spec is None:
        return []
    return list(spec["grid_params"])


def algo_label(algo_name):
    spec = ALGO_SPECS.get(algo_name)
    if spec is None:
        return algo_name
    return spec["label"]


def build_result_row(algo_name, params, result):
    row = {
        "algorithm": algo_name,
        "horizon": params["horizon"],
        "tackangle": params["tackangle"],
        "alpha": params["alpha"],
        "beam_width": params.get("beam_width"),
        "scenarios": params.get("scenarios"),
        "dir_noise": params.get("dir_noise"),
        "speed_noise": params.get("speed_noise"),
        "seed": FIXED_PARAMS["seed"],
        "gamma": params.get("gamma"),
        "lr": params.get("lr"),
        "goal_penalty": params.get("goal_penalty"),
        "epsilon": params.get("epsilon"),
        "epsilon_decay": params.get("epsilon_decay"),
        "epsilon_min": params.get("epsilon_min"),
        "approx": params.get("approx"),
        "hidden_size": params.get("hidden_size"),
        "l2": params.get("l2"),
        "normalize_features": params.get("normalize_features"),
        "initial_temp": params.get("initial_temp"),
        "cooling_rate": params.get("cooling_rate"),
        "min_temp": params.get("min_temp"),
        "reheat_factor": params.get("reheat_factor"),
        "total_sailed": result.get("total_sailed") if result else None,
        "nb_tacks": result.get("nb_tacks") if result else None,
        "steps": result.get("steps") if result else None,
        "distance_to_mark": result.get("distance_to_mark") if result else None,
        "elapsed_time": result.get("elapsed_time") if result else None,
        "worker_elapsed_time": result.get("elapsed_time") if result else None,
        "orchestrator_overhead_time": None,
        "effective_elapsed_time": result.get("elapsed_time") if result else None,
        "finished": result.get("finished", False) if result else False,
        "success": result.get("success", False) if result else False,
    }
    return row


def finalize_result_row_timing(row, orchestrator_overhead):
    try:
        worker_elapsed = float(row.get("worker_elapsed_time"))
    except (TypeError, ValueError):
        worker_elapsed = None
    if worker_elapsed is None:
        effective_elapsed = orchestrator_overhead
    else:
        effective_elapsed = worker_elapsed + orchestrator_overhead
    row["orchestrator_overhead_time"] = orchestrator_overhead
    row["effective_elapsed_time"] = effective_elapsed
    row["elapsed_time"] = effective_elapsed
    return effective_elapsed


def _build_value_cost_model(results):
    """Build a simple per-value cost model from finished historical runs (lower is better)."""
    sums = {}
    counts = {}
    algo_global_sum = {}
    algo_global_count = {}
    for r in results:
        algo = r.get("algorithm")
        if not algo or not r.get("finished", False):
            continue
        sailed = r.get("total_sailed")
        if sailed is None:
            continue
        try:
            cost = float(sailed)
        except (TypeError, ValueError):
            continue
        algo_global_sum[algo] = algo_global_sum.get(algo, 0.0) + cost
        algo_global_count[algo] = algo_global_count.get(algo, 0) + 1
        for p in algo_param_list(algo):
            key = (algo, p, r.get(p))
            sums[key] = sums.get(key, 0.0) + cost
            counts[key] = counts.get(key, 0) + 1
    means = {k: sums[k] / counts[k] for k in sums}
    algo_means = {
        algo: (algo_global_sum[algo] / algo_global_count[algo])
        for algo in algo_global_sum
        if algo_global_count.get(algo, 0) > 0
    }
    return means, algo_means


def _param_is_numeric(name, param_ranges=None):
    ranges = param_ranges if param_ranges is not None else PARAM_RANGES
    vals = ranges.get(name, [])
    if not vals:
        return False
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)


def _estimate_case_cost(
    algo,
    params,
    value_means,
    algo_means,
    metric="additive-mean",
    idx_maps=None,
    knn_k=3,
    param_ranges=None,
):
    parts = []
    m = (metric or "additive-mean").strip().lower()
    algo_fallback = algo_means.get(algo, float("inf"))
    idx_maps = idx_maps or {}
    ranges = param_ranges if param_ranges is not None else PARAM_RANGES

    if m in {"additive-mean", "additive-median"}:
        for p in algo_param_list(algo):
            key = (algo, p, params.get(p))
            v = value_means.get(key)
            if v is not None:
                parts.append(v)
        if not parts:
            return algo_fallback
        if m == "additive-median":
            s = sorted(parts)
            n = len(s)
            mid = n // 2
            if n % 2 == 1:
                return s[mid]
            return 0.5 * (s[mid - 1] + s[mid])
        return sum(parts) / len(parts)

    if m == "partial-match":
        for p in algo_param_list(algo):
            v0 = params.get(p)
            # Numeric params: exact + immediate neighbors in param index space.
            if _param_is_numeric(p, ranges) and p in idx_maps:
                vals = ranges[p]
                i0 = idx_maps[p].get(v0)
                if i0 is None:
                    continue
                local = []
                for j in (i0 - 1, i0, i0 + 1):
                    if 0 <= j < len(vals):
                        key = (algo, p, vals[j])
                        vv = value_means.get(key)
                        if vv is not None:
                            local.append(vv)
                if local:
                    parts.append(sum(local) / len(local))
            else:
                key = (algo, p, v0)
                vv = value_means.get(key)
                if vv is not None:
                    parts.append(vv)
        if not parts:
            return algo_fallback
        return sum(parts) / len(parts)

    if m == "knn":
        k = max(1, int(knn_k))
        for p in algo_param_list(algo):
            v0 = params.get(p)
            # For categoricals/bools, exact-match only.
            if not _param_is_numeric(p, ranges):
                key = (algo, p, v0)
                vv = value_means.get(key)
                if vv is not None:
                    parts.append(vv)
                continue

            vals = [v for v in ranges.get(p, []) if (algo, p, v) in value_means]
            if not vals:
                continue
            vmin = min(vals)
            vmax = max(vals)
            span = (vmax - vmin) if (vmax - vmin) != 0 else 1.0
            ranked = []
            for v in vals:
                d = abs(float(v) - float(v0)) / span
                ranked.append((d, value_means[(algo, p, v)]))
            ranked.sort(key=lambda x: x[0])
            top = ranked[:k]
            wsum = 0.0
            ssum = 0.0
            for d, vv in top:
                w = 1.0 / (d + 1e-9)
                wsum += w
                ssum += w * vv
            if wsum > 0:
                parts.append(ssum / wsum)
        if not parts:
            return algo_fallback
        return sum(parts) / len(parts)

    # Unknown metric fallback.
    return algo_fallback


def _is_sparse_point(algo, params, step, idx_maps, param_ranges=None):
    """Return True if params lie on a sparse grid for this algo."""
    ranges = param_ranges if param_ranges is not None else PARAM_RANGES
    if step <= 1:
        return True
    for p in algo_param_list(algo):
        if p not in ranges:
            continue
        p_map = idx_maps.get(p, {})
        val = params.get(p)
        if val not in p_map:
            continue
        idx = p_map[val]
        last = len(ranges[p]) - 1
        if idx not in (0, last) and (idx % step) != 0:
            return False
    return True


def allocate_proportional_quotas(counts_by_key, total_slots, order=None):
    total_slots = max(0, int(total_slots))
    if total_slots <= 0 or not counts_by_key:
        return {key: 0 for key in counts_by_key}

    positive_keys = [key for key, count in counts_by_key.items() if count > 0]
    if not positive_keys:
        return {key: 0 for key in counts_by_key}

    if order is None:
        order = list(positive_keys)
    else:
        order = [key for key in order if key in counts_by_key and counts_by_key[key] > 0]
        seen = set(order)
        order.extend(key for key in positive_keys if key not in seen)

    total_count = sum(counts_by_key[key] for key in positive_keys)
    quotas = {key: 0 for key in counts_by_key}
    fractions = []
    used = 0
    for key in order:
        count = counts_by_key[key]
        raw = total_slots * (count / total_count)
        q = min(count, int(raw))
        quotas[key] = q
        used += q
        fractions.append((raw - int(raw), key))

    remaining = total_slots - used
    fractions.sort(reverse=True)
    while remaining > 0:
        placed = False
        for _, key in fractions:
            if quotas[key] < counts_by_key[key]:
                quotas[key] += 1
                remaining -= 1
                placed = True
                if remaining <= 0:
                    break
        if not placed:
            break
    return quotas


def build_coverage_context(test_cases, algo_order):
    pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order}
    covered = {(algo, pair): set() for algo in pairs_by_algo for pair in pairs_by_algo[algo]}
    case_pairs = {}
    for algo, params, tid in test_cases:
        pairs = {}
        for pair in pairs_by_algo.get(algo, []):
            pairs[pair] = (params.get(pair[0]), params.get(pair[1]))
        case_pairs[tid] = pairs
    return pairs_by_algo, covered, case_pairs


def score_case_coverage(algo, tid, pairs_by_algo, case_pairs, covered):
    score = 0
    for pair in pairs_by_algo.get(algo, []):
        combo = case_pairs[tid].get(pair)
        if combo is not None and combo not in covered[(algo, pair)]:
            score += 1
    return score


def mark_case_coverage(algo, tid, pairs_by_algo, case_pairs, covered):
    for pair in pairs_by_algo.get(algo, []):
        combo = case_pairs[tid].get(pair)
        if combo is not None:
            covered[(algo, pair)].add(combo)


def build_local_coverage_view(algo, pairs_by_algo, local_covered):
    return {(algo, pair): local_covered[pair] for pair in pairs_by_algo.get(algo, [])}


def build_space_search_plan(
    test_cases,
    results,
    coarse_step=4,
    refine_step=2,
    eta=3,
    early_stop_delta=0.0,
    metric="additive-mean",
    param_ranges=None,
):
    """
    Build deterministic 3-phase plan: coarse -> refine1 -> refine2.
    Uses historical finished results as a lightweight value model for ranking.
    """
    eta = max(2, int(eta))
    coarse_step = max(1, int(coarse_step))
    refine_step = max(1, int(refine_step))
    early_stop_delta = max(0.0, float(early_stop_delta))

    effective_ranges = param_ranges if param_ranges is not None else PARAM_RANGES
    idx_maps = {p: {v: i for i, v in enumerate(vals)} for p, vals in effective_ranges.items()}
    value_means, algo_means = _build_value_cost_model(results)

    by_algo = {}
    for tc in test_cases:
        by_algo.setdefault(tc[0], []).append(tc)
    for algo in by_algo:
        by_algo[algo].sort(key=lambda x: make_test_key(x[0], x[1]))

    phase_coarse = []
    phase_refine1 = []
    phase_refine2 = []
    per_algo_counts = {}

    for algo in sorted(by_algo):
        cases = by_algo[algo]
        coarse = [tc for tc in cases if _is_sparse_point(algo, tc[1], coarse_step, idx_maps, effective_ranges)]
        coarse_keys = {make_test_key(tc[0], tc[1]) for tc in coarse}
        remaining = [tc for tc in cases if make_test_key(tc[0], tc[1]) not in coarse_keys]

        # Favor finer sparse points for refine pool, then rank by estimated cost.
        refine_pool = [tc for tc in remaining if _is_sparse_point(algo, tc[1], refine_step, idx_maps, effective_ranges)]
        refine_pool.sort(
            key=lambda tc: (
                _estimate_case_cost(
                    tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps, param_ranges=effective_ranges
                ),
                make_test_key(tc[0], tc[1]),
            )
        )

        n1 = max(0, len(refine_pool) // eta)
        refine1 = refine_pool[:n1]
        refine1_keys = {make_test_key(tc[0], tc[1]) for tc in refine1}

        remaining_after_refine1 = [tc for tc in remaining if make_test_key(tc[0], tc[1]) not in refine1_keys]
        remaining_after_refine1.sort(
            key=lambda tc: (
                _estimate_case_cost(
                    tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps, param_ranges=effective_ranges
                ),
                make_test_key(tc[0], tc[1]),
            )
        )

        best_coarse = float("inf")
        if coarse:
            best_coarse = min(
                _estimate_case_cost(
                    tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps, param_ranges=effective_ranges
                )
                for tc in coarse
            )
        best_refine1 = float("inf")
        if refine1:
            best_refine1 = min(
                _estimate_case_cost(
                    tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps, param_ranges=effective_ranges
                )
                for tc in refine1
            )

        keep_refine2 = True
        if early_stop_delta > 0.0 and best_coarse < float("inf") and best_refine1 < float("inf"):
            denom = abs(best_coarse) if abs(best_coarse) > 1e-9 else 1.0
            improvement = (best_coarse - best_refine1) / denom
            if improvement < early_stop_delta:
                keep_refine2 = False

        n2 = max(0, len(remaining_after_refine1) // eta) if keep_refine2 else 0
        refine2 = remaining_after_refine1[:n2]

        phase_coarse.extend(coarse)
        phase_refine1.extend(refine1)
        phase_refine2.extend(refine2)
        per_algo_counts[algo] = (len(coarse), len(refine1), len(refine2), len(cases))

    plan = {
        "coarse": phase_coarse,
        "refine1": phase_refine1,
        "refine2": phase_refine2,
        "per_algo_counts": per_algo_counts,
    }
    return plan


def build_topk_search_plan(
    test_cases,
    results,
    metric="additive-mean",
    explore_ratio=0.05,
    eta=3,
    seed=42,
    show_progress=True,
    param_ranges=None,
):
    """
    Build a top-k plan from historical score estimates.
    Keep about 1/eta of remaining cases, with per-algo quotas proportional
    to remaining tests and exploit/explore split inside each algo.
    """
    total = len(test_cases)
    if total == 0:
        return {
            "selected": [],
            "selected_total": 0,
            "exploit_count": 0,
            "explore_count": 0,
            "candidate_total": 0,
            "per_algo_quota": {},
            "per_algo_selected": {},
            "per_algo_exploit": {},
            "per_algo_explore": {},
            "per_algo_candidates": {},
        }

    eta = max(2, int(eta))
    explore_ratio = max(0.0, min(1.0, float(explore_ratio)))
    exploit_ratio = 1.0 - explore_ratio

    effective_ranges = param_ranges if param_ranges is not None else PARAM_RANGES
    idx_maps = {p: {v: i for i, v in enumerate(vals)} for p, vals in effective_ranges.items()}
    value_means, algo_means = _build_value_cost_model(results)

    k_total = max(1, total // eta)
    by_algo = {}
    for tc in test_cases:
        by_algo.setdefault(tc[0], []).append(tc)
    algo_order = [a for a in DEFAULT_ALGO_ORDER if a in by_algo]
    algo_order.extend(sorted(set(by_algo) - set(algo_order)))
    per_algo_candidates = {a: len(by_algo.get(a, [])) for a in algo_order}

    # Quotas proportional to remaining tests per algo.
    quota = allocate_proportional_quotas(per_algo_candidates, k_total, order=algo_order)

    # Score each algo locally, then take exploit/explore within each algo quota.
    rng = random.Random(int(seed))
    selected = []
    selected_keys = set()
    per_algo_selected = {a: 0 for a in algo_order}
    per_algo_exploit = {a: 0 for a in algo_order}
    per_algo_explore = {a: 0 for a in algo_order}
    total_exploit = 0
    total_explore = 0
    for a in algo_order:
        cases = by_algo.get(a, [])
        if not cases or quota[a] <= 0:
            continue
        scored = []
        for tc in cases:
            _, params, _ = tc
            s = _estimate_case_cost(
                a, params, value_means, algo_means, metric=metric, idx_maps=idx_maps, param_ranges=effective_ranges
            )
            scored.append((s, make_test_key(a, params), tc))
        scored.sort(key=lambda x: (x[0], x[1]))

        q = quota[a]
        q_exploit = min(q, int(round(q * exploit_ratio)))
        q_explore = q - q_exploit

        for _, key, tc in scored[:q_exploit]:
            if key in selected_keys:
                continue
            selected.append(tc)
            selected_keys.add(key)
            per_algo_selected[a] += 1
            per_algo_exploit[a] += 1
            total_exploit += 1

        pool = [x for x in scored[q_exploit:] if x[1] not in selected_keys]
        if q_explore > 0 and pool:
            if q_explore >= len(pool):
                picks = pool
            else:
                idxs = rng.sample(range(len(pool)), q_explore)
                picks = [pool[i] for i in idxs]
            for _, key, tc in picks:
                if key in selected_keys:
                    continue
                selected.append(tc)
                selected_keys.add(key)
                per_algo_selected[a] += 1
                per_algo_explore[a] += 1
                total_explore += 1
    return {
        "selected": selected,
        "selected_total": len(selected),
        "exploit_count": total_exploit,
        "explore_count": total_explore,
        "candidate_total": total,
        "per_algo_quota": quota,
        "per_algo_selected": per_algo_selected,
        "per_algo_exploit": per_algo_exploit,
        "per_algo_explore": per_algo_explore,
        "per_algo_candidates": per_algo_candidates,
    }


def order_cases_quota_window_coverage(test_cases, algo_order, show_progress=True, label=None, verbose=0, window_size=500):
    step_start = time.perf_counter()
    progress_start = step_start
    by_algo = {}
    for algo, params, tid in test_cases:
        by_algo.setdefault(algo, []).append((algo, params, tid))
    if label:
        step1_time = time.perf_counter() - step_start
        print(f"  [{label}] step 1/4 group by algo ({step1_time:.2f}s)", flush=True)

    pairs_by_algo, covered, case_pairs = build_coverage_context(test_cases, [algo for algo in algo_order if algo in by_algo])

    total = sum(len(cases) for cases in by_algo.values())
    ordered = []
    last_pct = -1

    # Step 2: per-algo local coverage ordering (dynamic within algo only)
    ordered_by_algo = {}
    step2_start = time.perf_counter()
    for algo in algo_order:
        cases = list(by_algo.get(algo, []))
        if not cases:
            continue
        if label:
            print(f"  [{label}] step 2/4 order local coverage ({algo})", flush=True)
        algo_total = len(cases)
        algo_done = 0
        algo_last_pct = -1
        local_covered = {pair: set() for pair in pairs_by_algo.get(algo, [])}
        local_coverage_view = build_local_coverage_view(algo, pairs_by_algo, local_covered)
        algo_ordered = []
        while cases:
            best_idx = None
            best_score = -1
            for i, (_, params, tid) in enumerate(cases):
                score = score_case_coverage(
                    algo,
                    tid,
                    pairs_by_algo,
                    case_pairs,
                    local_coverage_view,
                )
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_idx is None:
                algo_ordered.extend(cases)
                break
            tc = cases.pop(best_idx)
            algo_ordered.append(tc)
            for pair in pairs_by_algo.get(algo, []):
                combo = case_pairs[tc[2]].get(pair)
                if combo is not None:
                    local_covered[pair].add(combo)
            algo_done += 1
            if label:
                pct = 100.0 * algo_done / algo_total if algo_total else 100.0
                if int(pct) != algo_last_pct and int(pct) % 10 == 0:
                    print(f"  [{label}]   {algo} local coverage {pct:.0f}%", flush=True)
                    algo_last_pct = int(pct)
        ordered_by_algo[algo] = algo_ordered
    if label:
        step2_time = time.perf_counter() - step2_start
        print(f"  [{label}] step 2/4 order local coverage ({step2_time:.2f}s)", flush=True)

    # Step 2: windowed quotas + per-window global coverage ordering
    window_size = max(1, int(window_size))
    remaining_counts = {algo: len(ordered_by_algo.get(algo, [])) for algo in algo_order}
    total_remaining = sum(remaining_counts.values())
    step3_start = time.perf_counter()
    if label:
        print(f"  [{label}] step 3/4 build windows W=500 + quotas", flush=True)
    window_count = 0
    total_windows = (total_remaining + window_size - 1) // window_size if window_size else 0
    while len(ordered) < total and total_remaining > 0:
        current_window = min(window_size, total_remaining)
        quotas = allocate_proportional_quotas(
            {algo: remaining_counts.get(algo, 0) for algo in algo_order},
            current_window,
            order=algo_order,
        )

        window_items = []
        for algo in algo_order:
            q = quotas.get(algo, 0)
            if q <= 0:
                continue
            lst = ordered_by_algo.get(algo, [])
            take = min(q, len(lst))
            window_items.extend(lst[:take])
            ordered_by_algo[algo] = lst[take:]
            remaining_counts[algo] -= take

        # Order window by global coverage gain
        scored = []
        for idx, (algo, params, tid) in enumerate(window_items):
            score = score_case_coverage(algo, tid, pairs_by_algo, case_pairs, covered)
            scored.append((score, idx, (algo, params, tid)))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for score, _, tc in scored:
            ordered.append(tc)
            algo = tc[0]
            mark_case_coverage(algo, tc[2], pairs_by_algo, case_pairs, covered)

            if show_progress:
                pct = 100.0 * len(ordered) / total if total else 100.0
                elapsed = time.perf_counter() - progress_start
                last_pct = maybe_print_progress(
                    "coverage order",
                    pct,
                    last_pct,
                    suffix=f" {elapsed:.1f}s",
                    step=5,
                    width=20,
                )
            if len(ordered) >= total:
                break

        total_remaining = sum(remaining_counts.values())
        window_count += 1
        if label and total_windows:
            pct = 100.0 * window_count / total_windows
            if int(pct) % 10 == 0:
                print(f"  [{label}] window ordering {pct:.0f}%", flush=True)
    if label:
        step3_time = time.perf_counter() - step3_start
        print(f"  [{label}] step 4/4 order windows by global coverage ({step3_time:.2f}s)", flush=True)

    if total and show_progress:
        elapsed = time.perf_counter() - progress_start
        print(render_progress_line("coverage order", 100.0, suffix=f" {elapsed:.1f}s", width=20), end="", flush=True)
        print()
        counts, max_gaps, max_runs, min_share, gain, uniq, param_run = compute_chunk_metrics(
            ordered, algo_order, pairs_by_algo
        )
        parts = []
        for algo in algo_order:
            parts.append(
                format_metric_parts(
                    algo,
                    max_gaps[algo],
                    min_share[algo],
                    max_runs[algo],
                    gain[algo],
                    uniq[algo],
                    param_run.get(algo, (0, "")),
                )
            )
        if verbose > 0:
            print("  global distribution: " + " | ".join(parts), flush=True)
    return ordered


def order_cases_coverage_global(test_cases, algo_order, show_progress=True, label=None):
    by_algo = {}
    for algo, params, tid in test_cases:
        by_algo.setdefault(algo, []).append((algo, params, tid))

    pairs_by_algo, covered, case_pairs = build_coverage_context(test_cases, [algo for algo in algo_order if algo in by_algo])

    total = sum(len(cases) for cases in by_algo.values())
    ordered = []
    last_pct = -1
    progress_start = time.perf_counter()
    label_start = time.perf_counter() if label else None
    label_next_pct = 10

    # Lazy-greedy heaps per algo.
    heaps = {}
    selected = {algo: set() for algo in algo_order}
    saturated = set()
    for algo in algo_order:
        cases = by_algo.get(algo, [])
        if not cases:
            continue
        heap = []
        for idx, (_, _, tid) in enumerate(cases):
            heapq.heappush(heap, (-score_case_coverage(algo, tid, pairs_by_algo, case_pairs, covered), idx, tid))
        heaps[algo] = heap

    while len(ordered) < total:
        progress = False
        for algo in algo_order:
            if algo in saturated:
                continue
            heap = heaps.get(algo)
            if not heap:
                continue
            while heap:
                neg_score, idx, tid = heapq.heappop(heap)
                if tid in selected[algo]:
                    continue
                current_score = score_case_coverage(algo, tid, pairs_by_algo, case_pairs, covered)
                if current_score <= 0:
                    saturated.add(algo)
                    break
                if -neg_score == current_score:
                    tc = by_algo[algo][idx]
                    ordered.append(tc)
                    selected[algo].add(tid)
                    mark_case_coverage(algo, tid, pairs_by_algo, case_pairs, covered)
                    progress = True
                    if show_progress:
                        pct = 100.0 * len(ordered) / total if total else 100.0
                        elapsed = time.perf_counter() - progress_start
                        last_pct = maybe_print_progress(
                            "coverage order",
                            pct,
                            last_pct,
                            suffix=f" {elapsed:.1f}s",
                            step=5,
                            width=20,
                        )
                    elif label:
                        pct = 100.0 * len(ordered) / total if total else 100.0
                        if pct >= label_next_pct or pct >= 100.0:
                            elapsed = time.perf_counter() - label_start if label_start else 0.0
                            print(f"  [{label}] global coverage progress {pct:.0f}% ({elapsed:.1f}s)", flush=True)
                            while label_next_pct <= pct:
                                label_next_pct += 10
                    break
                heapq.heappush(heap, (-current_score, idx, tid))
            if len(ordered) >= total:
                break
        if not progress:
            # Coverage saturated: append remaining in algo order.
            for algo in algo_order:
                cases = by_algo.get(algo, [])
                if not cases:
                    continue
                for idx, tc in enumerate(cases):
                    if tc[2] not in selected[algo]:
                        ordered.append(tc)
                by_algo[algo] = []
            break

    if total and show_progress:
        elapsed = time.perf_counter() - progress_start
        print(render_progress_line("coverage order", 100.0, suffix=f" {elapsed:.1f}s", width=20), end="", flush=True)
        print()
    return ordered


def order_cases_quota_window_coverage_worker(chunk, algo_order, worker_id=None, window_size=500):
    # Per-chunk regrouping by algo, local greedy coverage per algo, then windowed merge by head gain.
    buckets = {algo: [] for algo in algo_order}
    for tc in chunk:
        buckets.setdefault(tc[0], []).append(tc)

    for algo in algo_order:
        algo_cases = buckets.get(algo, [])
        if algo_cases:
            buckets[algo] = order_cases_coverage_global(algo_cases, [algo], show_progress=False)

    all_bucket_cases = []
    for algo in algo_order:
        all_bucket_cases.extend(buckets.get(algo, []))
    pairs_by_algo, covered, case_pairs = build_coverage_context(all_bucket_cases, algo_order)

    indices = {algo: 0 for algo in algo_order}
    total_remaining = sum(len(buckets.get(algo, [])) for algo in algo_order)
    window_size = max(1, int(window_size))
    rebuilt = []
    while total_remaining > 0:
        current_window = min(window_size, total_remaining)
        quotas = allocate_proportional_quotas(
            {
                algo: len(buckets.get(algo, [])) - indices.get(algo, 0)
                for algo in algo_order
            },
            current_window,
            order=algo_order,
        )

        window = []
        used_any = True
        while len(window) < current_window and used_any:
            used_any = False
            best_algo = None
            best_gain = -1
            best_tc = None
            for algo in algo_order:
                if quotas.get(algo, 0) <= 0:
                    continue
                lst = buckets.get(algo, [])
                idx = indices.get(algo, 0)
                if idx >= len(lst):
                    continue
                tc = lst[idx]
                gain = score_case_coverage(algo, tc[2], pairs_by_algo, case_pairs, covered)
                if gain > best_gain:
                    best_gain = gain
                    best_algo = algo
                    best_tc = tc
            if best_algo is not None:
                indices[best_algo] = indices.get(best_algo, 0) + 1
                quotas[best_algo] -= 1
                window.append(best_tc)
                mark_case_coverage(best_algo, best_tc[2], pairs_by_algo, case_pairs, covered)
                used_any = True

        if len(window) < current_window:
            for algo in algo_order:
                lst = buckets.get(algo, [])
                idx = indices.get(algo, 0)
                while idx < len(lst) and len(window) < current_window:
                    tc = lst[idx]
                    idx += 1
                    indices[algo] = idx
                    window.append(tc)
                    mark_case_coverage(algo, tc[2], pairs_by_algo, case_pairs, covered)
        rebuilt.extend(window)
        total_remaining = sum(
            len(buckets.get(algo, [])) - indices.get(algo, 0) for algo in algo_order
        )

    return worker_id, rebuilt


def compute_chunk_metrics(chunk_ordered, algo_order, pairs_by_algo):
    total = len(chunk_ordered)
    counts = {algo: 0 for algo in algo_order}
    for algo, _, _ in chunk_ordered:
        if algo in counts:
            counts[algo] += 1

    max_runs = {algo: 0 for algo in algo_order}
    run = 0
    prev = None
    for algo, _, _ in chunk_ordered:
        if algo == prev:
            run += 1
        else:
            run = 1
            prev = algo
        if algo in max_runs and run > max_runs[algo]:
            max_runs[algo] = run

    max_gaps = {algo: 0 for algo in algo_order}
    gap = {algo: 0 for algo in algo_order}
    for algo, _, _ in chunk_ordered:
        for a in algo_order:
            if a == algo:
                max_gaps[a] = max(max_gaps[a], gap[a])
                gap[a] = 0
            else:
                gap[a] += 1
    for a in algo_order:
        max_gaps[a] = max(max_gaps[a], gap[a])

    min_share = {
        algo: (counts[algo] / total if total else 0.0) for algo in algo_order
    }
    coverage_gain = {algo: 0.0 for algo in algo_order}
    unique_ratio = {algo: 0.0 for algo in algo_order}
    param_run = {}
    for algo in algo_order:
        pairs = pairs_by_algo.get(algo, [])
        if not pairs or counts[algo] <= 0:
            param_run[algo] = (0, "")
            continue
        unique_total = 0
        combos_by_pair = {pair: set() for pair in pairs}
        for a, params, _ in chunk_ordered:
            if a != algo:
                continue
            for pair in pairs:
                combos_by_pair[pair].add((params.get(pair[0]), params.get(pair[1])))
        for pair in pairs:
            unique_total += len(combos_by_pair[pair])
        coverage_gain[algo] = unique_total / max(1, counts[algo])
        unique_ratio[algo] = unique_total / max(1, counts[algo] * len(pairs))
        # Max run per parameter within this algo's sequence
        params_list = algo_param_list(algo)
        algo_tests = [params for a, params, _ in chunk_ordered if a == algo]
        best_run = 0
        best_param = ""
        for param in params_list:
            run = 0
            prev = object()
            max_run = 0
            for params in algo_tests:
                val = params.get(param)
                if val == prev:
                    run += 1
                else:
                    run = 1
                    prev = val
                if run > max_run:
                    max_run = run
            if max_run > best_run:
                best_run = max_run
                best_param = param
        param_run[algo] = (best_run, best_param)
    return counts, max_gaps, max_runs, min_share, coverage_gain, unique_ratio, param_run


def format_metric_parts(algo, max_gap, min_share, max_run, cov_gain, uniq, param_run):
    label = algo_label(algo)
    run_val, run_param = param_run
    pr = f"{run_val}({run_param})" if run_param else f"{run_val}"
    return (
        f"{label}: g{max_gap} s{min_share*100:.1f}% r{max_run} "
        f"cg{cov_gain:.2f} uq{uniq:.2f} pr{pr}"
    )


def order_cases_quota_window_coverage_chunked(test_cases, algo_order, workers, verbose=0, window_size=500):
    shuffled = list(test_cases)
    if workers <= 1:
        return order_cases_quota_window_coverage(
            shuffled, algo_order, show_progress=True, verbose=verbose, window_size=window_size
        )

    pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order}
    random.shuffle(shuffled)
    shuffle_global_done = True
    # Announce early before heavy metric computations.
    print(f"Ordering {len(shuffled)} cases with stratified {workers} chunks (workers={workers})...")
    if shuffle_global_done:
        print_completed_progress("shuffle global")
    if verbose > 0:
        global_counts, global_max_gaps, global_max_runs, global_min_share, global_gain, global_unique_ratio, global_param_run = compute_chunk_metrics(
            shuffled, algo_order, pairs_by_algo
        )
    chunks = [[] for _ in range(workers)]
    for idx, case in enumerate(shuffled):
        chunks[idx % workers].append(case)
    shuffle_by_algo_done = False
    # Create a tiny warmup chunk to advance progress quickly.
    warmup_chunk = []
    for chunk in chunks:
        if chunk:
            warmup_chunk.append(chunk.pop(0))
    chunks = [chunk for chunk in chunks if chunk]
    chunk_size = max(1, (len(shuffled) + max(1, len(chunks)) - 1) // max(1, len(chunks)))
    ordered = []
    if verbose > 0:
        print(f"  chunk_size {chunk_size}, chunks {len(chunks)}")
        if shuffle_global_done:
            parts = []
            for algo in algo_order:
                if algo in global_counts:
                    parts.append(
                        format_metric_parts(
                            algo,
                            global_max_gaps[algo],
                            global_min_share[algo],
                            global_max_runs[algo],
                            global_gain[algo],
                            global_unique_ratio[algo],
                            global_param_run.get(algo, (0, "")),
                        )
                    )
            if parts:
                print(f"  global distribution: " + " | ".join(parts))
    print_completed_progress("chunk dispatch")
    # Pre-coverage metrics (verbose only)
    if verbose > 0:
        pre_counts = {}
        pre_max_gaps = {}
        pre_max_runs = {}
        pre_min_share = {}
        pre_gain = {}
        pre_unique_ratio = {}
        pre_param_run = {}
        for idx, chunk in enumerate(chunks):
            counts, max_gaps, max_runs, min_share, gain, uniq, param_run = compute_chunk_metrics(
                chunk, algo_order, pairs_by_algo
            )
            pre_counts[idx + 1] = counts
            pre_max_gaps[idx + 1] = max_gaps
            pre_max_runs[idx + 1] = max_runs
            pre_min_share[idx + 1] = min_share
            pre_gain[idx + 1] = gain
            pre_unique_ratio[idx + 1] = uniq
            pre_param_run[idx + 1] = param_run
        for idx in sorted(pre_counts):
            parts = []
            for algo in algo_order:
                parts.append(
                    format_metric_parts(
                        algo,
                        pre_max_gaps[idx][algo],
                        pre_min_share[idx][algo],
                        pre_max_runs[idx][algo],
                        pre_gain[idx][algo],
                        pre_unique_ratio[idx][algo],
                        pre_param_run[idx].get(algo, (0, "")),
                    )
                )
            print(f"  pre-coverage chunk W{idx}: " + " | ".join(parts))

    done_chunks = 0
    window_start = time.perf_counter()
    # Run warmup in the main process to advance progress quickly.
    chunk_metrics = {} if verbose > 0 else None
    if warmup_chunk:
        warmup_ordered = order_cases_quota_window_coverage(
            warmup_chunk, algo_order, show_progress=False, verbose=0, window_size=window_size
        )
        ordered.extend(warmup_ordered)
        if verbose > 0:
            chunk_metrics[0] = compute_chunk_metrics(warmup_ordered, algo_order, pairs_by_algo)
        done_chunks += 1
        total_chunks = len(chunks) + 1
        pct = 100.0 * done_chunks / max(1, total_chunks)
        elapsed = time.perf_counter() - window_start
        print(
            render_count_progress_line(
                "window-based coverage chunks + warmup",
                pct,
                done_chunks,
                total_chunks,
                suffix=f" {elapsed:.1f}s",
                width=20,
            ),
            end="",
            flush=True,
        )

    total_chunks = len(chunks) + (1 if warmup_chunk else 0)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(order_cases_quota_window_coverage_worker, chunk, algo_order, idx + 1, window_size)
            for idx, chunk in enumerate(chunks)
        ]
        for future in as_completed(futures):
            worker_id, chunk_ordered = future.result()
            ordered.extend(chunk_ordered)
            if verbose > 0:
                chunk_metrics[worker_id] = compute_chunk_metrics(chunk_ordered, algo_order, pairs_by_algo)
            done_chunks += 1
            pct = 100.0 * done_chunks / max(1, total_chunks)
            elapsed = time.perf_counter() - window_start
            print(
                render_count_progress_line(
                    "window-based coverage chunks + warmup",
                    pct,
                    done_chunks,
                    total_chunks,
                    suffix=f" {elapsed:.1f}s",
                    width=20,
                ),
                end="",
                flush=True,
            )
    if total_chunks:
        print()
    if verbose > 0 and chunk_metrics:
        for worker_id in sorted(chunk_metrics):
            counts, max_gaps, max_runs, min_share, gain, uniq, param_run = chunk_metrics[worker_id]
            parts = []
            for algo in algo_order:
                parts.append(
                    format_metric_parts(
                        algo,
                        max_gaps[algo],
                        min_share[algo],
                        max_runs[algo],
                        gain[algo],
                        uniq[algo],
                        param_run.get(algo, (0, "")),
                    )
                )
            wid = "warmup" if worker_id == 0 else f"W{worker_id}"
            print(f"  post-window chunk {wid}: " + " | ".join(parts))
    return ordered


TEST_KEY_COMPONENTS = [
    ("horizon", "h"),
    ("tackangle", "ta"),
    ("alpha", "a"),
    ("beam_width", "bw"),
    ("scenarios", "sc"),
    ("dir_noise", "dn"),
    ("speed_noise", "sn"),
    ("gamma", "g"),
    ("lr", "lr"),
    ("goal_penalty", "gp"),
    ("epsilon", "e"),
    ("epsilon_decay", "ed"),
    ("epsilon_min", "emin"),
    ("approx", "ap"),
    ("hidden_size", "hs"),
    ("l2", "l2"),
    ("normalize_features", "nf"),
    ("initial_temp", "it"),
    ("cooling_rate", "cr"),
    ("min_temp", "mt"),
    ("reheat_factor", "rf"),
]


def extract_test_key_params(mapping):
    return {field: mapping.get(field) for field, _ in TEST_KEY_COMPONENTS}


def make_test_key(algo_name, params):
    """Create a unique key for a test case."""
    key = algo_name
    for field, prefix in TEST_KEY_COMPONENTS:
        key += f"|{prefix}{params.get(field, 'None')}"
    return key


def make_test_key_from_result_row(row):
    return make_test_key(row["algorithm"], extract_test_key_params(row))


def filter_completed_chunk(chunk, completed_keys):
    remaining = []
    for algo, params, tid in chunk:
        key = make_test_key(algo, params)
        if key not in completed_keys:
            remaining.append((algo, params, tid))
    return remaining


def format_progress_bar(pct, width=20):
    filled = int((pct / 100.0) * width)
    return "█" * filled + "░" * (width - filled)


def render_progress_line(label, pct, suffix="", width=20):
    bar = format_progress_bar(pct, width=width)
    return f"\r  {label} [{bar}] {pct:3.0f}%{suffix}"


def render_count_progress_line(label, pct, current, total, suffix="", width=20):
    bar = format_progress_bar(pct, width=width)
    return f"\r  {label} [{bar}] {current}/{total} ({pct:.0f}%){suffix}"


def maybe_print_progress(label, pct, last_pct, suffix="", step=5, width=20):
    pct_int = int(pct)
    if pct_int != last_pct and pct_int % step == 0:
        print(render_progress_line(label, pct, suffix=suffix, width=width), end="", flush=True)
        return pct_int
    return last_pct


def print_completed_progress(label, width=20, suffix="   ", flush=True):
    print(f"  {label} [{format_progress_bar(100.0, width=width)}] 100%{suffix}", flush=flush)


def load_existing_results(json_path):
    """Load existing results from JSON file for resume."""
    if not os.path.exists(json_path):
        return [], set()

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        results = data.get("results", [])

        # Build set of completed test keys
        completed_keys = set()
        for r in results:
            key = make_test_key_from_result_row(r)
            completed_keys.add(key)

        return results, completed_keys
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Could not load existing results: {e}")
        return [], set()


def count_by_algorithm(results):
    """Count completed tests per algorithm."""
    counts = {algo: 0 for algo in DEFAULT_ALGO_ORDER}
    for r in results:
        algo = r["algorithm"]
        if algo in counts:
            counts[algo] += 1
    return counts


def print_progress_summary(results, algo_order, algo_totals, title="ÉTAT D'AVANCEMENT DES TESTS"):
    """Affiche un résumé de l'avancement par algorithme avec barre de progression."""
    counts = count_by_algorithm(results)
    total_done = sum(counts.get(algo, 0) for algo in algo_order)
    total_all = sum(algo_totals.get(algo, counts.get(algo, 0)) for algo in algo_order)

    print("\n" + "=" * 70)
    print(f"{title}")
    print("=" * 70)

    for algo in algo_order:
        done = counts.get(algo, 0)
        total = algo_totals.get(algo, done)
        pct = 100.0 * done / total if total > 0 else 0
        bar = format_progress_bar(pct, width=20)
        status = "✓ COMPLET" if done >= total else ""
        print(f"  {algo:18} [{bar}] {done:6}/{total:6} ({pct:5.1f}%) {status}")

    print("-" * 70)
    total_pct = 100.0 * total_done / total_all if total_all > 0 else 0
    bar = format_progress_bar(total_pct, width=20)
    print(f"  {'TOTAL':18} [{bar}] {total_done:6}/{total_all:6} ({total_pct:5.1f}%)")
    print("=" * 70 + "\n")


def _format_duration(seconds):
    if seconds is None or seconds <= 0:
        return "n/a"
    if seconds > 3600:
        return f"{seconds/3600:.1f}h"
    if seconds > 60:
        return f"{seconds/60:.1f}min"
    return f"{seconds:.0f}s"


def _format_signed_duration(seconds):
    if seconds is None:
        return "n/a"
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{_format_duration(abs(seconds))}"


def _percentile(values, p):
    if not values:
        return None
    vs = sorted(values)
    idx = int(p * (len(vs) - 1))
    return vs[idx]


def init_eta_tracker(algo_order, window=DEFAULT_WINDOW_SIZE):
    alpha = 2.0 / (window + 1.0)
    tracker = {}
    for algo in algo_order:
        tracker[algo] = {
            "alpha": alpha,
            "ewma_spt": None,  # seconds per test
            "samples": deque(maxlen=window),
        }
    return tracker


def _eta_window_from_tracker(tracker):
    if not tracker:
        return max(1, DEFAULT_WINDOW_SIZE // 2)
    for entry in tracker.values():
        a = entry.get("alpha")
        if a and a > 0:
            w = int(round((2.0 / a) - 1.0))
            return max(1, w)
    return max(1, DEFAULT_WINDOW_SIZE // 2)


def _blend_eta(eta_ewma, eta_wall, run_done, w_eta):
    """Blend ETA with fixed weights: 0.65*EWMA + 0.35*wall."""
    phase = "steady-state"
    w_ewma, w_wall = 0.65, 0.35
    if eta_ewma is None:
        return eta_wall, phase, w_ewma, w_wall
    if eta_wall is None:
        return eta_ewma, phase, w_ewma, w_wall
    return (w_ewma * eta_ewma) + (w_wall * eta_wall), phase, w_ewma, w_wall


def update_eta_tracker(tracker, algo, elapsed_time):
    if not tracker or algo not in tracker:
        return
    try:
        t = float(elapsed_time)
    except (TypeError, ValueError):
        return
    if t <= 0:
        return
    entry = tracker[algo]
    if entry["ewma_spt"] is None:
        entry["ewma_spt"] = t
    else:
        a = entry["alpha"]
        entry["ewma_spt"] = (1.0 - a) * entry["ewma_spt"] + a * t
    entry["samples"].append(t)


def eta_snapshot(tracker, counts, algo_order, fallback_rate=0.0, workers=1, totals=None):
    if fallback_rate and fallback_rate > 0:
        fallback_spt = 1.0 / fallback_rate
    else:
        fallback_spt = None

    eta = 0.0
    eta_p50 = 0.0
    eta_p90 = 0.0
    has_any = False
    totals_map = totals if totals is not None else compute_algo_totals(PARAM_RANGES)
    for algo in algo_order:
        done = counts.get(algo, 0)
        total = totals_map.get(algo, done)
        remaining = max(0, total - done)
        if remaining <= 0:
            continue
        entry = tracker.get(algo, {}) if tracker else {}
        ewma_spt = entry.get("ewma_spt")
        samples = list(entry.get("samples", [])) if entry else []
        p50_spt = _percentile(samples, 0.50)
        p90_spt = _percentile(samples, 0.90)
        if ewma_spt is None:
            ewma_spt = fallback_spt
        if p50_spt is None:
            p50_spt = ewma_spt
        if p90_spt is None:
            p90_spt = ewma_spt
        if ewma_spt is None:
            continue
        eta += remaining * ewma_spt
        eta_p50 += remaining * p50_spt
        eta_p90 += remaining * p90_spt
        has_any = True
    if not has_any:
        return None, None, None
    w = max(1, int(workers))
    return eta / w, eta_p50 / w, eta_p90 / w


def print_progress_line(
    results,
    elapsed_time,
    rate,
    algo_order,
    algo_totals,
    coverage_gain=None,
    eta_tracker=None,
    workers=1,
    run_done=None,
    run_total=None,
    run_counts=None,
    run_totals=None,
):
    if getattr(print_progress_line, "_suspend", False):
        return
    """Affiche une ligne compacte de progression mise à jour à chaque test."""
    counts = count_by_algorithm(results)
    total_done = sum(counts.get(algo, 0) for algo in algo_order)
    total_all = sum(algo_totals.get(algo, counts.get(algo, 0)) for algo in algo_order)
    total_pct = 100.0 * total_done / total_all if total_all > 0 else 0

    # ETA via EWMA per algo + wallclock warmup/blend.
    eta_ewma, eta_p50_ewma, eta_p90_ewma = eta_snapshot(
        eta_tracker, counts, algo_order, fallback_rate=rate, workers=workers
    )
    run_done_i = max(0, int(run_done)) if run_done is not None else 0
    run_total_i = max(1, int(run_total)) if run_total is not None and int(run_total) > 0 else 0
    w_eta = _eta_window_from_tracker(eta_tracker)

    wall_rate = (run_done_i / elapsed_time) if (elapsed_time and elapsed_time > 0 and run_done_i > 0) else None
    global_remaining = max(0, total_all - total_done)
    eta_wall = (global_remaining / wall_rate) if wall_rate else None
    eta, eta_phase, w_ewma, w_wall = _blend_eta(eta_ewma, eta_wall, run_done_i, w_eta)

    eta_p50, _, _, _ = _blend_eta(eta_p50_ewma, eta_wall, run_done_i, w_eta)
    eta_p90, _, _, _ = _blend_eta(eta_p90_ewma, eta_wall, run_done_i, w_eta)

    if eta is None:
        remaining = total_all - total_done
        eta = remaining / rate if rate > 0 else 0
        eta_str = _format_duration(eta)
    else:
        eta_str = f"{_format_duration(eta)} (p50:{_format_duration(eta_p50)} p90:{_format_duration(eta_p90)})"

    # Barres compactes (plus courtes pour limiter le wrapping terminal).
    bar_width = 20
    bar_filled = max(0, min(bar_width, int((total_pct / 100.0) * bar_width)))
    bar = "█" * bar_filled + "░" * (bar_width - bar_filled)

    # Affichage par algo compact
    parts = []
    for algo in algo_order:
        label = algo_label(algo)
        total = algo_totals.get(algo, counts.get(algo, 0))
        parts.append(f"{label}:{counts.get(algo, 0)}/{total}")
    algo_status = " | ".join(parts)

    run_status = ""
    run_eta = None
    run_eta_ewma = None
    run_eta_wall = None
    run_phase = None
    run_w_ewma = None
    run_w_wall = None
    if run_done is not None and run_total is not None and run_total > 0:
        run_pct = 100.0 * run_done_i / run_total_i
        run_filled = max(0, min(bar_width, int((run_pct / 100.0) * bar_width)))
        run_bar = "█" * run_filled + "░" * (bar_width - run_filled)
        run_eta_ewma, _, _ = eta_snapshot(
            eta_tracker,
            run_counts or {},
            algo_order,
            fallback_rate=rate,
            workers=workers,
            totals=run_totals,
        )
        run_remaining = max(0, run_total_i - run_done_i)
        run_eta_wall = (run_remaining / wall_rate) if wall_rate else None
        run_eta, run_phase, run_w_ewma, run_w_wall = _blend_eta(run_eta_ewma, run_eta_wall, run_done_i, w_eta)
        if run_eta is None:
            run_eta = (run_remaining / rate) if rate > 0 else 0

        run_status = (
            f"[{run_bar}] {run_pct:5.1f}% | "
            f"run {run_done_i}/{run_total_i} ETA:{_format_duration(run_eta)}"
        )

    line1 = f"[{bar}] {total_pct:5.1f}% | {algo_status}"
    all_status = f"all {total_done}/{total_all}"
    if run_status:
        line2 = f"{run_status} | {all_status} ETA: {eta_str}"
    else:
        line2 = f"{all_status} ETA: {eta_str}"
    cols = shutil.get_terminal_size(fallback=(120, 24)).columns
    if cols > 8:
        if len(line1) >= cols:
            line1 = line1[: cols - 4] + "..."
        if len(line2) >= cols:
            line2 = line2[: cols - 4] + "..."
    # Cursor is on line2 (no trailing newline). Go up 1 to line1, clear both, rewrite.
    if getattr(print_progress_line, "_has_printed", False):
        print(f"\r\x1b[1A\r\x1b[2K", end="", flush=True)
    else:
        print(f"\r\x1b[2K", end="", flush=True)
    print(f"{line1}\r\n\x1b[2K{line2}", end="", flush=True)
    print_progress_line._has_printed = True
    return {
        "global_eta": eta,
        "global_eta_ewma": eta_ewma,
        "global_eta_wall": eta_wall,
        "global_phase": eta_phase,
        "global_w_ewma": w_ewma,
        "global_w_wall": w_wall,
        "run_eta": run_eta if run_status else None,
        "run_eta_ewma": run_eta_ewma if run_status else None,
        "run_eta_wall": run_eta_wall if run_status else None,
        "run_phase": run_phase if run_status else None,
        "run_w_ewma": run_w_ewma if run_status else None,
        "run_w_wall": run_w_wall if run_status else None,
    }


def init_coverage_tracker(algo_order):
    tracker = {}
    for algo in algo_order:
        pairs = algo_param_pairs(algo)
        tracker[algo] = {
            "pairs": pairs,
            "seen": {pair: set() for pair in pairs},
            "total_new": 0,
            "count": 0,
        }
    return tracker


def update_coverage_tracker(tracker, algo, params):
    if not tracker or algo not in tracker:
        return
    entry = tracker[algo]
    pairs = entry["pairs"]
    seen = entry["seen"]
    new_count = 0
    for pair in pairs:
        combo = (params.get(pair[0]), params.get(pair[1]))
        if combo not in seen[pair]:
            seen[pair].add(combo)
            new_count += 1
    entry["total_new"] += new_count
    entry["count"] += 1


def coverage_gain_snapshot(tracker, algo_order):
    gains = {}
    if not tracker:
        return gains
    for algo in algo_order:
        entry = tracker.get(algo)
        if not entry or entry["count"] == 0:
            gains[algo] = 0.0
        else:
            gains[algo] = entry["total_new"] / entry["count"]
    return gains


def save_results(results, csv_path, json_path, start_time, total_tests, effective_ranges, interrupted=False):
    """Save results to CSV and JSON files."""
    # CSV output
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)

    # JSON output (with metadata)
    output_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "total_tests": total_tests,
            "completed_tests": len(results),
            "total_time_seconds": time.time() - start_time,
            "fixed_params": dict(FIXED_PARAMS),
            "param_ranges": {key: list(values) for key, values in effective_ranges.items()},
            "interrupted": interrupted,
        },
        "results": results
    }
    with open(json_path, "w") as f:
        json.dump(output_data, f, indent=2)


def order_cases_by_mode(test_cases, args):
    """Apply the configured --order to a list of test cases."""
    if args.order == "shuffle":
        print(f"Ordering {len(test_cases)} cases...")
        random.shuffle(test_cases)
        print_completed_progress("shuffle global")
        return test_cases

    if args.order == "quota-window-coverage":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in {tc[0] for tc in test_cases}]
        if args.workers > 1 and len(test_cases) > args.workers:
            test_cases = order_cases_quota_window_coverage_chunked(
                test_cases, algo_order, args.workers, verbose=args.verbose, window_size=args.window_size
            )
            print("Test cases ordered by: quota-window-coverage (chunked)")
        else:
            print(f"Ordering {len(test_cases)} cases...")
            test_cases = order_cases_quota_window_coverage(
                test_cases, algo_order, show_progress=True, verbose=args.verbose, window_size=args.window_size
            )
            print("Test cases ordered by: quota-window-coverage")
        return test_cases

    if args.order == "global-coverage":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in {tc[0] for tc in test_cases}]
        algo_order.extend(sorted({tc[0] for tc in test_cases} - set(algo_order)))
        print(f"Ordering {len(test_cases)} cases...")
        test_cases = order_cases_coverage_global(test_cases, algo_order, show_progress=True)
        if args.verbose > 0:
            pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order}
            counts, max_gaps, max_runs, min_share, gain, uniq, param_run = compute_chunk_metrics(
                test_cases, algo_order, pairs_by_algo
            )
            parts = []
            for algo in algo_order:
                parts.append(
                    format_metric_parts(
                        algo,
                        max_gaps[algo],
                        min_share[algo],
                        max_runs[algo],
                        gain[algo],
                        uniq[algo],
                        param_run.get(algo, (0, "")),
                    )
                )
            print("  global distribution: " + " | ".join(parts), flush=True)
        print("Test cases ordered by: global-coverage")
        return test_cases

    order_list = [item.strip() for item in args.order.split(",") if item.strip()]
    order_set = set(order_list)
    unknown = order_set - VALID_ALGOS
    if unknown:
        raise ValueError(f"Unknown algo(s) in --order: {', '.join(sorted(unknown))}")
    print(f"Ordering {len(test_cases)} cases...")
    ordered = []
    total_order = len(test_cases)
    done_order = 0
    last_pct = -1
    for algo in order_list:
        chunk = [tc for tc in test_cases if tc[0] == algo]
        ordered.extend(chunk)
        done_order += len(chunk)
        pct = 100.0 * done_order / total_order if total_order else 100.0
        if int(pct) != last_pct and int(pct) % 5 == 0:
            print(render_progress_line("order by algo", pct, width=20), end="", flush=True)
            last_pct = int(pct)
    tail = [tc for tc in test_cases if tc[0] not in order_set]
    ordered.extend(tail)
    if total_order:
        print(render_progress_line("order by algo", 100.0, suffix="   ", width=20), end="", flush=True)
        print()
    print(f"Test cases ordered by: {', '.join(order_list)}")
    return ordered


def execute_batch(
    test_cases,
    args,
    results,
    completed_keys,
    total_tests_original,
    csv_path,
    json_path,
    interrupted_state,
    phase_label=None,
    all_results=None,
    all_completed_keys=None,
    save_results_ref=None,
    eta_history=None,
    run_start_time=None,
    algo_totals=None,
    effective_ranges=None,
):
    """Execute one batch of ordered test cases."""
    if not test_cases:
        return {"initial_run_eta_s": None, "batch_elapsed_s": 0.0}
    if all_results is None:
        all_results = results
    if all_completed_keys is None:
        all_completed_keys = completed_keys
    if save_results_ref is None:
        save_results_ref = all_results
    if algo_totals is None:
        algo_totals = compute_algo_totals(PARAM_RANGES)
    if effective_ranges is None:
        effective_ranges = PARAM_RANGES

    present_algos = {tc[0] for tc in test_cases}
    if args.order in {"shuffle", "quota-window-coverage", "global-coverage"}:
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))
    else:
        order_list = [item.strip() for item in args.order.split(",") if item.strip()]
        algo_order = [algo for algo in order_list if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))

    total_remaining = len(test_cases)
    run_totals_by_algo = {}
    for algo, _, _ in test_cases:
        run_totals_by_algo[algo] = run_totals_by_algo.get(algo, 0) + 1

    print(f"Running {total_remaining} test cases with {args.workers} workers...")
    print(
        f"Total tests in benchmark: {total_tests_original}, "
        f"already completed: {len(completed_keys)}, remaining: {total_remaining}"
    )
    print(f"Algorithms: {', '.join(algo_order)}")
    print(f"Metric: {args.metric}")
    print(f"Results will be saved every {args.save_interval} tests")
    print("Press Ctrl+C to interrupt and save progress\n")

    completed_this_run = 0
    start_time = time.time()
    results_lock = Lock()
    last_save_count = 0
    coverage_tracker = None
    eta_tracker = init_eta_tracker(algo_order, window=max(1, args.window_size // 2))
    run_done_by_algo = {algo: 0 for algo in algo_order}
    last_eta_display_value = None

    for r in results:
        update_eta_tracker(
            eta_tracker,
            r.get("algorithm"),
            r.get("effective_elapsed_time", r.get("elapsed_time")),
        )
    initial_run_eta_s, _, _ = eta_snapshot(
        eta_tracker,
        {algo: 0 for algo in algo_order},
        algo_order,
        fallback_rate=0.0,
        workers=args.workers,
        totals=run_totals_by_algo,
    )
    if eta_history is not None and initial_run_eta_s is not None:
        if run_start_time is not None:
            initial_elapsed = max(0.0, time.time() - run_start_time)
        else:
            initial_elapsed = 0.0
        eta_history.append((initial_elapsed, initial_run_eta_s, initial_run_eta_s, None, "steady-state", 0.65, 0.35))
        last_eta_display_value = _format_duration(initial_run_eta_s)
    if args.order in {"quota-window-coverage", "global-coverage"}:
        coverage_tracker = init_coverage_tracker(algo_order)
        for r in results:
            update_coverage_tracker(coverage_tracker, r["algorithm"], r)

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker_ignore_sigint) as executor:
        futures = {executor.submit(run_single_test, tc): tc for tc in test_cases}
        pending = set(futures.keys())

        while pending and not interrupted_state["value"]:
            done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for future in done:
                if interrupted_state["value"]:
                    break
                try:
                    algo_name, params, result, test_id = future.result()
                except Exception as e:
                    print(f"Error in worker future: {e}")
                    continue

                orchestrator_start = time.time()
                completed_this_run += 1
                run_done_by_algo[algo_name] = run_done_by_algo.get(algo_name, 0) + 1
                elapsed = time.time() - start_time
                rate = completed_this_run / elapsed if elapsed > 0 else 0

                row = build_result_row(algo_name, params, result)

                with results_lock:
                    results.append(row)
                    completed_keys.add(make_test_key(algo_name, params))
                    if all_results is not results:
                        all_results.append(row)
                    if all_completed_keys is not completed_keys:
                        all_completed_keys.add(make_test_key(algo_name, params))
                    orchestrator_overhead = max(0.0, time.time() - orchestrator_start)
                    effective_elapsed = finalize_result_row_timing(row, orchestrator_overhead)

                    update_eta_tracker(eta_tracker, row["algorithm"], row.get("effective_elapsed_time"))
                    if coverage_tracker is not None:
                        update_coverage_tracker(coverage_tracker, row["algorithm"], row)
                    if completed_this_run - last_save_count >= args.save_interval:
                        save_results(
                            save_results_ref,
                            csv_path,
                            json_path,
                            start_time,
                            total_tests_original,
                            effective_ranges,
                            interrupted=False,
                        )
                        last_save_count = completed_this_run

                    gains = coverage_gain_snapshot(coverage_tracker, algo_order)
                    eta_info = print_progress_line(
                        results,
                        elapsed,
                        rate,
                        algo_order,
                        algo_totals,
                        coverage_gain=gains,
                        eta_tracker=eta_tracker,
                        workers=args.workers,
                        run_done=completed_this_run,
                        run_total=total_remaining,
                        run_counts=run_done_by_algo,
                        run_totals=run_totals_by_algo,
                    )
                    current_eta = None
                    if isinstance(eta_info, dict):
                        current_eta = eta_info.get("run_eta")
                        if current_eta is None:
                            current_eta = eta_info.get("global_eta")
                    else:
                        current_eta = eta_info
                    if eta_history is not None and current_eta is not None:
                        eta_display_value = _format_duration(current_eta)
                        if eta_display_value != last_eta_display_value:
                            if run_start_time is not None:
                                eta_elapsed = max(0.0, time.time() - run_start_time)
                            else:
                                eta_elapsed = elapsed
                            eta_ewma = None
                            eta_wall = None
                            eta_phase = None
                            eta_w_ewma = None
                            eta_w_wall = None
                            if isinstance(eta_info, dict):
                                eta_ewma = eta_info.get("run_eta_ewma")
                                eta_wall = eta_info.get("run_eta_wall")
                                eta_phase = eta_info.get("run_phase")
                                eta_w_ewma = eta_info.get("run_w_ewma")
                                eta_w_wall = eta_info.get("run_w_wall")
                                if eta_ewma is None and eta_wall is None:
                                    eta_ewma = eta_info.get("global_eta_ewma")
                                    eta_wall = eta_info.get("global_eta_wall")
                                    eta_phase = eta_info.get("global_phase")
                                    eta_w_ewma = eta_info.get("global_w_ewma")
                                    eta_w_wall = eta_info.get("global_w_wall")
                            eta_history.append((eta_elapsed, current_eta, eta_ewma, eta_wall, eta_phase, eta_w_ewma, eta_w_wall))
                            last_eta_display_value = eta_display_value

        if interrupted_state["value"]:
            print()
            print("Interrupted! Saving progress...")
            for future in pending:
                future.cancel()

    # Leave progress bars visible, just move to next line
    print()
    return {
        "initial_run_eta_s": initial_run_eta_s,
        "batch_elapsed_s": time.time() - start_time,
    }


def build_eta_history_lines(history):
    pred_totals_local = []
    lines_local = []
    for i, (elapsed_s, eta_s, eta_ewma_s, eta_wall_s, _eta_phase, eta_w_ewma, eta_w_wall) in enumerate(history, start=1):
        eta_sum = (elapsed_s if elapsed_s is not None else 0.0) + (eta_s if eta_s is not None else 0.0)
        pred_totals_local.append(eta_sum)
        if eta_ewma_s is not None and eta_wall_s is not None:
            eta_expr = (
                f"{_format_duration(eta_s)}"
                f"({eta_w_ewma:.1f}*{_format_duration(eta_ewma_s)}+{eta_w_wall:.1f}*{_format_duration(eta_wall_s)})"
            )
        elif eta_ewma_s is not None:
            we = eta_w_ewma if eta_w_ewma is not None else 1.0
            ww = eta_w_wall if eta_w_wall is not None else 0.0
            eta_expr = f"{_format_duration(eta_s)}({we:.1f}*{_format_duration(eta_ewma_s)}+{ww:.1f}*n/a)"
        else:
            eta_expr = _format_duration(eta_s)
        lines_local.append(
            f"  {i:>4d}. {_format_duration(elapsed_s)} + {eta_expr} = {_format_duration(eta_sum)}"
        )
    return pred_totals_local, lines_local


def compute_eta_stats(pred_totals_local, target):
    if not pred_totals_local or target is None or target <= 0:
        return None
    errors = [p - target for p in pred_totals_local]
    abs_errors = [abs(e) for e in errors]
    rel_abs = [ae / target for ae in abs_errors]
    within10 = sum(1 for r in rel_abs if r <= 0.10)
    return {
        "bias_s": sum(errors) / len(errors),
        "mae_s": sum(abs_errors) / len(abs_errors),
        "mape": (sum(rel_abs) / len(rel_abs)) * 100.0,
        "hit10": (100.0 * within10 / len(rel_abs)),
    }


def find_stabilization_start(pred_totals_local, target, tolerance, window_size=20, inside_ratio=0.80, consecutive_windows=3):
    if not pred_totals_local or target is None or tolerance is None:
        return None
    n = len(pred_totals_local)
    if n == 0:
        return None
    k = min(window_size, n)
    need = max(1, int(inside_ratio * k))
    consec = 0
    for start in range(0, n - k + 1):
        window = pred_totals_local[start:start + k]
        inside = sum(1 for value in window if abs(value - target) <= tolerance)
        if inside >= need:
            consec += 1
            if consec >= consecutive_windows:
                return start
        else:
            consec = 0
    return None


def print_eta_history_compact(lines_local, pred_totals_local, target, stats):
    print("ETA history (elapsed + ETA (w_ewma*EWMA+w_wall*ETA_Wall)):")
    n = len(lines_local)
    if n <= 30:
        for line in lines_local:
            print(line)
        return
    first_n = 10
    middle_n = 10
    last_n = 10
    mid_start_1based = None
    if stats is not None and pred_totals_local:
        target_zone = target + stats["bias_s"]
        tol = max(1.0, stats["mae_s"])
        stable_idx = find_stabilization_start(pred_totals_local, target_zone, tol)
        if stable_idx is not None:
            mid_start_1based = stable_idx + 1
    if mid_start_1based is None:
        mid_start = max(first_n, (n - middle_n) // 2)
    else:
        mid_start = max(first_n, min(n - last_n - middle_n, mid_start_1based - 1))
    mid_end = min(n, mid_start + middle_n)
    if mid_end > n - last_n:
        mid_end = n - last_n
        mid_start = mid_end - middle_n
    sections = [
        (1, first_n),
        (mid_start + 1, mid_end),
        (n - last_n + 1, n),
    ]
    seen = set()
    for idx, (a, b) in enumerate(sections):
        if a > b:
            continue
        key = (a, b)
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{a}-{b}]")
        for j in range(a - 1, b):
            print(lines_local[j])
        if idx < len(sections) - 1:
            print("  ...")


def compute_total_compute_time(rows):
    total = 0.0
    found = False
    for row in rows:
        try:
            value = float(row.get("effective_elapsed_time", row.get("elapsed_time")))
        except (TypeError, ValueError, AttributeError):
            continue
        total += value
        found = True
    return total if found else None


def format_eta_slope(slope):
    if slope is None:
        return "n/a"
    sign = "+" if slope >= 0 else "-"
    return f"{sign}{abs(slope):.1f}h/h"


def compute_eta_trend(history, pred_totals_local):
    if not history or not pred_totals_local:
        return None
    elapsed_values = [float(item[0] or 0.0) for item in history]
    first20 = pred_totals_local[:20]
    last20 = pred_totals_local[-20:]
    start = _percentile(first20, 0.5)
    end = _percentile(last20, 0.5)
    if start is None or start <= 0 or end is None or end <= 0:
        return None

    delta = end - start
    delta_pct = 100.0 * delta / start

    slope = None
    if len(last20) >= 2:
        last20_elapsed = elapsed_values[-len(last20):]
        mean_x = sum(last20_elapsed) / len(last20_elapsed)
        mean_y = sum(last20) / len(last20)
        denom = sum((x - mean_x) ** 2 for x in last20_elapsed)
        if denom > 0:
            slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(last20_elapsed, last20)) / denom

    last20_errors = [abs(p - end) for p in last20]
    last20_mae = sum(last20_errors) / len(last20_errors) if last20_errors else None
    volatility = None
    if last20:
        deviations = [abs(p - end) for p in last20]
        mad = _percentile(deviations, 0.5)
        if mad is not None and end > 0:
            volatility = 100.0 * mad / end

    stabilized_after = None
    n = len(pred_totals_local)
    if last20_mae is not None and n >= 3:
        tol = max(last20_mae, 0.10 * end, 1.0)
        stable_idx = find_stabilization_start(pred_totals_local, end, tol)
        if stable_idx is not None:
            stabilized_after = elapsed_values[stable_idx]

    return {
        "start_s": start,
        "end_s": end,
        "delta_s": delta,
        "delta_pct": delta_pct,
        "slope_last20": slope,
        "volatility_last20": volatility,
        "stabilized_after_s": stabilized_after,
    }


def format_eta_trend(trend):
    if trend is None:
        return "ETA trend: n/a"
    volatility = trend.get("volatility_last20")
    volatility_s = f"{volatility:.1f}%" if volatility is not None else "n/a"
    return (
        f"ETA trend: start_first20={_format_duration(trend['start_s'])} "
        f"end_last20={_format_duration(trend['end_s'])} "
        f"delta={_format_signed_duration(trend['delta_s'])} ({trend['delta_pct']:+.1f}%) "
        f"slope_last20={format_eta_slope(trend.get('slope_last20'))} "
        f"volatility_last20={volatility_s} "
        f"stabilized_after={_format_duration(trend.get('stabilized_after_s'))}"
    )


def print_final_report(
    args,
    results,
    results_all,
    results_before_run,
    total_tests_original,
    benchmark_start,
    eta_history,
    first_initial_eta_s,
    interrupted_state,
    csv_path,
    json_path,
    algo_totals,
):
    summary_present_algos = {r.get("algorithm") for r in results if r.get("algorithm")}
    summary_algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in summary_present_algos]
    summary_algo_order.extend(sorted(summary_present_algos - set(summary_algo_order)))
    if not summary_algo_order:
        summary_algo_order = list(DEFAULT_ALGO_ORDER)
    print_progress_summary(results, summary_algo_order, algo_totals, "RÉSUMÉ FINAL")

    total_elapsed = time.time() - benchmark_start
    pred_totals = []
    history_lines = []
    if eta_history:
        pred_totals, history_lines = build_eta_history_lines(eta_history)
    eta_trend = compute_eta_trend(eta_history, pred_totals)
    run_rows = results[results_before_run:]
    run_compute_time = compute_total_compute_time(run_rows)
    cumulative_compute_time = compute_total_compute_time(results_all)
    had_previous_results = results_before_run > 0

    if interrupted_state["value"]:
        run_completed = len(results) - results_before_run
        print(f"\nBenchmark interrupted! ({run_completed} tests in this run)")
        print(f"Progress saved: {len(results)}/{total_tests_original} tests completed")
        print(f"Run with --resume to continue\n")
        last20_totals = pred_totals[-20:] if pred_totals else []
        estimated_elapsed = _percentile(last20_totals, 0.5) if last20_totals else None
        if args.verbose > 0 and history_lines:
            partial_stats_for_view = compute_eta_stats(last20_totals, estimated_elapsed)
            print_eta_history_compact(history_lines, pred_totals, estimated_elapsed, partial_stats_for_view)
        estimated_stats = compute_eta_stats(pred_totals, estimated_elapsed)
        if run_compute_time is not None:
            print(f"Aggregate multi-processor compute time: {_format_duration(run_compute_time)}")
        if args.resume and had_previous_results and cumulative_compute_time is not None:
            print(f"Cumulative aggregate multi-processor compute time: {_format_duration(cumulative_compute_time)}")
        print(format_eta_trend(eta_trend))
        if estimated_stats is not None:
            print(
                f"Estimated elapsed time: {_format_duration(estimated_elapsed)}"
                f" | bias:{_format_signed_duration(estimated_stats['bias_s'])}"
                f" mae:{_format_duration(estimated_stats['mae_s'])}"
                f" mape:{estimated_stats['mape']:.1f}%"
                f" hit10%:{estimated_stats['hit10']:.0f}%"
            )
        else:
            print(f"Estimated elapsed time: {_format_duration(estimated_elapsed)}")

        partial_stats = compute_eta_stats(last20_totals, estimated_elapsed)
        if partial_stats is not None and last20_totals:
            print(
                "Partial ETA diagnostics (interrupted, target=median last 20 predicted totals): "
                f"bias:{_format_signed_duration(partial_stats['bias_s'])} "
                f"mae:{_format_duration(partial_stats['mae_s'])} "
                f"mape:{partial_stats['mape']:.1f}% "
                f"hit10%:{partial_stats['hit10']:.0f}%"
            )
        else:
            print("Partial ETA diagnostics (interrupted, target=median last 20 predicted totals): n/a")
    else:
        run_completed = len(results) - results_before_run
        print(f"Benchmark complete! ({run_completed} tests in this run)")
        print()
        pred_stats = compute_eta_stats(pred_totals, total_elapsed)
        if args.verbose > 0 and history_lines:
            print_eta_history_compact(history_lines, pred_totals, total_elapsed, pred_stats)
        elif not eta_history:
            print(f"Initial ETA estimate: {_format_duration(first_initial_eta_s)}")
        if run_compute_time is not None:
            print(f"Aggregate multi-processor compute time: {_format_duration(run_compute_time)}")
        if args.resume and had_previous_results and cumulative_compute_time is not None:
            print(f"Cumulative aggregate multi-processor compute time: {_format_duration(cumulative_compute_time)}")
        print(format_eta_trend(eta_trend))
        if pred_stats is not None:
            print(
                f"Real elapsed time: {_format_duration(total_elapsed)}"
                f" | bias:{_format_signed_duration(pred_stats['bias_s'])}"
                f" mae:{_format_duration(pred_stats['mae_s'])}"
                f" mape:{pred_stats['mape']:.1f}%"
                f" hit10%:{pred_stats['hit10']:.0f}%"
            )
        else:
            print(f"Real elapsed time: {_format_duration(total_elapsed)}")

    print()
    print("Results saved to:")
    print(f"  - {csv_path}")
    print(f"  - {json_path}")

    successful = [r for r in results if r["success"]]
    finished_races = [r for r in results if r.get("finished", False)]
    print(f"\nSummary: {len(successful)}/{total_tests_original} tests ran, {len(finished_races)} finished the race")

    for algo in DEFAULT_ALGO_ORDER:
        algo_results = [r for r in finished_races if r["algorithm"] == algo]
        if algo_results:
            sailed = [r["total_sailed"] for r in algo_results if r["total_sailed"]]
            if sailed:
                print(f"\n{algo} ({len(algo_results)} finished):")
                print(f"  total_sailed: min={min(sailed):.1f}, max={max(sailed):.1f}, avg={sum(sailed)/len(sailed):.1f}")


def run_ordered_batch(
    test_cases,
    args,
    results,
    completed_keys,
    total_tests_original,
    csv_path,
    json_path,
    interrupted_state,
    all_results,
    all_completed_keys,
    eta_history,
    benchmark_start,
    algo_totals,
    effective_ranges,
    phase_label=None,
):
    ordered_cases = order_cases_by_mode(test_cases, args)
    if len(ordered_cases) == 0:
        print("All tests already completed!")
        return None
    return execute_batch(
        ordered_cases,
        args,
        results,
        completed_keys,
        total_tests_original,
        csv_path,
        json_path,
        interrupted_state,
        phase_label=phase_label,
        all_results=all_results,
        all_completed_keys=all_completed_keys,
        save_results_ref=all_results,
        eta_history=eta_history,
        run_start_time=benchmark_start,
        algo_totals=algo_totals,
        effective_ranges=effective_ranges,
    )


def run_selected_search_mode(
    all_test_cases,
    args,
    results,
    completed_keys,
    total_tests_original,
    csv_path,
    json_path,
    interrupted_state,
    results_all,
    completed_keys_all,
    eta_history,
    benchmark_start,
    algo_totals,
    effective_ranges,
):
    first_initial_eta_s = None

    if args.search_mode == "space-search":
        planned_total_input = len(all_test_cases)
        plan = build_space_search_plan(
            all_test_cases,
            results,
            coarse_step=args.space_coarse_step,
            refine_step=args.space_refine_step,
            eta=args.space_eta,
            early_stop_delta=args.space_early_stop_delta,
            metric=args.metric,
            param_ranges=effective_ranges,
        )
        phase_sizes = {
            "coarse": len(plan.get("coarse", [])),
            "refine1": len(plan.get("refine1", [])),
            "refine2": len(plan.get("refine2", [])),
        }
        selected_cases = list(plan.get("coarse", [])) + list(plan.get("refine1", [])) + list(plan.get("refine2", []))
        print(
            f"Space-search planning: coarse={phase_sizes['coarse']}, "
            f"refine1={phase_sizes['refine1']}, refine2={phase_sizes['refine2']} "
            f"(selected {len(selected_cases)}/{planned_total_input})"
        )
        if args.verbose > 0:
            for algo in sorted(plan.get("per_algo_counts", {})):
                c0, c1, c2, tot = plan["per_algo_counts"][algo]
                print(
                    f"  {algo}: coarse={c0}, refine1={c1}, refine2={c2}, "
                    f"selected={c0 + c1 + c2}/{tot}"
                )
        batch_stats = run_ordered_batch(
            selected_cases, args, results, completed_keys, total_tests_original, csv_path, json_path,
            interrupted_state, results_all, completed_keys_all, eta_history, benchmark_start, algo_totals, effective_ranges,
        )
        if batch_stats:
            first_initial_eta_s = batch_stats.get("initial_run_eta_s")
        return first_initial_eta_s

    if args.search_mode == "coarse-to-fine":
        remaining_cases = list(all_test_cases)
        initial_remaining = len(remaining_cases)
        print(f"Coarse-to-fine sequential run on {initial_remaining} remaining cases")
        for phase_name in ("coarse", "refine1", "refine2"):
            if interrupted_state["value"] or not remaining_cases:
                break

            phase_plan = build_space_search_plan(
                remaining_cases,
                results,
                coarse_step=args.space_coarse_step,
                refine_step=args.space_refine_step,
                eta=args.space_eta,
                early_stop_delta=args.space_early_stop_delta,
                metric=args.metric,
                param_ranges=effective_ranges,
            )
            phase_cases = list(phase_plan.get(phase_name, []))
            print(
                f"Space-search phase {phase_name}: selected {len(phase_cases)}/{len(remaining_cases)} "
                f"(coarse={len(phase_plan.get('coarse', []))}, "
                f"refine1={len(phase_plan.get('refine1', []))}, "
                f"refine2={len(phase_plan.get('refine2', []))})"
            )
            if not phase_cases:
                continue

            batch_stats = run_ordered_batch(
                phase_cases, args, results, completed_keys, total_tests_original, csv_path, json_path,
                interrupted_state, results_all, completed_keys_all, eta_history, benchmark_start,
                algo_totals, effective_ranges, phase_label=phase_name,
            )
            if first_initial_eta_s is None and batch_stats:
                first_initial_eta_s = batch_stats.get("initial_run_eta_s")
            remaining_cases = [
                tc for tc in remaining_cases
                if make_test_key(tc[0], tc[1]) not in completed_keys
            ]
        return first_initial_eta_s

    if args.search_mode == "topk-search":
        planned_total_input = len(all_test_cases)
        plan = build_topk_search_plan(
            all_test_cases,
            results,
            metric=args.metric,
            explore_ratio=args.topk_explore_ratio,
            eta=args.topk_eta,
            seed=args.topk_seed,
            param_ranges=effective_ranges,
        )
        selected_cases = list(plan.get("selected", []))
        print(
            f"Top-k planning: exploit={plan.get('exploit_count', 0)}, "
            f"explore={plan.get('explore_count', 0)} "
            f"(selected {plan.get('selected_total', 0)}/{planned_total_input})",
            flush=True,
        )
        print_completed_progress("top-k fusion")
        quota = plan.get("per_algo_quota", {})
        picked = plan.get("per_algo_selected", {})
        exp = plan.get("per_algo_exploit", {})
        rnd = plan.get("per_algo_explore", {})
        cand = plan.get("per_algo_candidates", {})
        for algo in sorted(quota):
            print(
                f"  {algo}: candidates={cand.get(algo, 0)}, "
                f"quota={quota.get(algo, 0)}, "
                f"selected={picked.get(algo, 0)}, "
                f"exploit={exp.get(algo, 0)}, "
                f"explore={rnd.get(algo, 0)}",
                flush=True,
            )
        batch_stats = run_ordered_batch(
            selected_cases, args, results, completed_keys, total_tests_original, csv_path, json_path,
            interrupted_state, results_all, completed_keys_all, eta_history, benchmark_start, algo_totals, effective_ranges,
        )
        if batch_stats:
            first_initial_eta_s = batch_stats.get("initial_run_eta_s")
        return first_initial_eta_s

    batch_stats = run_ordered_batch(
        all_test_cases, args, results, completed_keys, total_tests_original, csv_path, json_path,
        interrupted_state, results_all, completed_keys_all, eta_history, benchmark_start, algo_totals, effective_ranges,
    )
    if batch_stats:
        first_initial_eta_s = batch_stats.get("initial_run_eta_s")
    return first_initial_eta_s

def prepare_benchmark_state(args, json_path, algo_set, effective_ranges, algo_totals):
    results_all = []
    completed_keys_all = set()
    results = []
    completed_keys = set()
    if args.resume:
        results_all, completed_keys_all = load_existing_results(json_path)

    all_test_cases = generate_test_cases(args.verbose, param_ranges=effective_ranges, algo_totals=algo_totals)
    total_tests_original = len(all_test_cases)

    if algo_set is not None:
        all_test_cases = [tc for tc in all_test_cases if tc[0] in algo_set]

    if args.resume and completed_keys_all:
        active_completed_keys = set()
        for algo, params, _ in all_test_cases:
            k = make_test_key(algo, params)
            if k in completed_keys_all:
                active_completed_keys.add(k)
        results = [r for r in results_all if make_test_key_from_result_row(r) in active_completed_keys]
        completed_keys = active_completed_keys
        print(f"Resuming: found {len(completed_keys)} completed tests in active ranges")
        print_progress_summary(results, DEFAULT_ALGO_ORDER, algo_totals, "TESTS DÉJÀ EFFECTUÉS")
    elif args.resume:
        results = []
        completed_keys = set()
    else:
        results = []
        completed_keys = set()
        results_all = []
        completed_keys_all = set()

    if args.resume and completed_keys:
        print(f"Filtering completed tests from {len(all_test_cases)} cases...")
        if args.workers > 1 and len(all_test_cases) > args.workers:
            chunk_size = max(1, len(all_test_cases) // args.workers)
            chunks = [all_test_cases[i:i + chunk_size] for i in range(0, len(all_test_cases), chunk_size)]
            remaining_tests = []
            done_chunks = 0
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(filter_completed_chunk, chunk, completed_keys) for chunk in chunks]
                for future in as_completed(futures):
                    remaining_tests.extend(future.result())
                    done_chunks += 1
                    if done_chunks % max(1, len(chunks) // 10) == 0 or done_chunks == len(chunks):
                        pct = 100.0 * done_chunks / len(chunks)
                        print(
                            render_count_progress_line(
                                "filter progress",
                                pct,
                                done_chunks,
                                f"{len(chunks)} chunks",
                                width=20,
                            ),
                            end="",
                            flush=True,
                        )
        else:
            remaining_tests = []
            for algo, params, tid in all_test_cases:
                key = make_test_key(algo, params)
                if key not in completed_keys:
                    remaining_tests.append((algo, params, tid))
        skipped = len(all_test_cases) - len(remaining_tests)
        all_test_cases = remaining_tests
        if args.workers > 1 and len(all_test_cases) > args.workers:
            print()
        if args.verbose > 0:
            print(f"  skipping {skipped} already completed tests")
            remaining_counts = {}
            for algo, _, _ in all_test_cases:
                remaining_counts[algo] = remaining_counts.get(algo, 0) + 1
            if remaining_counts:
                for algo in sorted(remaining_counts):
                    print(f"  remaining {algo}: {remaining_counts[algo]}")
            if args.order not in {"shuffle", "quota-window-coverage"}:
                present_algos = {tc[0] for tc in all_test_cases}
                algo_order_local = [algo for algo in DEFAULT_ALGO_ORDER if algo in present_algos]
                algo_order_local.extend(sorted(present_algos - set(algo_order_local)))
                pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order_local}
                counts, max_gaps, max_runs, min_share, gain, uniq, param_run = compute_chunk_metrics(
                    all_test_cases, algo_order_local, pairs_by_algo
                )
                parts = []
                for algo in algo_order_local:
                    parts.append(
                        format_metric_parts(
                            algo,
                            max_gaps[algo],
                            min_share[algo],
                            max_runs[algo],
                            gain[algo],
                            uniq[algo],
                            param_run.get(algo, (0, "")),
                        )
                    )
                print("  global distribution: " + " | ".join(parts))

    return results_all, completed_keys_all, results, completed_keys, all_test_cases, total_tests_original


def build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Benchmark trajectory planning algorithms",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--output", default="benchmark_results.csv", help="Output CSV file")
    parser.add_argument("--json-output", default="benchmark_results.json", help="Output JSON file")
    parser.add_argument("--workers", type=int, default=12, help="Number of parallel workers")
    parser.add_argument("--algo", default="all",
                        help="Which algorithm(s) to benchmark (comma-separated or 'all')")
    parser.add_argument("--range", action="append", default=[],
                        help="Override a parameter range (repeatable): name=v1,v2 or name=min:max")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run (skip completed tests)")
    parser.add_argument("--order", default="quota-window-coverage",
                        help="Execution order: 'quota-window-coverage' (local greedy per algo; windowed merge with "
                             "per-algo quotas and head gain selection; stratified across chunks when using workers), "
                             "'global-coverage' (global greedy coverage ordering), "
                             "'shuffle' (random across algos/params), or comma-separated algo list "
                             "(sequential params per algo)")
    parser.add_argument("--save-interval", type=int, default=100, help="Save results every N completed tests")
    parser.add_argument("--verbose", type=int, default=0, help="Verbosity level (0=summary, 1=details)")
    parser.add_argument("--window-size", type=int, default=DEFAULT_WINDOW_SIZE,
                        help="Window size for quota-window-coverage; ETA uses W_eta=W/2 with EWMA alpha=2/(W_eta+1)")
    parser.add_argument("--search-mode", default="grid", choices=["grid", "space-search", "coarse-to-fine", "topk-search"],
                        help="Case generation mode: 'grid' runs all remaining cases; "
                             "'space-search' keeps a deterministic coarse/refine1/refine2 subset (one-shot); "
                             "'coarse-to-fine' runs sequential phases with replanning between phases; "
                             "'topk-search' keeps an estimated best subset with exploit/explore split")
    parser.add_argument("--space-coarse-step", type=int, default=4,
                        help="Sparse-grid step for space-search coarse phase")
    parser.add_argument("--space-refine-step", type=int, default=2,
                        help="Sparse-grid step for space-search refine pool")
    parser.add_argument("--space-eta", type=int, default=3,
                        help="Successive-halving factor for space-search (keep ~1/eta per refine phase)")
    parser.add_argument("--space-early-stop-delta", type=float, default=0.0,
                        help="Optional relative min improvement for refine2 activation per algo (fraction; 0.02=2%%)")
    parser.add_argument("--metric", default="additive-mean",
                        choices=["additive-mean", "additive-median", "partial-match", "knn"],
                        help="Scoring metric for space-search/coarse-to-fine candidate ranking")
    parser.add_argument("--topk-eta", type=int, default=3,
                        help="Top-k selection factor for topk-search (keep about 1/eta of remaining cases)")
    parser.add_argument("--topk-explore-ratio", type=float, default=0.05,
                        help="Top-k explore ratio (random from non-top candidates); exploit is 1 - explore")
    parser.add_argument("--topk-seed", type=int, default=42,
                        help="Random seed for topk-search exploration picks")
    return parser


def parse_and_validate_args():
    parser = build_arg_parser()
    args = parser.parse_args()
    valid_order_keywords = {"shuffle", "quota-window-coverage", "global-coverage"}
    algo_set = None
    if args.algo != "all":
        algo_list = [item.strip() for item in args.algo.split(",") if item.strip()]
        unknown_algos = [algo for algo in algo_list if algo not in VALID_ALGOS]
        if unknown_algos:
            parser.error(f"Unknown algo(s) in --algo: {', '.join(unknown_algos)}")
        algo_set = set(algo_list)
    if args.order not in valid_order_keywords:
        order_list = [item.strip() for item in args.order.split(",") if item.strip()]
        unknown_order_algos = [algo for algo in order_list if algo not in VALID_ALGOS]
        if unknown_order_algos:
            parser.error(f"Unknown algo(s) in --order: {', '.join(sorted(set(unknown_order_algos)))}")
    return parser, args, algo_set


def configure_effective_ranges(args, parser):
    try:
        effective_ranges = apply_range_overrides(BASE_PARAM_RANGES, args.range)
    except ValueError as e:
        parser.error(str(e))
    algo_totals = compute_algo_totals(effective_ranges)
    print("Effective parameter ranges:")
    for name, values in effective_ranges.items():
        print(f"  {name}: {_format_allowed_values(values)}")
    return effective_ranges, algo_totals


def resolve_output_paths(args):
    output_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(output_dir, args.output)
    json_path = os.path.join(output_dir, args.json_output)
    return csv_path, json_path


def main():
    parser, args, algo_set = parse_and_validate_args()
    effective_ranges, algo_totals = configure_effective_ranges(args, parser)
    csv_path, json_path = resolve_output_paths(args)

    if not args.resume and (os.path.exists(csv_path) or os.path.exists(json_path)):
        print("Existing benchmark results detected.")
        print(f"  - CSV: {csv_path if os.path.exists(csv_path) else 'not found'}")
        print(f"  - JSON: {json_path if os.path.exists(json_path) else 'not found'}")
        response = input("Type 'reset' to overwrite, or press Enter to cancel: ").strip().lower()
        if response != "reset":
            print("Cancelled. Re-run with --resume or type 'reset' to overwrite.")
            return

    results_all, completed_keys_all, results, completed_keys, all_test_cases, total_tests_original = prepare_benchmark_state(
        args=args,
        json_path=json_path,
        algo_set=algo_set,
        effective_ranges=effective_ranges,
        algo_totals=algo_totals,
    )

    interrupted_state = {"value": False}
    print_progress_line._suspend = False
    print_progress_line._has_printed = False
    results_before_run = len(results)
    benchmark_start = time.time()
    first_initial_eta_s = None
    eta_history = []

    def handle_interrupt(signum, frame):
        interrupted_state["value"] = True
        print_progress_line._suspend = True

    signal.signal(signal.SIGINT, handle_interrupt)

    try:
        first_initial_eta_s = run_selected_search_mode(
            all_test_cases=all_test_cases,
            args=args,
            results=results,
            completed_keys=completed_keys,
            total_tests_original=total_tests_original,
            csv_path=csv_path,
            json_path=json_path,
            interrupted_state=interrupted_state,
            results_all=results_all,
            completed_keys_all=completed_keys_all,
            eta_history=eta_history,
            benchmark_start=benchmark_start,
            algo_totals=algo_totals,
            effective_ranges=effective_ranges,
        )
    except ValueError as e:
        print(str(e))
        return
    except Exception as e:
        print(f"Error during benchmark: {e}")
        interrupted_state["value"] = True

    # Final save
    save_results(
        results_all,
        csv_path,
        json_path,
        benchmark_start,
        total_tests_original,
        effective_ranges,
        interrupted=interrupted_state["value"],
    )

    # Leave progress bars visible, just move to next line
    print()
    print_final_report(
        args=args,
        results=results,
        results_all=results_all,
        results_before_run=results_before_run,
        total_tests_original=total_tests_original,
        benchmark_start=benchmark_start,
        eta_history=eta_history,
        first_initial_eta_s=first_initial_eta_s,
        interrupted_state=interrupted_state,
        csv_path=csv_path,
        json_path=json_path,
        algo_totals=algo_totals,
    )


if __name__ == "__main__":
    main()
