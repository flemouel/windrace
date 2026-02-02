#!/usr/bin/env python3
"""
Extract trajectories from log files (MPC and Beam).
Automatically identifies and extracts the most recent trajectory sequence per method.
"""

import re
import os

def find_latest_sequence(log_file, pattern_type, method):
    """
    Find the latest trajectory sequence in a log file based on the last marker.
    Sequence starts after the last marker and continues while entries match.
    Returns (marker_line, entries) or None.
    """
    marker_pattern = re.compile(
        rf'(?i)\[(.*?)\].*"DEBUG (?:DEBUG {method} trajectory|{method} trajectory):?"'
    )
    entry_pattern = re.compile(
        rf'\[(.*?)\].*"DEBUG route {method} trajectory \({pattern_type}\) (\d+) (\w+) ([\d.]+) ([\d.-]+)"'
    )

    with open(log_file, 'r') as f:
        lines = f.readlines()

    marker_index = None
    marker_line = None
    for i in range(len(lines) - 1, -1, -1):
        if marker_pattern.search(lines[i]):
            marker_index = i
            marker_line = lines[i].strip()
            break

    if marker_index is None:
        return None

    entries = []
    for line in lines[marker_index + 1:]:
        entry_match = entry_pattern.search(line)
        if not entry_match:
            break
        step = int(entry_match.group(2))
        decision = entry_match.group(3)
        lat = float(entry_match.group(4))
        lng = float(entry_match.group(5))
        entries.append((step, decision, lat, lng))

    if not entries:
        return None

    entries.sort(key=lambda x: x[0])
    return marker_line, entries

def extract_and_save(log_file, pattern_type, method, output_file):
    """Extract latest trajectory and save to file."""

    if not os.path.exists(log_file):
        print(f"Warning: {log_file} not found!")
        return None

    print(f"\nProcessing {log_file}...")
    result = find_latest_sequence(log_file, pattern_type, method)
    if result is None:
        print(f"  No '{pattern_type}' trajectories found for {method}!")
        return None

    marker_line, entries = result
    print(f"  Latest marker: {marker_line}")
    print(f"  Steps: {entries[0][0]} to {entries[-1][0]} ({len(entries)} points)")

    # Save to file
    with open(output_file, 'w') as f:
        for step, decision, lat, lng in entries:
            f.write(f"DEBUG route {method} trajectory ({pattern_type}) {step:04d} {decision} {lat:.7f} {lng:.7f}\n")

    print(f"  Saved to: {output_file}")

    return {
        'method': method,
        'timestamp': marker_line,
        'count': len(entries),
        'first_step': entries[0][0],
        'last_step': entries[-1][0],
        'decisions': {
            'KEEP': sum(1 for e in entries if e[1] == 'KEEP'),
            'P': sum(1 for e in entries if e[1] == 'P'),
            'S': sum(1 for e in entries if e[1] == 'S')
        }
    }

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Extract latest trajectories from logs")
    parser.add_argument("--method", default="all", help="Method to extract: mpc, beam, or all")
    args = parser.parse_args()

    # Determine paths relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
    
    server_log = os.path.join(base_dir, 'logs', 'server.log')
    frontend_log = os.path.join(base_dir, 'logs', 'frontend.log')
    
    methods = []
    if args.method == "all":
        methods = ["mpc", "beam"]
    else:
        methods = [args.method]
    
    print("=" * 80)
    print("MPC TRAJECTORY EXTRACTION")
    print("=" * 80)
    
    planned_infos = []
    sailed_infos = []
    for method in methods:
        output_planned = os.path.join(script_dir, f'{method}_planned.txt')
        output_sailed = os.path.join(script_dir, f'{method}_sailed.txt')
        planned_infos.append(extract_and_save(server_log, 'planned', method, output_planned))
        sailed_infos.append(extract_and_save(frontend_log, 'sailed', method, output_sailed))

    # Summary
    print("\n" + "=" * 80)
    print("EXTRACTION SUMMARY")
    print("=" * 80)

    for info in planned_infos:
        if info:
            print(f"\n{info['method'].upper()} Planned Trajectory ({info['timestamp']}):")
            print(f"  Steps: {info['first_step']} to {info['last_step']} ({info['count']} points)")
            print(f"  Decisions: KEEP={info['decisions']['KEEP']}, P={info['decisions']['P']}, S={info['decisions']['S']}")
        else:
            print("\nPlanned Trajectory: NOT FOUND")

    for info in sailed_infos:
        if info:
            print(f"\n{info['method'].upper()} Sailed Trajectory ({info['timestamp']}):")
            print(f"  Steps: {info['first_step']} to {info['last_step']} ({info['count']} points)")
            print(f"  Decisions: KEEP={info['decisions']['KEEP']}, P={info['decisions']['P']}, S={info['decisions']['S']}")
        else:
            print("\nSailed Trajectory: NOT FOUND")

    print("\n" + "=" * 80)

    if any(planned_infos) and any(sailed_infos):
        print("\n✓ Extraction complete! You can now run:")
        print("  - compare_trajectories.py (for analysis)")
        print("  - visualize_trajectories.py (for PNG visualization)")
