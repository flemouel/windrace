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
    "horizon": [10, 20, 30, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400, 600, 800, 1000, 1200, 1500, 2000],
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
}
BASE_PARAM_RANGES = {k: list(v) for k, v in PARAM_RANGES.items()}

# Total tests per algorithm (derived from PARAM_RANGES)
def _range_len(name, ranges=None):
    src = ranges if ranges is not None else PARAM_RANGES
    return len(src.get(name, []))


def compute_algo_totals(param_ranges=None):
    src = param_ranges if param_ranges is not None else PARAM_RANGES
    return {
        "mpc_realmove": _range_len("horizon", src) * _range_len("alpha", src),
        "mpc_simplemove": _range_len("horizon", src) * _range_len("alpha", src),
        "beam_realmove": _range_len("horizon", src) * _range_len("alpha", src) * _range_len("beam_width", src),
        "adp_realmove": _range_len("horizon", src) * _range_len("alpha", src) * _range_len("gamma", src) * _range_len("lr", src)
        * _range_len("goal_penalty", src) * _range_len("epsilon", src) * _range_len("epsilon_decay", src) * _range_len("epsilon_min", src)
        * _range_len("approx", src) * _range_len("hidden_size", src) * _range_len("l2", src) * _range_len("normalize_features", src),
        "spst_realmove": _range_len("horizon", src) * _range_len("alpha", src) * _range_len("scenarios", src)
        * _range_len("dir_noise", src) * _range_len("speed_noise", src),
    }


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


ALGO_TOTALS = compute_algo_totals(PARAM_RANGES)

# Base directory (where the algorithm scripts are located)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Root directory (windgame)
ROOT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))


def run_algorithm(algo_name, params, timeout=300):
    """
    Run a single algorithm with given parameters.
    Returns dict with results or None on failure.
    """
    script_map = {
        "beam_realmove": "beam_realmove.py",
        "mpc_realmove": "mpc_realmove.py",
        "mpc_simplemove": "mpc_simplemove.py",
        "adp_realmove": "adp_realmove.py",
        "spst_realmove": "spst_realmove.py",
    }

    script_path = os.path.join(BASE_DIR, script_map[algo_name])
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
    # mpc_simplemove doesn't have near/far delay parameters

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
            return None

        # Parse output
        output = result.stdout
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

        # Check if race was completed (distance_to_mark <= goal)
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

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


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


def generate_test_cases(verbose=0):
    """Generate all test cases for grid search."""
    test_cases = []
    test_id = 0
    total_expected = sum(ALGO_TOTALS.values())
    print(f"Generating test cases (expected total: {total_expected})...")
    if total_expected <= 0:
        return test_cases

    counts = {}

    # mpc_realmove: 3 parameters (no beam_width) - FIRST
    last_pct = -1
    for horizon, alpha in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["alpha"]
    ):
        params = {
            "horizon": horizon,
            "tackangle": FIXED_PARAMS["tackangle"],
            "alpha": alpha,
            "beam_width": None
        }
        test_cases.append(("mpc_realmove", params, test_id))
        test_id += 1
        pct = 100.0 * test_id / total_expected
        if int(pct) != last_pct and int(pct) % 10 == 0:
            bar = format_progress_bar(pct, width=20)
            print(f"\r  generation [{bar}] {pct:3.0f}%", end="", flush=True)
            last_pct = int(pct)
    counts["mpc_realmove"] = test_id

    # mpc_simplemove: 3 parameters (no beam_width) - SECOND
    start_count = test_id
    for horizon, alpha in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["alpha"]
    ):
        params = {
            "horizon": horizon,
            "tackangle": FIXED_PARAMS["tackangle"],
            "alpha": alpha,
            "beam_width": None
        }
        test_cases.append(("mpc_simplemove", params, test_id))
        test_id += 1
        pct = 100.0 * test_id / total_expected
        if int(pct) != last_pct and int(pct) % 10 == 0:
            bar = format_progress_bar(pct, width=20)
            print(f"\r  generation [{bar}] {pct:3.0f}%", end="", flush=True)
            last_pct = int(pct)
    counts["mpc_simplemove"] = test_id - start_count

    # beam_realmove: all 4 parameters - LAST
    start_count = test_id
    for horizon, alpha, beam_width in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["alpha"],
        PARAM_RANGES["beam_width"]
    ):
        params = {
            "horizon": horizon,
            "tackangle": FIXED_PARAMS["tackangle"],
            "alpha": alpha,
            "beam_width": beam_width
        }
        test_cases.append(("beam_realmove", params, test_id))
        test_id += 1
        pct = 100.0 * test_id / total_expected
        if int(pct) != last_pct and int(pct) % 10 == 0:
            bar = format_progress_bar(pct, width=20)
            print(f"\r  generation [{bar}] {pct:3.0f}%", end="", flush=True)
            last_pct = int(pct)
    counts["beam_realmove"] = test_id - start_count

    # adp_realmove: horizon, alpha + ADP-specific parameters
    start_count = test_id
    for (
        horizon, alpha, gamma, lr, goal_penalty, epsilon, epsilon_decay,
        epsilon_min, approx, hidden_size, l2, normalize_features
    ) in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["alpha"],
        PARAM_RANGES["gamma"],
        PARAM_RANGES["lr"],
        PARAM_RANGES["goal_penalty"],
        PARAM_RANGES["epsilon"],
        PARAM_RANGES["epsilon_decay"],
        PARAM_RANGES["epsilon_min"],
        PARAM_RANGES["approx"],
        PARAM_RANGES["hidden_size"],
        PARAM_RANGES["l2"],
        PARAM_RANGES["normalize_features"],
    ):
        params = {
            "horizon": horizon,
            "tackangle": FIXED_PARAMS["tackangle"],
            "alpha": alpha,
            "beam_width": None,
            "gamma": gamma,
            "lr": lr,
            "goal_penalty": goal_penalty,
            "epsilon": epsilon,
            "epsilon_decay": epsilon_decay,
            "epsilon_min": epsilon_min,
            "approx": approx,
            "hidden_size": hidden_size,
            "l2": l2,
            "normalize_features": normalize_features,
        }
        test_cases.append(("adp_realmove", params, test_id))
        test_id += 1
        pct = 100.0 * test_id / total_expected
        if int(pct) != last_pct and int(pct) % 10 == 0:
            bar = format_progress_bar(pct, width=20)
            print(f"\r  generation [{bar}] {pct:3.0f}%", end="", flush=True)
            last_pct = int(pct)
    counts["adp_realmove"] = test_id - start_count

    # spst_realmove: horizon, alpha + stochastic parameters
    start_count = test_id
    for horizon, alpha, scenarios, dir_noise, speed_noise in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["alpha"],
        PARAM_RANGES["scenarios"],
        PARAM_RANGES["dir_noise"],
        PARAM_RANGES["speed_noise"],
    ):
        params = {
            "horizon": horizon,
            "tackangle": FIXED_PARAMS["tackangle"],
            "alpha": alpha,
            "beam_width": None,
            "scenarios": scenarios,
            "dir_noise": dir_noise,
            "speed_noise": speed_noise,
        }
        test_cases.append(("spst_realmove", params, test_id))
        test_id += 1
        pct = 100.0 * test_id / total_expected
        if int(pct) != last_pct and int(pct) % 10 == 0:
            bar = format_progress_bar(pct, width=20)
            print(f"\r  generation [{bar}] {pct:3.0f}%", end="", flush=True)
            last_pct = int(pct)
    counts["spst_realmove"] = test_id - start_count

    print(f"\r  generation [{format_progress_bar(100.0, width=20)}] 100%   ", end="", flush=True)
    print()
    if verbose > 0:
        for algo in ["mpc_realmove", "mpc_simplemove", "beam_realmove", "adp_realmove", "spst_realmove"]:
            if algo in counts:
                print(f"  {algo}: {counts[algo]}")
        print(f"  generated {len(test_cases)} test cases")

    return test_cases


