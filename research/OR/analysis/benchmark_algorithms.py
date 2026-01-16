#!/usr/bin/env python3
"""
Benchmark script for comparing trajectory planning algorithms.

Runs grid search over parameter ranges and collects metric:
- total_sailed: total distance traveled (only for finished races)

Algorithms tested:
- beam_realmove.py
- mpc_realmove.py
- mpc_simplemove.py

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
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime
from threading import Lock

# Total tests per algorithm (calculated from PARAM_RANGES)
ALGO_TOTALS = {
    "mpc_realmove": 16 * 12 * 16,      # horizon * tackangle * alpha = 3072
    "mpc_simplemove": 16 * 12 * 16,    # horizon * tackangle * alpha = 3072
    "beam_realmove": 16 * 12 * 16 * 16  # horizon * tackangle * alpha * beam_width = 49152
}

# Fixed parameters
FIXED_PARAMS = {
    "start_lat": 18.38142820098676,
    "start_lng": -64.56660471988445,
    "finish_lat": 18.40857035782242,
    "finish_lng": -64.53339266400592,
    "goal": 20,
    "verbose": 1,
    "start_index": 600,
    "near_threshold": 200,
    "near_delay": 10,
    "far_delay": 20,
}

# Parameter ranges for grid search
# All algorithms now use relative horizon (lookahead from start_index)
PARAM_RANGES = {
    "horizon": [10, 20, 30, 50, 75, 100, 150, 200, 300, 400, 600, 800, 1000, 1200, 1500, 2000],
    "tackangle": [30, 32, 34, 36, 38, 40, 42, 43, 44, 46, 48, 50],
    "alpha": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
    "beam_width": [5, 10, 20, 30, 50, 75, 100, 150, 200, 250, 300, 400, 500, 600, 800, 1000],
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
        "--tackangle", str(params["tackangle"]),
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


def generate_test_cases():
    """Generate all test cases for grid search."""
    test_cases = []
    test_id = 0

    # mpc_realmove: 3 parameters (no beam_width) - FIRST
    for horizon, tackangle, alpha in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["tackangle"],
        PARAM_RANGES["alpha"]
    ):
        params = {
            "horizon": horizon,
            "tackangle": tackangle,
            "alpha": alpha,
            "beam_width": None
        }
        test_cases.append(("mpc_realmove", params, test_id))
        test_id += 1

    # mpc_simplemove: 3 parameters (no beam_width) - SECOND
    for horizon, tackangle, alpha in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["tackangle"],
        PARAM_RANGES["alpha"]
    ):
        params = {
            "horizon": horizon,
            "tackangle": tackangle,
            "alpha": alpha,
            "beam_width": None
        }
        test_cases.append(("mpc_simplemove", params, test_id))
        test_id += 1

    # beam_realmove: all 4 parameters - LAST
    for horizon, tackangle, alpha, beam_width in itertools.product(
        PARAM_RANGES["horizon"],
        PARAM_RANGES["tackangle"],
        PARAM_RANGES["alpha"],
        PARAM_RANGES["beam_width"]
    ):
        params = {
            "horizon": horizon,
            "tackangle": tackangle,
            "alpha": alpha,
            "beam_width": beam_width
        }
        test_cases.append(("beam_realmove", params, test_id))
        test_id += 1

    return test_cases


def make_test_key(algo_name, params):
    """Create a unique key for a test case."""
    return f"{algo_name}|h{params['horizon']}|ta{params['tackangle']}|a{params['alpha']}|bw{params.get('beam_width', 'None')}"


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
                    "beam_width": r.get("beam_width")
                }
            )
            completed_keys.add(key)

        return results, completed_keys
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Could not load existing results: {e}")
        return [], set()


DEFAULT_ALGO_ORDER = ["mpc_simplemove", "mpc_realmove", "beam_realmove"]


def count_by_algorithm(results):
    """Count completed tests per algorithm."""
    counts = {"mpc_realmove": 0, "mpc_simplemove": 0, "beam_realmove": 0}
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


def print_progress_line(results, elapsed_time, rate, algo_order):
    """Affiche une ligne compacte de progression mise à jour à chaque test."""
    counts = count_by_algorithm(results)
    total_done = sum(counts.get(algo, 0) for algo in algo_order)
    total_all = sum(ALGO_TOTALS.get(algo, counts.get(algo, 0)) for algo in algo_order)
    total_pct = 100.0 * total_done / total_all if total_all > 0 else 0

    # Calculer ETA
    remaining = total_all - total_done
    eta = remaining / rate if rate > 0 else 0
    eta_str = f"{eta/3600:.1f}h" if eta > 3600 else f"{eta/60:.1f}min" if eta > 60 else f"{eta:.0f}s"

    # Barre compacte
    bar_filled = int(total_pct / 2)
    bar = "█" * bar_filled + "░" * (50 - bar_filled)

    # Affichage par algo compact
    label_map = {
        "mpc_realmove": "mpc_r",
        "mpc_simplemove": "mpc_s",
        "beam_realmove": "beam",
    }
    parts = []
    for algo in algo_order:
        label = label_map.get(algo, algo)
        total = ALGO_TOTALS.get(algo, counts.get(algo, 0))
        parts.append(f"{label}:{counts.get(algo, 0)}/{total}")
    algo_status = " | ".join(parts)

    # Utiliser \r pour réécrire la ligne (sans retour à la ligne)
    print(f"\r[{bar}] {total_pct:5.1f}% | {algo_status} | ETA: {eta_str}    ", end="", flush=True)


def save_results(results, csv_path, json_path, start_time, total_tests, interrupted=False):
    """Save results to CSV and JSON files."""
    # CSV output
    with open(csv_path, "w", newline="") as f:
        fieldnames = ["algorithm", "horizon", "tackangle", "alpha", "beam_width",
                      "total_sailed", "nb_tacks", "steps", "distance_to_mark",
                      "elapsed_time", "finished", "success"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # JSON output (with metadata)
    output_data = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "total_tests": total_tests,
            "completed_tests": len(results),
            "total_time_seconds": time.time() - start_time,
            "fixed_params": FIXED_PARAMS,
            "param_ranges": PARAM_RANGES,
            "interrupted": interrupted,
        },
        "results": results
    }
    with open(json_path, "w") as f:
        json.dump(output_data, f, indent=2)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark trajectory planning algorithms")
    parser.add_argument("--output", default="benchmark_results.csv", help="Output CSV file")
    parser.add_argument("--json-output", default="benchmark_results.json", help="Output JSON file")
    parser.add_argument("--workers", type=int, default=12, help="Number of parallel workers")
    parser.add_argument("--algo", default="all",
                        help="Which algorithm(s) to benchmark (comma-separated or 'all')")
    parser.add_argument("--quick", action="store_true", help="Run quick test with reduced parameter ranges")
    parser.add_argument("--resume", action="store_true", help="Resume from previous run (skip completed tests)")
    parser.add_argument("--order", default="shuffle",
                        help="Execution order: 'shuffle' or comma-separated algo list")
    parser.add_argument("--save-interval", type=int, default=10, help="Save results every N completed tests")
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
    all_test_cases = generate_test_cases()

    # Filter by algorithm if specified
    if args.algo != "all":
        algo_list = [item.strip() for item in args.algo.split(",") if item.strip()]
        valid_algos = {"beam_realmove", "mpc_realmove", "mpc_simplemove"}
        unknown_algos = [algo for algo in algo_list if algo not in valid_algos]
        if unknown_algos:
            print(f"Unknown algo(s) in --algo: {', '.join(unknown_algos)}")
            return
        algo_set = set(algo_list)
        all_test_cases = [tc for tc in all_test_cases if tc[0] in algo_set]

    # Quick mode: reduce parameter ranges
    if args.quick:
        quick_horizons = [60, 300, 1200, 2400]
        quick_tackangles = [40, 43, 45]
        quick_alphas = [0.0, 0.5, 1.0]
        quick_beam_widths = [50, 200, 400]

        filtered = []
        for algo, params, tid in all_test_cases:
            if params["horizon"] not in quick_horizons:
                continue
            if params["tackangle"] not in quick_tackangles:
                continue
            if params["alpha"] not in quick_alphas:
                continue
            if algo == "beam_realmove" and params["beam_width"] not in quick_beam_widths:
                continue
            filtered.append((algo, params, tid))
        all_test_cases = filtered

    # Filter out already completed tests
    if args.resume and completed_keys:
        remaining_tests = []
        for algo, params, tid in all_test_cases:
            key = make_test_key(algo, params)
            if key not in completed_keys:
                remaining_tests.append((algo, params, tid))
        skipped = len(all_test_cases) - len(remaining_tests)
        all_test_cases = remaining_tests
        print(f"Skipping {skipped} already completed tests")

    if args.order == "shuffle":
        random.shuffle(all_test_cases)
        print("Test cases shuffled for random execution order")
    else:
        order_list = [item.strip() for item in args.order.split(",") if item.strip()]
        order_set = set(order_list)
        unknown = order_set - {"mpc_simplemove", "mpc_realmove", "beam_realmove"}
        if unknown:
            print(f"Unknown algo(s) in --order: {', '.join(sorted(unknown))}")
            return
        ordered = []
        for algo in order_list:
            ordered.extend([tc for tc in all_test_cases if tc[0] == algo])
        ordered.extend([tc for tc in all_test_cases if tc[0] not in order_set])
        all_test_cases = ordered
        print(f"Test cases ordered by: {', '.join(order_list)}")

    present_algos = {tc[0] for tc in all_test_cases}
    if args.order == "shuffle":
        algo_order = [algo for algo in DEFAULT_ALGO_ORDER if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))
    else:
        algo_order = [algo for algo in order_list if algo in present_algos]
        algo_order.extend(sorted(present_algos - set(algo_order)))

    total_tests_original = len(generate_test_cases())
    total_remaining = len(all_test_cases)

    if total_remaining == 0:
        print("All tests already completed!")
        return

    print(f"Running {total_remaining} test cases with {args.workers} workers...")
    print(f"Total tests in benchmark: {total_tests_original}, already completed: {len(completed_keys)}")
    print(f"Algorithms: {', '.join(algo_order)}")
    print(f"Results will be saved every {args.save_interval} tests")
    print("Press Ctrl+C to interrupt and save progress\n")

    # Variables for tracking
    completed_this_run = 0
    start_time = time.time()
    results_lock = Lock()
    interrupted = False
    last_save_count = 0

    def handle_interrupt(signum, frame):
        nonlocal interrupted
        interrupted = True
        print("\n\nInterrupted! Saving progress...")

    # Register signal handler
    signal.signal(signal.SIGINT, handle_interrupt)

    try:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
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

                        # Periodic save
                        if completed_this_run - last_save_count >= args.save_interval:
                            save_results(results, csv_path, json_path, start_time, total_tests_original, interrupted=False)

                        # Update progress line after each test
                        print_progress_line(results, elapsed, rate, algo_order)

            # Cancel remaining futures if interrupted
            if interrupted:
                for future in pending:
                    future.cancel()

    except Exception as e:
        print(f"Error during benchmark: {e}")
        interrupted = True

    # Final save
    save_results(results, csv_path, json_path, start_time, total_tests_original, interrupted=interrupted)

    # Saut de ligne après la barre de progression
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

    for algo in ["beam_realmove", "mpc_realmove", "mpc_simplemove"]:
        algo_results = [r for r in finished_races if r["algorithm"] == algo]
        if algo_results:
            sailed = [r["total_sailed"] for r in algo_results if r["total_sailed"]]
            if sailed:
                print(f"\n{algo} ({len(algo_results)} finished):")
                print(f"  total_sailed: min={min(sailed):.1f}, max={max(sailed):.1f}, avg={sum(sailed)/len(sailed):.1f}")


if __name__ == "__main__":
    main()
