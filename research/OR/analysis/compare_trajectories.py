#!/usr/bin/env python3
"""
Compare planned vs sailed trajectories.
"""

import argparse
import re
import math

def parse_trajectory(filename, method):
    """Parse trajectory file and return dict keyed by step."""
    pattern = rf'DEBUG route {re.escape(method)} trajectory \((?:planned|sailed)\) (\d+) (\w+) ([\d.]+) ([\d.-]+)'
    entries = {}

    with open(filename, 'r') as f:
        for line in f:
            match = re.search(pattern, line)
            if match:
                step = int(match.group(1))
                decision = match.group(2)
                lat = float(match.group(3))
                lng = float(match.group(4))
                entries[step] = {'decision': decision, 'lat': lat, 'lng': lng}

    return entries

def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two points."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def analyze_trajectories(planned, sailed, method_label):
    """Analyze and compare trajectories with temporal alignment."""

    print("=" * 80)
    print(f"{method_label} TRAJECTORY COMPARISON ANALYSIS (TIME-ALIGNED)")
    print("=" * 80)
    print()

    # Basic statistics
    print("1. BASIC STATISTICS")
    print("-" * 80)
    planned_steps = sorted(planned.keys())
    sailed_steps = sorted(sailed.keys())

    print(f"Planned trajectory: {len(planned)} steps (step {planned_steps[0]} to {planned_steps[-1]})")
    print(f"Sailed trajectory:  {len(sailed)} steps (step {sailed_steps[0]} to {sailed_steps[-1]})")
    print()

    # Time alignment: normalize both to start at 0
    print("2. TIME ALIGNMENT")
    print("-" * 80)
    planned_offset = planned_steps[0]
    sailed_offset = sailed_steps[0]

    print(f"Planned offset: {planned_offset} (normalized to 0)")
    print(f"Sailed offset:  {sailed_offset} (normalized to 0)")
    print()

    # Create aligned trajectories (indexed by elapsed time from start)
    planned_aligned = {step - planned_offset: data for step, data in planned.items()}
    sailed_aligned = {step - sailed_offset: data for step, data in sailed.items()}

    # Find common elapsed times
    common_elapsed = sorted(set(planned_aligned.keys()) & set(sailed_aligned.keys()))
    print(f"Common elapsed time steps: {len(common_elapsed)}")
    if common_elapsed:
        print(f"  Range: t={min(common_elapsed)} to t={max(common_elapsed)}")
    print()

    # Decisions analysis
    print("3. DECISION ANALYSIS")
    print("-" * 80)

    planned_decisions = {}
    for step, data in planned.items():
        dec = data['decision']
        planned_decisions[dec] = planned_decisions.get(dec, 0) + 1

    sailed_decisions = {}
    for step, data in sailed.items():
        dec = data['decision']
        sailed_decisions[dec] = sailed_decisions.get(dec, 0) + 1

    print("Planned trajectory decisions:")
    for dec, count in sorted(planned_decisions.items()):
        pct = (count / len(planned)) * 100
        print(f"  {dec:10s}: {count:5d} ({pct:5.1f}%)")

    print()
    print("Sailed trajectory decisions:")
    for dec, count in sorted(sailed_decisions.items()):
        pct = (count / len(sailed)) * 100
        print(f"  {dec:10s}: {count:5d} ({pct:5.1f}%)")
    print()

    # Compare aligned trajectories
    if common_elapsed:
        print("4. COMPARISON ON ALIGNED TRAJECTORIES")
        print("-" * 80)

        decision_matches = 0
        distances = []

        for t in common_elapsed:
            p = planned_aligned[t]
            s = sailed_aligned[t]

            if p['decision'] == s['decision']:
                decision_matches += 1

            dist = haversine(p['lat'], p['lng'], s['lat'], s['lng'])
            distances.append(dist)

        match_pct = (decision_matches / len(common_elapsed)) * 100
        print(f"Decision match rate: {decision_matches}/{len(common_elapsed)} ({match_pct:.1f}%)")
        print()

        print("Position deviation statistics (time-aligned):")
        print(f"  Mean distance:   {sum(distances)/len(distances):.2f} m")
        print(f"  Min distance:    {min(distances):.2f} m")
        print(f"  Max distance:    {max(distances):.2f} m")
        print(f"  Median distance: {sorted(distances)[len(distances)//2]:.2f} m")
        print()

        # Show worst deviations
        print("Top 10 largest position deviations (at aligned time steps):")
        indexed_distances = [(common_elapsed[i], distances[i]) for i in range(len(distances))]
        indexed_distances.sort(key=lambda x: x[1], reverse=True)

        for i, (t, dist) in enumerate(indexed_distances[:10], 1):
            p = planned_aligned[t]
            s = sailed_aligned[t]
            dec_match = "✓" if p['decision'] == s['decision'] else "✗"
            print(f"  {i:2d}. t={t:4d}: {dist:7.2f} m  [{p['decision']} vs {s['decision']} {dec_match}]")
        print()

    # Geographic bounds
    print("5. GEOGRAPHIC BOUNDS")
    print("-" * 80)

    p_lats = [d['lat'] for d in planned.values()]
    p_lngs = [d['lng'] for d in planned.values()]
    s_lats = [d['lat'] for d in sailed.values()]
    s_lngs = [d['lng'] for d in sailed.values()]

    print("Planned trajectory:")
    print(f"  Latitude:  {min(p_lats):.6f} to {max(p_lats):.6f}")
    print(f"  Longitude: {min(p_lngs):.6f} to {max(p_lngs):.6f}")

    print()
    print("Sailed trajectory:")
    print(f"  Latitude:  {min(s_lats):.6f} to {max(s_lats):.6f}")
    print(f"  Longitude: {min(s_lngs):.6f} to {max(s_lngs):.6f}")
    print()

    # Calculate total distance
    print("6. TOTAL DISTANCE SAILED")
    print("-" * 80)

    def calc_total_distance(traj):
        steps = sorted(traj.keys())
        total = 0
        for i in range(len(steps)-1):
            s1 = traj[steps[i]]
            s2 = traj[steps[i+1]]
            total += haversine(s1['lat'], s1['lng'], s2['lat'], s2['lng'])
        return total

    planned_dist = calc_total_distance(planned)
    sailed_dist = calc_total_distance(sailed)

    print(f"Planned trajectory: {planned_dist:.2f} m")
    print(f"Sailed trajectory:  {sailed_dist:.2f} m")
    print(f"Difference:         {abs(planned_dist - sailed_dist):.2f} m ({((sailed_dist/planned_dist - 1)*100):.1f}%)")
    print()

    print("=" * 80)

if __name__ == '__main__':
    ALL_METHODS = ["mpc", "beam", "adp", "spst", "sa"]
    parser = argparse.ArgumentParser(description="Compare planned vs sailed trajectories")
    parser.add_argument("--method", default="all",
                        help=f"Method to compare: {', '.join(ALL_METHODS)}, or all (default: all)")
    args = parser.parse_args()

    if args.method == "all":
        methods = ALL_METHODS
    else:
        methods = [args.method]

    for method in methods:
        planned_file = f'{method}_planned.txt'
        sailed_file = f'{method}_sailed.txt'
        try:
            planned = parse_trajectory(planned_file, method)
            sailed = parse_trajectory(sailed_file, method)
        except FileNotFoundError:
            print(f"Skipping {method}: trajectory files not found")
            continue
        if not planned or not sailed:
            print(f"Skipping {method}: no trajectory data found")
            continue
        analyze_trajectories(planned, sailed, method.upper())
