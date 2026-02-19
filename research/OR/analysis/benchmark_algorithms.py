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

# Total tests per algorithm (derived from PARAM_RANGES)
def _range_len(name):
    return len(PARAM_RANGES.get(name, []))


ALGO_TOTALS = {
    "mpc_realmove": _range_len("horizon") * _range_len("alpha"),
    "mpc_simplemove": _range_len("horizon") * _range_len("alpha"),
    "beam_realmove": _range_len("horizon") * _range_len("alpha") * _range_len("beam_width"),
    "adp_realmove": _range_len("horizon") * _range_len("alpha") * _range_len("gamma") * _range_len("lr")
    * _range_len("goal_penalty") * _range_len("epsilon") * _range_len("epsilon_decay") * _range_len("epsilon_min")
    * _range_len("approx") * _range_len("hidden_size") * _range_len("l2") * _range_len("normalize_features"),
    "spst_realmove": _range_len("horizon") * _range_len("alpha") * _range_len("scenarios")
    * _range_len("dir_noise") * _range_len("speed_noise"),
}

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


def _estimate_case_cost(algo, params, value_means, algo_means):
    parts = []
    for p in algo_param_list(algo):
        key = (algo, p, params.get(p))
        v = value_means.get(key)
        if v is not None:
            parts.append(v)
    if parts:
        return sum(parts) / len(parts)
    return algo_means.get(algo, float("inf"))


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
                _estimate_case_cost(tc[0], tc[1], value_means, algo_means),
                make_test_key(tc[0], tc[1]),
            )
        )

        n1 = max(0, len(refine_pool) // eta)
        refine1 = refine_pool[:n1]
        refine1_keys = {make_test_key(tc[0], tc[1]) for tc in refine1}

        remaining_after_refine1 = [tc for tc in remaining if make_test_key(tc[0], tc[1]) not in refine1_keys]
        remaining_after_refine1.sort(
            key=lambda tc: (
                _estimate_case_cost(tc[0], tc[1], value_means, algo_means),
                make_test_key(tc[0], tc[1]),
            )
        )

        best_coarse = float("inf")
        if coarse:
            best_coarse = min(_estimate_case_cost(tc[0], tc[1], value_means, algo_means) for tc in coarse)
        best_refine1 = float("inf")
        if refine1:
            best_refine1 = min(_estimate_case_cost(tc[0], tc[1], value_means, algo_means) for tc in refine1)

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
            key = make_test_key(
                r["algorithm"],
                {
                    "horizon": r["horizon"],
                    "tackangle": r["tackangle"],
                    "alpha": r["alpha"],
                    "beam_width": r.get("beam_width"),
                    "scenarios": r.get("scenarios"),
                    "dir_noise": r.get("dir_noise"),
                    "speed_noise": r.get("speed_noise"),
                    "gamma": r.get("gamma"),
                    "lr": r.get("lr"),
                    "goal_penalty": r.get("goal_penalty"),
                    "epsilon": r.get("epsilon"),
                    "epsilon_decay": r.get("epsilon_decay"),
                    "epsilon_min": r.get("epsilon_min"),
                    "approx": r.get("approx"),
                    "hidden_size": r.get("hidden_size"),
                    "l2": r.get("l2"),
                    "normalize_features": r.get("normalize_features"),
                }
            )
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
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        status = "✓ COMPLET" if done >= total else ""
        print(f"  {algo:18} [{bar}] {done:5}/{total:5} ({pct:5.1f}%) {status}")

    print("-" * 65)
    total_pct = 100.0 * total_done / total_all if total_all > 0 else 0
    bar_filled = int(total_pct / 5)
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

    # ETA via EWMA per algo + p50/p90 bounds (fallback to global rate if needed).
    eta, eta_p50, eta_p90 = eta_snapshot(
        eta_tracker, counts, algo_order, fallback_rate=rate, workers=workers
    )
    if eta is None:
        remaining = total_all - total_done
        eta = remaining / rate if rate > 0 else 0
        eta_str = _format_duration(eta)
    else:
        eta_str = f"{_format_duration(eta)} (p50:{_format_duration(eta_p50)} p90:{_format_duration(eta_p90)})"

    # Barres compactes (plus courtes pour limiter le wrapping terminal).
    bar_width = 20
    bar_filled = int((total_pct / 100.0) * bar_width)
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
    if run_done is not None and run_total is not None and run_total > 0:
        run_done_i = max(0, int(run_done))
        run_total_i = max(1, int(run_total))
        run_pct = 100.0 * run_done_i / run_total_i
        run_filled = int((run_pct / 100.0) * bar_width)
        run_bar = "█" * run_filled + "░" * (bar_width - run_filled)
        run_eta, _, _ = eta_snapshot(
            eta_tracker,
            run_counts or {},
            algo_order,
            fallback_rate=rate,
            workers=workers,
            totals=run_totals,
        )
        run_status = (
            f" | run [{run_bar}] {run_pct:5.1f}% "
            f"{run_done_i}/{run_total_i} ETA:{_format_duration(run_eta)}"
        )

    line = f"[{bar}] {total_pct:5.1f}% | {algo_status} | ETA: {eta_str}{run_status}"
    cols = shutil.get_terminal_size(fallback=(120, 24)).columns
    if cols > 8 and len(line) >= cols:
        line = line[: cols - 4] + "..."
    print(f"\r\x1b[2K{line}", end="", flush=True)


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
                      "elapsed_time", "finished", "success"]
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
    parser.add_argument("--resume", action="store_true", help="Resume from previous run (skip completed tests)")
    parser.add_argument("--order", default="quota-window-coverage",
                        help="Execution order: 'quota-window-coverage' (local greedy per algo; windowed merge with "
                             "per-algo quotas and head gain selection; stratified across chunks when using workers), "
                             "'global-coverage' (global greedy coverage ordering), "
                             "'shuffle' (random across algos/params), or comma-separated algo list "
                             "(sequential params per algo)")
    parser.add_argument("--save-interval", type=int, default=10, help="Save results every N completed tests")
    parser.add_argument("--verbose", type=int, default=0, help="Verbosity level (0=summary, 1=details)")
    parser.add_argument("--window-size", type=int, default=DEFAULT_WINDOW_SIZE,
                        help="Window size for quota-window-coverage and ETA EWMA alpha=2/(W+1)")
    parser.add_argument("--search-mode", default="grid", choices=["grid", "space-search"],
                        help="Case generation mode: 'grid' runs all remaining cases; "
                             "'space-search' keeps a deterministic coarse/refine1/refine2 subset")
    parser.add_argument("--space-coarse-step", type=int, default=4,
                        help="Sparse-grid step for space-search coarse phase")
    parser.add_argument("--space-refine-step", type=int, default=2,
                        help="Sparse-grid step for space-search refine pool")
    parser.add_argument("--space-eta", type=int, default=3,
                        help="Successive-halving factor for space-search (keep ~1/eta per refine phase)")
    parser.add_argument("--space-early-stop-delta", type=float, default=0.0,
                        help="Optional relative min improvement for refine2 activation per algo")
    args = parser.parse_args()

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
    results = []
    completed_keys = set()
    if args.resume:
        results, completed_keys = load_existing_results(json_path)
        if completed_keys:
            print(f"Resuming: found {len(completed_keys)} completed tests")
            print_progress_summary(results, DEFAULT_ALGO_ORDER, "TESTS DÉJÀ EFFECTUÉS")

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


    # Filter out already completed tests
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

    # Optional adaptive subset selection (deterministic) before ordering.
    if args.search_mode == "space-search":
        planned_total_input = len(all_test_cases)
        plan = build_space_search_plan(
            all_test_cases,
            results,
            coarse_step=args.space_coarse_step,
            refine_step=args.space_refine_step,
            eta=args.space_eta,
            early_stop_delta=args.space_early_stop_delta,
        )
        phase_sizes = {
            "coarse": len(plan["coarse"]),
            "refine1": len(plan["refine1"]),
            "refine2": len(plan["refine2"]),
        }
        all_test_cases = plan["coarse"] + plan["refine1"] + plan["refine2"]
        print(
            f"Space-search planning: coarse={phase_sizes['coarse']}, "
            f"refine1={phase_sizes['refine1']}, refine2={phase_sizes['refine2']} "
            f"(selected {len(all_test_cases)}/{planned_total_input})"
        )
        if args.verbose > 0:
            for algo in sorted(plan["per_algo_counts"]):
                c0, c1, c2, tot = plan["per_algo_counts"][algo]
                print(
                    f"  {algo}: coarse={c0}, refine1={c1}, refine2={c2}, "
                    f"selected={c0 + c1 + c2}/{tot}"
                )

    if args.order == "shuffle":
        print(f"Ordering {len(all_test_cases)} cases...")
        random.shuffle(all_test_cases)
        print(f"  shuffle global [{format_progress_bar(100.0, width=20)}] 100%   ")
    elif args.order == "quota-window-coverage":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in {tc[0] for tc in all_test_cases}]
        if args.workers > 1 and len(all_test_cases) > args.workers:
            all_test_cases = order_cases_quota_window_coverage_chunked(
                all_test_cases, algo_order, args.workers, verbose=args.verbose, window_size=args.window_size
            )
            print("Test cases ordered by: quota-window-coverage (chunked)")
        else:
            print(f"Ordering {len(all_test_cases)} cases...")
            all_test_cases = order_cases_quota_window_coverage(
                all_test_cases, algo_order, show_progress=True, verbose=args.verbose, window_size=args.window_size
            )
            print("Test cases ordered by: quota-window-coverage")
    elif args.order == "global-coverage":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in {tc[0] for tc in all_test_cases}]
        algo_order.extend(sorted({tc[0] for tc in all_test_cases} - set(algo_order)))
        print(f"Ordering {len(all_test_cases)} cases...")
        all_test_cases = order_cases_coverage_global(all_test_cases, algo_order, show_progress=True)
        if args.verbose > 0:
            pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order}
            counts, max_gaps, max_runs, min_share, gain, uniq, param_run = compute_chunk_metrics(
                all_test_cases, algo_order, pairs_by_algo
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
    else:
        order_list = [item.strip() for item in args.order.split(",") if item.strip()]
        order_set = set(order_list)
        unknown = order_set - {"mpc_simplemove", "mpc_realmove", "adp_realmove", "beam_realmove", "spst_realmove"}
        if unknown:
            print(f"Unknown algo(s) in --order: {', '.join(sorted(unknown))}")
            return
        print(f"Ordering {len(all_test_cases)} cases...")
        ordered = []
        total_order = len(all_test_cases)
        done_order = 0
        last_pct = -1
        for algo in order_list:
            chunk = [tc for tc in all_test_cases if tc[0] == algo]
            ordered.extend(chunk)
            done_order += len(chunk)
            pct = 100.0 * done_order / total_order if total_order else 100.0
            if int(pct) != last_pct and int(pct) % 5 == 0:
                bar = format_progress_bar(pct, width=20)
                print(f"\r  order by algo [{bar}] {pct:3.0f}%", end="", flush=True)
                last_pct = int(pct)
        tail = [tc for tc in all_test_cases if tc[0] not in order_set]
        ordered.extend(tail)
        done_order += len(tail)
        if total_order:
            print(f"\r  order by algo [{format_progress_bar(100.0, width=20)}] 100%   ", end="", flush=True)
            print()
        all_test_cases = ordered
        print(f"Test cases ordered by: {', '.join(order_list)}")

    present_algos = {tc[0] for tc in all_test_cases}
    if args.order == "shuffle":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))
    elif args.order == "quota-window-coverage":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))
    elif args.order == "global-coverage":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))
    else:
        algo_order = [algo for algo in order_list if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))

    total_remaining = len(all_test_cases)
    run_totals_by_algo = {}
    for algo, _, _ in all_test_cases:
        run_totals_by_algo[algo] = run_totals_by_algo.get(algo, 0) + 1

    if args.order == "shuffle" and args.verbose > 0:
        pairs_by_algo = {algo: algo_param_pairs(algo) for algo in algo_order}
        counts, max_gaps, max_runs, min_share, gain, uniq, param_run = compute_chunk_metrics(
            all_test_cases, algo_order, pairs_by_algo
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
        print("  global distribution: " + " | ".join(parts))

    if total_remaining == 0:
        print("All tests already completed!")
        return

    print(f"Running {total_remaining} test cases with {args.workers} workers...")
    print(f"Total tests in benchmark: {total_tests_original}, already completed: {len(completed_keys)}, remaining: {total_remaining}")
    print(f"Algorithms: {', '.join(algo_order)}")
    print(f"Results will be saved every {args.save_interval} tests")
    print("Press Ctrl+C to interrupt and save progress\n")

    # Variables for tracking
    completed_this_run = 0
    start_time = time.time()
    results_lock = Lock()
    interrupted = False
    print_progress_line._suspend = False
    last_save_count = 0
    coverage_tracker = None
    eta_tracker = init_eta_tracker(algo_order, window=args.window_size)
    run_done_by_algo = {algo: 0 for algo in algo_order}
    for r in results:
        update_eta_tracker(eta_tracker, r.get("algorithm"), r.get("elapsed_time"))
    if args.order in {"quota-window-coverage", "global-coverage"}:
        coverage_tracker = init_coverage_tracker(algo_order)
        for r in results:
            update_coverage_tracker(coverage_tracker, r["algorithm"], r)

    def handle_interrupt(signum, frame):
        nonlocal interrupted
        interrupted = True
        print_progress_line._suspend = True

    # Register signal handler
    signal.signal(signal.SIGINT, handle_interrupt)

    try:
        with ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=_init_worker_ignore_sigint,
        ) as executor:
            # Submit all tasks
            futures = {executor.submit(run_single_test, tc): tc for tc in all_test_cases}
            pending = set(futures.keys())

            while pending and not interrupted:
                # Wait for any future to complete (with timeout to check interrupt flag)
                done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)

                for future in done:
                    if interrupted:
                        break

                    try:
                        algo_name, params, result, test_id = future.result()
                    except Exception as e:
                        print(f"Error in test: {e}")
                        continue

                    completed_this_run += 1
                    run_done_by_algo[algo_name] = run_done_by_algo.get(algo_name, 0) + 1

                    # Progress update
                    elapsed = time.time() - start_time
                    rate = completed_this_run / elapsed if elapsed > 0 else 0

                    # Store result
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
                        "finished": result.get("finished", False) if result else False,
                        "success": result.get("success", False) if result else False,
                    }

                    with results_lock:
                        results.append(row)
                        update_eta_tracker(eta_tracker, row["algorithm"], row.get("elapsed_time"))
                        if coverage_tracker is not None:
                            update_coverage_tracker(coverage_tracker, row["algorithm"], row)

                        # Periodic save
                        if completed_this_run - last_save_count >= args.save_interval:
                            save_results(results, csv_path, json_path, start_time, total_tests_original, interrupted=False)

                        # Update progress line after each test
                        gains = coverage_gain_snapshot(coverage_tracker, algo_order)
                        print_progress_line(
                            results,
                            elapsed,
                            rate,
                            algo_order,
                            coverage_gain=gains,
                            eta_tracker=eta_tracker,
                            workers=args.workers,
                            run_done=completed_this_run if args.search_mode == "space-search" else None,
                            run_total=total_remaining if args.search_mode == "space-search" else None,
                            run_counts=run_done_by_algo if args.search_mode == "space-search" else None,
                            run_totals=run_totals_by_algo if args.search_mode == "space-search" else None,
                        )

            # Cancel remaining futures if interrupted
            if interrupted:
                print()
                print("Interrupted! Saving progress...")
                for future in pending:
                    future.cancel()

    except Exception as e:
        print(f"Error during benchmark: {e}")
        interrupted = True

    # Final save
    save_results(results, csv_path, json_path, start_time, total_tests_original, interrupted=interrupted)

    # Keep the last progress line visible on interruption; clear only on normal completion.
    if interrupted:
        print()
    else:
        clear_progress_lines()
        print()

    # Final progress summary
    print_progress_summary(results, algo_order, "RÉSUMÉ FINAL")

    if interrupted:
        print(f"Benchmark interrupted!")
        print(f"Progress saved: {len(results)}/{total_tests_original} tests completed")
        print(f"Run with --resume to continue")
    else:
        print(f"Benchmark complete!")

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