def algo_param_pairs(algo_name):
    if algo_name in ("mpc_realmove", "mpc_simplemove"):
        return [("horizon", "alpha")]
    if algo_name == "beam_realmove":
        return [("horizon", "alpha"), ("horizon", "beam_width"), ("alpha", "beam_width")]
    if algo_name == "adp_realmove":
        params = [
            "horizon", "alpha", "gamma", "lr", "goal_penalty", "epsilon",
            "epsilon_decay", "epsilon_min", "approx", "hidden_size", "l2", "normalize_features"
        ]
        return [(params[i], params[j]) for i in range(len(params)) for j in range(i + 1, len(params))]
    if algo_name == "spst_realmove":
        params = ["horizon", "alpha", "scenarios", "dir_noise", "speed_noise"]
        return [(params[i], params[j]) for i in range(len(params)) for j in range(i + 1, len(params))]
    return []

def algo_param_list(algo_name):
    if algo_name in ("mpc_realmove", "mpc_simplemove"):
        return ["horizon", "alpha"]
    if algo_name == "beam_realmove":
        return ["horizon", "alpha", "beam_width"]
    if algo_name == "adp_realmove":
        return [
            "horizon", "alpha", "gamma", "lr", "goal_penalty", "epsilon",
            "epsilon_decay", "epsilon_min", "approx", "hidden_size", "l2", "normalize_features"
        ]
    if algo_name == "spst_realmove":
        return ["horizon", "alpha", "scenarios", "dir_noise", "speed_noise"]
    return []


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


def _param_is_numeric(name):
    vals = PARAM_RANGES.get(name, [])
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
):
    parts = []
    m = (metric or "additive-mean").strip().lower()
    algo_fallback = algo_means.get(algo, float("inf"))
    idx_maps = idx_maps or {}

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
            if _param_is_numeric(p) and p in idx_maps:
                vals = PARAM_RANGES[p]
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
            if not _param_is_numeric(p):
                key = (algo, p, v0)
                vv = value_means.get(key)
                if vv is not None:
                    parts.append(vv)
                continue

            vals = [v for v in PARAM_RANGES.get(p, []) if (algo, p, v) in value_means]
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


def _is_sparse_point(algo, params, step, idx_maps):
    """Return True if params lie on a sparse grid for this algo."""
    if step <= 1:
        return True
    for p in algo_param_list(algo):
        if p not in PARAM_RANGES:
            continue
        p_map = idx_maps.get(p, {})
        val = params.get(p)
        if val not in p_map:
            continue
        idx = p_map[val]
        last = len(PARAM_RANGES[p]) - 1
        if idx not in (0, last) and (idx % step) != 0:
            return False
    return True


