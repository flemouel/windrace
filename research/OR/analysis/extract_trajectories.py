#!/usr/bin/env python3
"""
Extract MPC trajectories from log files.
Automatically identifies and extracts the most recent trajectory sequence from each log.
"""

import re
import os

def find_trajectory_sequences(log_file, pattern_type):
    """
    Find all trajectory sequences in a log file.
    Each sequence starts with "DEBUG MPC trajectory" or "DEBUG MPC trajectory:" marker.
    Returns dict: {timestamp: [(step, decision, lat, lng), ...]}
    """
    marker_pattern = r'\[(.*?)\].*"DEBUG MPC trajectory:?"'
    entry_pattern = rf'\[(.*?)\].*"DEBUG route \w+ trajectory \({pattern_type}\) (\d+) (\w+) ([\d.]+) ([\d.-]+)"'

    sequences = {}
    current_timestamp = None

    with open(log_file, 'r') as f:
        for line in f:
            # Check for trajectory start marker
            marker_match = re.search(marker_pattern, line)
            if marker_match:
                current_timestamp = marker_match.group(1)
                sequences[current_timestamp] = []
                continue

            # Check for trajectory entry
            if current_timestamp:
                entry_match = re.search(entry_pattern, line)
                if entry_match:
                    step = int(entry_match.group(2))
                    decision = entry_match.group(3)
                    lat = float(entry_match.group(4))
                    lng = float(entry_match.group(5))

                    sequences[current_timestamp].append((step, decision, lat, lng))

    return sequences

def get_latest_sequence(sequences):
    """
    Get the most recent trajectory sequence based on timestamp.
    Returns the latest timestamp and its entries.
    """
    if not sequences:
        return None

    # Find the most recent timestamp
    latest_timestamp = max(sequences.keys())

    entries = sequences[latest_timestamp]

    if not entries:
        return None

    # Sort by step number
    entries.sort(key=lambda x: x[0])

    return latest_timestamp, entries

def extract_and_save(log_file, pattern_type, output_file):
    """Extract latest trajectory and save to file."""

    if not os.path.exists(log_file):
        print(f"Warning: {log_file} not found!")
        return None

    print(f"\nProcessing {log_file}...")
    sequences = find_trajectory_sequences(log_file, pattern_type)

    if not sequences:
        print(f"  No '{pattern_type}' trajectories found!")
        return None

    print(f"  Found {len(sequences)} trajectory sequence(s)")

    # Get latest sequence
    result = get_latest_sequence(sequences)
    if result is None:
        print(f"  No valid sequence found!")
        return None

    timestamp, entries = result

    print(f"  Latest sequence: {timestamp}")
    print(f"  Steps: {entries[0][0]} to {entries[-1][0]} ({len(entries)} points)")

    # Save to file
    with open(output_file, 'w') as f:
        for step, decision, lat, lng in entries:
            f.write(f"DEBUG route mpc trajectory ({pattern_type}) {step:04d} {decision} {lat:.7f} {lng:.7f}\n")

    print(f"  Saved to: {output_file}")

    return {
        'timestamp': timestamp,
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
    # Determine paths relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
    
    server_log = os.path.join(base_dir, 'logs', 'server.log')
    frontend_log = os.path.join(base_dir, 'logs', 'frontend.log')
    
    output_planned = os.path.join(script_dir, 'mpc_planned.txt')
    output_sailed = os.path.join(script_dir, 'mpc_sailed.txt')
    
    print("=" * 80)
    print("MPC TRAJECTORY EXTRACTION")
    print("=" * 80)
    
    # Extract planned trajectory
    planned_info = extract_and_save(server_log, 'planned', output_planned)
    
    # Extract sailed trajectory
    sailed_info = extract_and_save(frontend_log, 'sailed', output_sailed)
    
    # Summary
    print("\n" + "=" * 80)
    print("EXTRACTION SUMMARY")
    print("=" * 80)
    
    if planned_info:
        print(f"\nPlanned Trajectory ({planned_info['timestamp']}):")
        print(f"  Steps: {planned_info['first_step']} to {planned_info['last_step']} ({planned_info['count']} points)")
        print(f"  Decisions: KEEP={planned_info['decisions']['KEEP']}, P={planned_info['decisions']['P']}, S={planned_info['decisions']['S']}")
    else:
        print("\nPlanned Trajectory: NOT FOUND")
    
    if sailed_info:
        print(f"\nSailed Trajectory ({sailed_info['timestamp']}):")
        print(f"  Steps: {sailed_info['first_step']} to {sailed_info['last_step']} ({sailed_info['count']} points)")
        print(f"  Decisions: KEEP={sailed_info['decisions']['KEEP']}, P={sailed_info['decisions']['P']}, S={sailed_info['decisions']['S']}")
    else:
        print("\nSailed Trajectory: NOT FOUND")
    
    print("\n" + "=" * 80)
    
    if planned_info and sailed_info:
        print("\n✓ Extraction complete! You can now run:")
        print("  - compare_trajectories.py (for analysis)")
        print("  - visualize_trajectories.py (for PNG visualization)")