def build_space_search_plan(
    test_cases,
    results,
    coarse_step=4,
    refine_step=2,
    eta=3,
    early_stop_delta=0.0,
    metric="additive-mean",
):
    """
    Build deterministic 3-phase plan: coarse -> refine1 -> refine2.
    Uses historical finished results as a lightweight value model for ranking.
    """
    eta = max(2, int(eta))
    coarse_step = max(1, int(coarse_step))
    refine_step = max(1, int(refine_step))
    early_stop_delta = max(0.0, float(early_stop_delta))

    idx_maps = {p: {v: i for i, v in enumerate(vals)} for p, vals in PARAM_RANGES.items()}
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
        coarse = [tc for tc in cases if _is_sparse_point(algo, tc[1], coarse_step, idx_maps)]
        coarse_keys = {make_test_key(tc[0], tc[1]) for tc in coarse}
        remaining = [tc for tc in cases if make_test_key(tc[0], tc[1]) not in coarse_keys]

        # Favor finer sparse points for refine pool, then rank by estimated cost.
        refine_pool = [tc for tc in remaining if _is_sparse_point(algo, tc[1], refine_step, idx_maps)]
        refine_pool.sort(
            key=lambda tc: (
                _estimate_case_cost(tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps),
                make_test_key(tc[0], tc[1]),
            )
        )

        n1 = max(0, len(refine_pool) // eta)
        refine1 = refine_pool[:n1]
        refine1_keys = {make_test_key(tc[0], tc[1]) for tc in refine1}

        remaining_after_refine1 = [tc for tc in remaining if make_test_key(tc[0], tc[1]) not in refine1_keys]
        remaining_after_refine1.sort(
            key=lambda tc: (
                _estimate_case_cost(tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps),
                make_test_key(tc[0], tc[1]),
            )
        )

        best_coarse = float("inf")
        if coarse:
            best_coarse = min(
                _estimate_case_cost(tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps)
                for tc in coarse
            )
        best_refine1 = float("inf")
        if refine1:
            best_refine1 = min(
                _estimate_case_cost(tc[0], tc[1], value_means, algo_means, metric=metric, idx_maps=idx_maps)
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

    idx_maps = {p: {v: i for i, v in enumerate(vals)} for p, vals in PARAM_RANGES.items()}
    value_means, algo_means = _build_value_cost_model(results)

    k_total = max(1, total // eta)
    by_algo = {}
    for tc in test_cases:
        by_algo.setdefault(tc[0], []).append(tc)
    algo_order = [a for a in DEFAULT_ALGO_ORDER if a in by_algo]
    algo_order.extend(sorted(set(by_algo) - set(algo_order)))
    per_algo_candidates = {a: len(by_algo.get(a, [])) for a in algo_order}

    # Quotas proportional to remaining tests per algo.
    quota = {a: 0 for a in algo_order}
    frac = []
    used = 0
    for a in algo_order:
        count = per_algo_candidates[a]
        raw = k_total * (count / total)
        q = min(count, int(raw))
        quota[a] = q
        used += q
        frac.append((raw - int(raw), a))
    rem = k_total - used
    frac.sort(reverse=True)
    while rem > 0:
        placed = False
        for _, a in frac:
            if quota[a] < per_algo_candidates[a]:
                quota[a] += 1
                rem -= 1
                placed = True
                if rem <= 0:
                    break
        if not placed:
            break

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
            s = _estimate_case_cost(a, params, value_means, algo_means, metric=metric, idx_maps=idx_maps)
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

    pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order if algo in by_algo}
    covered = {(algo, pair): set() for algo in pairs_by_algo for pair in pairs_by_algo[algo]}
    case_pairs = {}
    for algo, params, tid in test_cases:
        pairs = {}
        for pair in pairs_by_algo.get(algo, []):
            pairs[pair] = (params.get(pair[0]), params.get(pair[1]))
        case_pairs[tid] = pairs

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
        algo_ordered = []
        while cases:
            best_idx = None
            best_score = -1
            for i, (_, params, tid) in enumerate(cases):
                score = 0
                for p in pairs_by_algo.get(algo, []):
                    combo = case_pairs[tid].get(p)
                    if combo is not None and combo not in local_covered[p]:
                        score += 1
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_idx is None:
                algo_ordered.extend(cases)
                break
            tc = cases.pop(best_idx)
            algo_ordered.append(tc)
            for p in pairs_by_algo.get(algo, []):
                combo = case_pairs[tc[2]].get(p)
                if combo is not None:
                    local_covered[p].add(combo)
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
        quotas = {}
        fractions = []
        remaining_slots = current_window
        for algo in algo_order:
            count = remaining_counts.get(algo, 0)
            if count <= 0:
                continue
            raw = current_window * (count / total_remaining)
            q = int(raw)
            quotas[algo] = q
            remaining_slots -= q
            fractions.append((raw - q, algo))
        fractions.sort(reverse=True)
        for _ in range(remaining_slots):
            if not fractions:
                break
            placed = False
            for _, algo in fractions:
                if quotas.get(algo, 0) < remaining_counts.get(algo, 0):
                    quotas[algo] += 1
                    placed = True
                    break
            if not placed:
                break

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
            score = 0
            for p in pairs_by_algo.get(algo, []):
                combo = case_pairs[tid].get(p)
                if combo is not None and combo not in covered[(algo, p)]:
                    score += 1
            scored.append((score, idx, (algo, params, tid)))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for score, _, tc in scored:
            ordered.append(tc)
            algo = tc[0]
            for p in pairs_by_algo.get(algo, []):
                combo = case_pairs[tc[2]].get(p)
                if combo is not None:
                    covered[(algo, p)].add(combo)

            if show_progress:
                pct = 100.0 * len(ordered) / total if total else 100.0
                show_now = int(pct) != last_pct and int(pct) % 5 == 0
                if show_now:
                    bar = format_progress_bar(pct, width=20)
                    elapsed = time.perf_counter() - progress_start
                    print(f"\r  coverage order [{bar}] {pct:3.0f}% {elapsed:.1f}s", end="", flush=True)
                    if int(pct) % 5 == 0:
                        last_pct = int(pct)
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
        print(f"\r  coverage order [{format_progress_bar(100.0, width=20)}] 100% {elapsed:.1f}s", end="", flush=True)
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

    pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order if algo in by_algo}
    covered = {(algo, pair): set() for algo in pairs_by_algo for pair in pairs_by_algo[algo]}
    case_pairs = {}
    for algo, params, tid in test_cases:
        pairs = {}
        for pair in pairs_by_algo.get(algo, []):
            pairs[pair] = (params.get(pair[0]), params.get(pair[1]))
        case_pairs[tid] = pairs

    total = sum(len(cases) for cases in by_algo.values())
    ordered = []
    last_pct = -1
    progress_start = time.perf_counter()
    label_start = time.perf_counter() if label else None
    label_next_pct = 10

    def score_case(algo, tid):
        score = 0
        for p in pairs_by_algo.get(algo, []):
            combo = case_pairs[tid].get(p)
            if combo is not None and combo not in covered[(algo, p)]:
                score += 1
        return score

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
            heapq.heappush(heap, (-score_case(algo, tid), idx, tid))
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
                current_score = score_case(algo, tid)
                if current_score <= 0:
                    saturated.add(algo)
                    break
                if -neg_score == current_score:
                    tc = by_algo[algo][idx]
                    ordered.append(tc)
                    selected[algo].add(tid)
                    for p in pairs_by_algo.get(algo, []):
                        combo = case_pairs[tid].get(p)
                        if combo is not None:
                            covered[(algo, p)].add(combo)
                    progress = True
                    if show_progress:
                        pct = 100.0 * len(ordered) / total if total else 100.0
                        show_now = int(pct) != last_pct and int(pct) % 5 == 0
                        if show_now:
                            bar = format_progress_bar(pct, width=20)
                            elapsed = time.perf_counter() - progress_start
                            print(f"\r  coverage order [{bar}] {pct:3.0f}% {elapsed:.1f}s", end="", flush=True)
                            if int(pct) % 5 == 0:
                                last_pct = int(pct)
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
        print(f"\r  coverage order [{format_progress_bar(100.0, width=20)}] 100% {elapsed:.1f}s", end="", flush=True)
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

    pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order}
    covered = {(algo, pair): set() for algo in pairs_by_algo for pair in pairs_by_algo[algo]}
    case_pairs = {}
    for algo in algo_order:
        for _, params, tid in buckets.get(algo, []):
            pairs = {}
            for pair in pairs_by_algo.get(algo, []):
                pairs[pair] = (params.get(pair[0]), params.get(pair[1]))
            case_pairs[tid] = pairs

    indices = {algo: 0 for algo in algo_order}
    total_remaining = sum(len(buckets.get(algo, [])) for algo in algo_order)
    window_size = max(1, int(window_size))
    rebuilt = []
    while total_remaining > 0:
        current_window = min(window_size, total_remaining)
        quotas = {}
        fractions = []
        remaining_slots = current_window
        for algo in algo_order:
            lst = buckets.get(algo, [])
            count = len(lst) - indices.get(algo, 0)
            if count <= 0:
                continue
            raw = current_window * (count / total_remaining)
            q = int(raw)
            quotas[algo] = q
            remaining_slots -= q
            fractions.append((raw - q, algo))
        fractions.sort(reverse=True)
        for _, algo in fractions:
            if remaining_slots <= 0:
                break
            if quotas.get(algo, 0) < len(buckets.get(algo, [])):
                quotas[algo] += 1
                remaining_slots -= 1

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
                gain = 0
                for p in pairs_by_algo.get(algo, []):
                    combo = case_pairs[tc[2]].get(p)
                    if combo is not None and combo not in covered[(algo, p)]:
                        gain += 1
                if gain > best_gain:
                    best_gain = gain
                    best_algo = algo
                    best_tc = tc
            if best_algo is not None:
                indices[best_algo] = indices.get(best_algo, 0) + 1
                quotas[best_algo] -= 1
                window.append(best_tc)
                for p in pairs_by_algo.get(best_algo, []):
                    combo = case_pairs[best_tc[2]].get(p)
                    if combo is not None:
                        covered[(best_algo, p)].add(combo)
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
                    for p in pairs_by_algo.get(algo, []):
                        combo = case_pairs[tc[2]].get(p)
                        if combo is not None:
                            covered[(algo, p)].add(combo)
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
    label_map = {
        "mpc_realmove": "mpc_r",
        "mpc_simplemove": "mpc_s",
        "adp_realmove": "adp",
        "beam_realmove": "beam",
        "spst_realmove": "spst",
    }
    label = label_map.get(algo, algo)
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
        print(f"  shuffle global [{format_progress_bar(100.0, width=20)}] 100%   ")
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
    print(f"  chunk dispatch [{format_progress_bar(100.0, width=20)}] 100%   ")
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
        bar = format_progress_bar(pct, width=20)
        elapsed = time.perf_counter() - window_start
        print(
            f"\r  window-based coverage chunks + warmup [{bar}] {done_chunks}/{total_chunks} ({pct:.0f}%) {elapsed:.1f}s",
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
            bar = format_progress_bar(pct, width=20)
            elapsed = time.perf_counter() - window_start
            print(
            f"\r  window-based coverage chunks + warmup [{bar}] {done_chunks}/{total_chunks} ({pct:.0f}%) {elapsed:.1f}s",
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


def make_test_key(algo_name, params):
    """Create a unique key for a test case."""
    return (
        f"{algo_name}|h{params['horizon']}|ta{params['tackangle']}|a{params['alpha']}"
        f"|bw{params.get('beam_width', 'None')}|sc{params.get('scenarios', 'None')}"
        f"|dn{params.get('dir_noise', 'None')}|sn{params.get('speed_noise', 'None')}"
        f"|g{params.get('gamma', 'None')}|lr{params.get('lr', 'None')}|gp{params.get('goal_penalty', 'None')}"
        f"|e{params.get('epsilon', 'None')}|ed{params.get('epsilon_decay', 'None')}|emin{params.get('epsilon_min', 'None')}"
        f"|ap{params.get('approx', 'None')}|hs{params.get('hidden_size', 'None')}|l2{params.get('l2', 'None')}"
        f"|nf{params.get('normalize_features', 'None')}"
    )


def make_test_key_from_result_row(row):
    return make_test_key(
        row["algorithm"],
        {
            "horizon": row["horizon"],
            "tackangle": row["tackangle"],
            "alpha": row["alpha"],
            "beam_width": row.get("beam_width"),
            "scenarios": row.get("scenarios"),
            "dir_noise": row.get("dir_noise"),
            "speed_noise": row.get("speed_noise"),
            "gamma": row.get("gamma"),
            "lr": row.get("lr"),
            "goal_penalty": row.get("goal_penalty"),
            "epsilon": row.get("epsilon"),
            "epsilon_decay": row.get("epsilon_decay"),
            "epsilon_min": row.get("epsilon_min"),
            "approx": row.get("approx"),
            "hidden_size": row.get("hidden_size"),
            "l2": row.get("l2"),
            "normalize_features": row.get("normalize_features"),
        },
    )


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


DEFAULT_ALGO_ORDER = ["adp_realmove", "beam_realmove", "mpc_realmove", "mpc_simplemove", "spst_realmove"]
DEFAULT_WINDOW_SIZE = 500


def count_by_algorithm(results):
    """Count completed tests per algorithm."""
    counts = {"mpc_realmove": 0, "mpc_simplemove": 0, "adp_realmove": 0, "beam_realmove": 0, "spst_realmove": 0}
    for r in results:
        algo = r["algorithm"]
        if algo in counts:
            counts[algo] += 1
    return counts


def print_progress_summary(results, algo_order, title="ÉTAT D'AVANCEMENT DES TESTS"):
    """Affiche un résumé de l'avancement par algorithme avec barre de progression."""
    counts = count_by_algorithm(results)
    total_done = sum(counts.get(algo, 0) for algo in algo_order)
    total_all = sum(ALGO_TOTALS.get(algo, counts.get(algo, 0)) for algo in algo_order)

    print("\n" + "=" * 65)
    print(f"{title}")
    print("=" * 65)

    for algo in algo_order:
        done = counts[algo]
        total = ALGO_TOTALS.get(algo, done)
        pct = 100.0 * done / total if total > 0 else 0
        bar_filled = max(0, min(20, int(pct / 5)))
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        status = "✓ COMPLET" if done >= total else ""
        print(f"  {algo:18} [{bar}] {done:5}/{total:5} ({pct:5.1f}%) {status}")

    print("-" * 65)
    total_pct = 100.0 * total_done / total_all if total_all > 0 else 0
    bar_filled = max(0, min(20, int(total_pct / 5)))
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    print(f"  {'TOTAL':18} [{bar}] {total_done:5}/{total_all:5} ({total_pct:5.1f}%)")
    print("=" * 65 + "\n")


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
    """Blend ETA with fixed weights (former steady-state): 0.7*EWMA + 0.3*wall."""
    phase = "steady-state"
    w_ewma, w_wall = 0.70, 0.30
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
    for algo in algo_order:
        done = counts.get(algo, 0)
        if totals is not None:
            total = totals.get(algo, done)
        else:
            total = ALGO_TOTALS.get(algo, done)
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
    total_all = sum(ALGO_TOTALS.get(algo, counts.get(algo, 0)) for algo in algo_order)
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
    label_map = {
        "mpc_realmove": "mpc_r",
        "mpc_simplemove": "mpc_s",
        "adp_realmove": "adp",
        "beam_realmove": "beam",
        "spst_realmove": "spst",
    }
    parts = []
    for algo in algo_order:
        label = label_map.get(algo, algo)
        total = ALGO_TOTALS.get(algo, counts.get(algo, 0))
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
            f" | run [{run_bar}] {run_pct:5.1f}% "
            f"{run_done_i}/{run_total_i} ETA:{_format_duration(run_eta)}"
        )

    line = f"[{bar}] {total_pct:5.1f}% | {algo_status} | ETA: {eta_str}{run_status}"
    cols = shutil.get_terminal_size(fallback=(120, 24)).columns
    if cols > 8 and len(line) >= cols:
        line = line[: cols - 4] + "..."
    print(f"\r\x1b[2K{line}", end="", flush=True)
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


def clear_progress_lines():
    """Clear active progress display (single line or 2-line space-run mode)."""
    print("\r\x1b[2K", end="", flush=True)


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


def save_results(results, csv_path, json_path, start_time, total_tests, interrupted=False):
    """Save results to CSV and JSON files."""
    # CSV output
    with open(csv_path, "w", newline="") as f:
        fieldnames = ["algorithm", "horizon", "tackangle", "alpha", "beam_width",
                      "scenarios", "dir_noise", "speed_noise", "seed",
                      "gamma", "lr", "goal_penalty", "epsilon", "epsilon_decay", "epsilon_min",
                      "approx", "hidden_size", "l2", "normalize_features",
                      "total_sailed", "nb_tacks", "steps", "distance_to_mark",
                      "elapsed_time", "worker_elapsed_time", "orchestrator_overhead_time", "effective_elapsed_time",
                      "finished", "success"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # JSON output (with metadata)
    effective_ranges = {key: list(values) for key, values in PARAM_RANGES.items()}

    output_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "total_tests": total_tests,
            "completed_tests": len(results),
            "total_time_seconds": time.time() - start_time,
            "fixed_params": dict(FIXED_PARAMS),
            "param_ranges": effective_ranges,
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
        print(f"  shuffle global [{format_progress_bar(100.0, width=20)}] 100%   ")
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
    unknown = order_set - {"mpc_simplemove", "mpc_realmove", "adp_realmove", "beam_realmove", "spst_realmove"}
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
            bar = format_progress_bar(pct, width=20)
            print(f"\r  order by algo [{bar}] {pct:3.0f}%", end="", flush=True)
            last_pct = int(pct)
    tail = [tc for tc in test_cases if tc[0] not in order_set]
    ordered.extend(tail)
    if total_order:
        print(f"\r  order by algo [{format_progress_bar(100.0, width=20)}] 100%   ", end="", flush=True)
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
        eta_history.append((initial_elapsed, initial_run_eta_s, initial_run_eta_s, None, "steady-state", 0.7, 0.3))
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
                    print(f"Error in test: {e}")
                    continue

                orchestrator_start = time.time()
                completed_this_run += 1
                run_done_by_algo[algo_name] = run_done_by_algo.get(algo_name, 0) + 1
                elapsed = time.time() - start_time
                rate = completed_this_run / elapsed if elapsed > 0 else 0

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

                with results_lock:
                    results.append(row)
                    completed_keys.add(make_test_key(algo_name, params))
                    if all_results is not results:
                        all_results.append(row)
                    if all_completed_keys is not completed_keys:
                        all_completed_keys.add(make_test_key(algo_name, params))
                    orchestrator_overhead = max(0.0, time.time() - orchestrator_start)
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

                    update_eta_tracker(eta_tracker, row["algorithm"], row.get("effective_elapsed_time"))
                    if coverage_tracker is not None:
                        update_coverage_tracker(coverage_tracker, row["algorithm"], row)
                    if completed_this_run - last_save_count >= args.save_interval:
                        save_results(save_results_ref, csv_path, json_path, start_time, total_tests_original, interrupted=False)
                        last_save_count = completed_this_run

                    gains = coverage_gain_snapshot(coverage_tracker, algo_order)
                    eta_info = print_progress_line(
                        results,
                        elapsed,
                        rate,
                        algo_order,
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

    if interrupted_state["value"]:
        print()
    else:
        clear_progress_lines()
        print()
    return {
        "initial_run_eta_s": initial_run_eta_s,
        "batch_elapsed_s": time.time() - start_time,
    }


def main():
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
    args = parser.parse_args()
    global PARAM_RANGES, ALGO_TOTALS
    try:
        PARAM_RANGES = apply_range_overrides(BASE_PARAM_RANGES, args.range)
    except ValueError as e:
        print(str(e))
        return
    ALGO_TOTALS = compute_algo_totals(PARAM_RANGES)
    print("Effective parameter ranges:")
    for name, values in PARAM_RANGES.items():
        print(f"  {name}: {_format_allowed_values(values)}")

    # Setup paths
    output_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(output_dir, args.output)
    json_path = os.path.join(output_dir, args.json_output)

    if not args.resume and (os.path.exists(csv_path) or os.path.exists(json_path)):
        print("Existing benchmark results detected.")
        print(f"  - CSV: {csv_path if os.path.exists(csv_path) else 'not found'}")
        print(f"  - JSON: {json_path if os.path.exists(json_path) else 'not found'}")
        response = input("Type 'reset' to overwrite, or press Enter to cancel: ").strip().lower()
        if response != "reset":
            print("Cancelled. Re-run with --resume or type 'reset' to overwrite.")
            return

    # Load existing results if resuming
    results_all = []
    completed_keys_all = set()
    results = []
    completed_keys = set()
    if args.resume:
        results_all, completed_keys_all = load_existing_results(json_path)

    # Generate test cases
    all_test_cases = generate_test_cases(args.verbose)
    total_tests_original = len(all_test_cases)

    # Filter by algorithm if specified
    if args.algo != "all":
        algo_list = [item.strip() for item in args.algo.split(",") if item.strip()]
        valid_algos = {"adp_realmove", "beam_realmove", "mpc_realmove", "mpc_simplemove", "spst_realmove"}
        unknown_algos = [algo for algo in algo_list if algo not in valid_algos]
        if unknown_algos:
            print(f"Unknown algo(s) in --algo: {', '.join(unknown_algos)}")
            return
        algo_set = set(algo_list)
        all_test_cases = [tc for tc in all_test_cases if tc[0] in algo_set]


    # Build active resume view for current effective ranges
    if args.resume and completed_keys_all:
        active_completed_keys = set()
        for algo, params, _ in all_test_cases:
            k = make_test_key(algo, params)
            if k in completed_keys_all:
                active_completed_keys.add(k)
        results = [r for r in results_all if make_test_key_from_result_row(r) in active_completed_keys]
        completed_keys = active_completed_keys
        print(f"Resuming: found {len(completed_keys)} completed tests in active ranges")
        print_progress_summary(results, DEFAULT_ALGO_ORDER, "TESTS DÉJÀ EFFECTUÉS")
    elif args.resume:
        results = []
        completed_keys = set()
    else:
        results = []
        completed_keys = set()
        results_all = []
        completed_keys_all = set()

    # Filter out already completed tests (active scope)
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
                        bar = format_progress_bar(pct, width=20)
                        print(f"\r  filter progress [{bar}] {done_chunks}/{len(chunks)} chunks ({pct:.0f}%)", end="", flush=True)
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

    interrupted_state = {"value": False}
    print_progress_line._suspend = False
    benchmark_start = time.time()
    first_initial_eta_s = None
    eta_history = []

    def handle_interrupt(signum, frame):
        interrupted_state["value"] = True
        print_progress_line._suspend = True

    signal.signal(signal.SIGINT, handle_interrupt)

    try:
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
            )
            phase_sizes = {
                "coarse": len(plan.get("coarse", [])),
                "refine1": len(plan.get("refine1", [])),
                "refine2": len(plan.get("refine2", [])),
            }
            all_test_cases = list(plan.get("coarse", [])) + list(plan.get("refine1", [])) + list(plan.get("refine2", []))
            print(
                f"Space-search planning: coarse={phase_sizes['coarse']}, "
                f"refine1={phase_sizes['refine1']}, refine2={phase_sizes['refine2']} "
                f"(selected {len(all_test_cases)}/{planned_total_input})"
            )
            if args.verbose > 0:
                for algo in sorted(plan.get("per_algo_counts", {})):
                    c0, c1, c2, tot = plan["per_algo_counts"][algo]
                    print(
                        f"  {algo}: coarse={c0}, refine1={c1}, refine2={c2}, "
                        f"selected={c0 + c1 + c2}/{tot}"
                    )
            all_test_cases = order_cases_by_mode(all_test_cases, args)
            if len(all_test_cases) == 0:
                print("All tests already completed!")
                return
            batch_stats = execute_batch(
                all_test_cases,
                args,
                results,
                completed_keys,
                total_tests_original,
                csv_path,
                json_path,
                interrupted_state,
                phase_label=None,
                all_results=results_all,
                all_completed_keys=completed_keys_all,
                save_results_ref=results_all,
                eta_history=eta_history,
                run_start_time=benchmark_start,
            )
            if first_initial_eta_s is None and batch_stats:
                first_initial_eta_s = batch_stats.get("initial_run_eta_s")

        elif args.search_mode == "coarse-to-fine":
            remaining_cases = list(all_test_cases)
            initial_remaining = len(remaining_cases)
            print(f"Coarse-to-fine sequential run on {initial_remaining} remaining cases")
            for phase_name in ("coarse", "refine1", "refine2"):
                if interrupted_state["value"]:
                    break
                if not remaining_cases:
                    break

                phase_plan = build_space_search_plan(
                    remaining_cases,
                    results,
                    coarse_step=args.space_coarse_step,
                    refine_step=args.space_refine_step,
                    eta=args.space_eta,
                    early_stop_delta=args.space_early_stop_delta,
                    metric=args.metric,
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

                phase_cases = order_cases_by_mode(phase_cases, args)
                batch_stats = execute_batch(
                    phase_cases,
                    args,
                    results,
                    completed_keys,
                    total_tests_original,
                    csv_path,
                    json_path,
                    interrupted_state,
                    phase_label=phase_name,
                    all_results=results_all,
                    all_completed_keys=completed_keys_all,
                    save_results_ref=results_all,
                    eta_history=eta_history,
                    run_start_time=benchmark_start,
                )
                if first_initial_eta_s is None and batch_stats:
                    first_initial_eta_s = batch_stats.get("initial_run_eta_s")
                # Recompute remaining from completed keys (keeps only not-yet-run cases).
                remaining_cases = [
                    tc for tc in remaining_cases
                    if make_test_key(tc[0], tc[1]) not in completed_keys
                ]
        elif args.search_mode == "topk-search":
            planned_total_input = len(all_test_cases)
            plan = build_topk_search_plan(
                all_test_cases,
                results,
                metric=args.metric,
                explore_ratio=args.topk_explore_ratio,
                eta=args.topk_eta,
                seed=args.topk_seed,
            )
            all_test_cases = list(plan.get("selected", []))
            print(
                f"Top-k planning: exploit={plan.get('exploit_count', 0)}, "
                f"explore={plan.get('explore_count', 0)} "
                f"(selected {plan.get('selected_total', 0)}/{planned_total_input})",
                flush=True,
            )
            print(f"  top-k fusion [{format_progress_bar(100.0, width=20)}] 100%   ", flush=True)
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
            all_test_cases = order_cases_by_mode(all_test_cases, args)
            if len(all_test_cases) == 0:
                print("All tests already completed!")
                return
            batch_stats = execute_batch(
                all_test_cases,
                args,
                results,
                completed_keys,
                total_tests_original,
                csv_path,
                json_path,
                interrupted_state,
                phase_label=None,
                all_results=results_all,
                all_completed_keys=completed_keys_all,
                save_results_ref=results_all,
                eta_history=eta_history,
                run_start_time=benchmark_start,
            )
            if first_initial_eta_s is None and batch_stats:
                first_initial_eta_s = batch_stats.get("initial_run_eta_s")
        else:
            all_test_cases = order_cases_by_mode(all_test_cases, args)
            if len(all_test_cases) == 0:
                print("All tests already completed!")
                return
            batch_stats = execute_batch(
                all_test_cases,
                args,
                results,
                completed_keys,
                total_tests_original,
                csv_path,
                json_path,
                interrupted_state,
                phase_label=None,
                all_results=results_all,
                all_completed_keys=completed_keys_all,
                save_results_ref=results_all,
                eta_history=eta_history,
                run_start_time=benchmark_start,
            )
            if first_initial_eta_s is None and batch_stats:
                first_initial_eta_s = batch_stats.get("initial_run_eta_s")
    except ValueError as e:
        print(str(e))
        return
    except Exception as e:
        print(f"Error during benchmark: {e}")
        interrupted_state["value"] = True

    # Final save
    save_results(results_all, csv_path, json_path, benchmark_start, total_tests_original, interrupted=interrupted_state["value"])

    # Keep the last progress line visible on interruption; clear only on normal completion.
    if interrupted_state["value"]:
        print()
    else:
        clear_progress_lines()
        print()

    # Final progress summary
    summary_present_algos = {r.get("algorithm") for r in results if r.get("algorithm")}
    summary_algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in summary_present_algos]
    summary_algo_order.extend(sorted(summary_present_algos - set(summary_algo_order)))
    if not summary_algo_order:
        summary_algo_order = list(DEFAULT_ALGO_ORDER)
    print_progress_summary(results, summary_algo_order, "RÉSUMÉ FINAL")

    def _build_eta_history_lines(history):
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

    def _compute_stats(pred_totals_local, target):
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

    def _print_eta_history_compact(lines_local, pred_totals_local, target, stats):
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
            k = min(20, n)
            need = max(1, int(0.80 * k))
            consec = 0
            for s in range(0, n - k + 1):
                window = pred_totals_local[s:s + k]
                inside = sum(1 for v in window if abs(v - target_zone) <= tol)
                if inside >= need:
                    consec += 1
                    if consec >= 3:
                        mid_start_1based = s + 1
                        break
                else:
                    consec = 0
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

    total_elapsed = time.time() - benchmark_start
    pred_totals = []
    history_lines = []
    if eta_history:
        pred_totals, history_lines = _build_eta_history_lines(eta_history)

    if interrupted_state["value"]:
        print(f"Benchmark interrupted!")
        print(f"Progress saved: {len(results)}/{total_tests_original} tests completed")
        print(f"Run with --resume to continue")
        last20_totals = pred_totals[-20:] if pred_totals else []
        estimated_elapsed = _percentile(last20_totals, 0.5) if last20_totals else None
        if args.verbose > 0 and history_lines:
            partial_stats_for_view = _compute_stats(last20_totals, estimated_elapsed)
            _print_eta_history_compact(history_lines, pred_totals, estimated_elapsed, partial_stats_for_view)
        estimated_stats = _compute_stats(pred_totals, estimated_elapsed)
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

        partial_stats = _compute_stats(last20_totals, estimated_elapsed)
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
        print(f"Benchmark complete!")
        print()
        pred_stats = _compute_stats(pred_totals, total_elapsed)
        if args.verbose > 0 and history_lines:
            _print_eta_history_compact(history_lines, pred_totals, total_elapsed, pred_stats)
        elif not eta_history:
            print(f"Initial ETA estimate: {_format_duration(first_initial_eta_s)}")
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
    print(f"Results saved to:")
    print(f"  - {csv_path}")
    print(f"  - {json_path}")

    # Quick summary - only count finished races
    successful = [r for r in results if r["success"]]
    finished_races = [r for r in results if r.get("finished", False)]
    print(f"\nSummary: {len(successful)}/{total_tests_original} tests ran, {len(finished_races)} finished the race")

    for algo in ["beam_realmove", "mpc_realmove", "mpc_simplemove", "adp_realmove", "spst_realmove"]:
        algo_results = [r for r in finished_races if r["algorithm"] == algo]
        if algo_results:
            sailed = [r["total_sailed"] for r in algo_results if r["total_sailed"]]
            if sailed:
                print(f"\n{algo} ({len(algo_results)} finished):")
                print(f"  total_sailed: min={min(sailed):.1f}, max={max(sailed):.1f}, avg={sum(sailed)/len(sailed):.1f}")


if __name__ == "__main__":
    main()
