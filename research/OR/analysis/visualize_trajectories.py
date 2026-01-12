#!/usr/bin/env python3
"""
Visualize MPC planned vs sailed trajectories with temporal alignment.
Uses matplotlib for static visualization.
"""

import re
import math
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle

def parse_trajectory(filename):
    """Parse trajectory file and return dict keyed by step."""
    pattern = r'DEBUG route mpc trajectory \((?:planned|sailed)\) (\d+) (\w+) ([\d.]+) ([\d.-]+)'
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

def create_visualization(planned, sailed):
    """Create time-aligned visualization with both trajectories."""

    # Time alignment
    planned_steps = sorted(planned.keys())
    sailed_steps = sorted(sailed.keys())

    planned_offset = planned_steps[0]
    sailed_offset = sailed_steps[0]

    # Create aligned trajectories (indexed by elapsed time)
    planned_aligned = {step - planned_offset: data for step, data in planned.items()}
    sailed_aligned = {step - sailed_offset: data for step, data in sailed.items()}

    # Find common elapsed times
    common_elapsed = sorted(set(planned_aligned.keys()) & set(sailed_aligned.keys()))

    # Calculate deviations
    deviations = []
    for t in common_elapsed:
        p = planned_aligned[t]
        s = sailed_aligned[t]
        dist = haversine(p['lat'], p['lng'], s['lat'], s['lng'])
        deviations.append((t, dist))

    # Find worst deviation zone
    deviations.sort(key=lambda x: x[1], reverse=True)
    worst_zone_start = max(0, deviations[0][0] - 10)
    worst_zone_end = min(max(common_elapsed), deviations[0][0] + 10)

    # Create figure with 3 subplots
    fig = plt.figure(figsize=(20, 12))
    gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.3)
    ax1 = fig.add_subplot(gs[0, :])  # Top: full trajectories
    ax2 = fig.add_subplot(gs[1, 0])  # Bottom left: deviation over time
    ax3 = fig.add_subplot(gs[1, 1])  # Bottom right: worst zone detail

    # Plot 1: Time-aligned trajectories overlay
    p_lngs = [planned_aligned[t]['lng'] for t in sorted(planned_aligned.keys())]
    p_lats = [planned_aligned[t]['lat'] for t in sorted(planned_aligned.keys())]
    s_lngs = [sailed_aligned[t]['lng'] for t in sorted(sailed_aligned.keys())]
    s_lats = [sailed_aligned[t]['lat'] for t in sorted(sailed_aligned.keys())]

    ax1.plot(p_lngs, p_lats, 'b-', linewidth=2, alpha=0.7, label=f'Planned ({len(planned_aligned)} pts, step {planned_steps[0]}-{planned_steps[-1]})')
    ax1.plot(s_lngs, s_lats, 'r-', linewidth=2, alpha=0.7, label=f'Sailed ({len(sailed_aligned)} pts, step {sailed_steps[0]}-{sailed_steps[-1]})')

    # Mark start points (both at t=0)
    ax1.plot(p_lngs[0], p_lats[0], 'bo', markersize=15, label=f'Planned Start (t=0, step {planned_steps[0]})', zorder=5)
    ax1.plot(s_lngs[0], s_lats[0], 'ro', markersize=15, label=f'Sailed Start (t=0, step {sailed_steps[0]})', zorder=5)

    # Mark end points
    ax1.plot(p_lngs[-1], p_lats[-1], 'bs', markersize=15, label=f'Planned End (t={len(planned_aligned)-1})', zorder=5)
    ax1.plot(s_lngs[-1], s_lats[-1], 'rs', markersize=15, label=f'Sailed End (t={len(sailed_aligned)-1})', zorder=5)

    # Mark tacks
    p_tacks = [(t, planned_aligned[t]) for t in planned_aligned.keys() if planned_aligned[t]['decision'] in ('P', 'S')]
    s_tacks = [(t, sailed_aligned[t]) for t in sailed_aligned.keys() if sailed_aligned[t]['decision'] in ('P', 'S')]

    if p_tacks:
        p_tack_lngs = [d['lng'] for _, d in p_tacks]
        p_tack_lats = [d['lat'] for _, d in p_tacks]
        ax1.scatter(p_tack_lngs, p_tack_lats, c='cyan', s=150, marker='*',
                   edgecolors='blue', linewidths=2, label=f'Planned Tacks ({len(p_tacks)})', zorder=6)

    if s_tacks:
        s_tack_lngs = [d['lng'] for _, d in s_tacks]
        s_tack_lats = [d['lat'] for _, d in s_tacks]
        ax1.scatter(s_tack_lngs, s_tack_lats, c='yellow', s=150, marker='*',
                   edgecolors='red', linewidths=2, label=f'Sailed Tacks ({len(s_tacks)})', zorder=6)

    # Mark worst deviation zone
    if common_elapsed:
        worst_t = deviations[0][0]
        p_worst = planned_aligned[worst_t]
        s_worst = sailed_aligned[worst_t]
        ax1.plot([p_worst['lng'], s_worst['lng']], [p_worst['lat'], s_worst['lat']],
                'k--', linewidth=2, alpha=0.5, label=f'Max deviation at t={worst_t} ({deviations[0][1]:.0f}m)')
        ax1.plot(p_worst['lng'], p_worst['lat'], 'ko', markersize=10, zorder=7)
        ax1.plot(s_worst['lng'], s_worst['lat'], 'ko', markersize=10, zorder=7)

    ax1.set_xlabel('Longitude', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Latitude', fontsize=12, fontweight='bold')
    ax1.set_title('MPC Trajectory Comparison: Time-Aligned Planned vs Sailed', fontsize=14, fontweight='bold')
    ax1.legend(loc='best', fontsize=9, ncol=2)
    ax1.grid(True, alpha=0.3)
    ax1.set_aspect('equal', adjustable='box')

    # Plot 2: Deviation over time
    dev_times = [t for t, _ in deviations]
    dev_distances = [d for _, d in deviations]

    # Sort by time for plotting
    time_dev_pairs = sorted(zip(dev_times, dev_distances), key=lambda x: x[0])
    dev_times_sorted = [t for t, _ in time_dev_pairs]
    dev_distances_sorted = [d for _, d in time_dev_pairs]

    ax2.plot(dev_times_sorted, dev_distances_sorted, 'g-', linewidth=2, alpha=0.7)
    ax2.fill_between(dev_times_sorted, dev_distances_sorted, alpha=0.3, color='green')

    # Mark mean deviation
    mean_dev = sum(dev_distances) / len(dev_distances)
    ax2.axhline(y=mean_dev, color='orange', linestyle='--', linewidth=2, label=f'Mean: {mean_dev:.0f}m')

    # Mark worst zone
    ax2.axvspan(worst_zone_start, worst_zone_end, alpha=0.2, color='red', label=f'Worst zone (t={worst_zone_start}-{worst_zone_end})')

    # Mark max deviation point
    ax2.plot(deviations[0][0], deviations[0][1], 'ro', markersize=10, label=f'Max: {deviations[0][1]:.0f}m at t={deviations[0][0]}')

    ax2.set_xlabel('Elapsed Time (steps)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Position Deviation (m)', fontsize=12, fontweight='bold')
    ax2.set_title('Position Deviation Over Time', fontsize=13, fontweight='bold')
    ax2.legend(loc='best', fontsize=10)
    ax2.grid(True, alpha=0.3)

    # Plot 3: Worst deviation zone detail
    zone_times = [t for t in common_elapsed if worst_zone_start <= t <= worst_zone_end]

    if zone_times:
        p_zone_lngs = [planned_aligned[t]['lng'] for t in zone_times]
        p_zone_lats = [planned_aligned[t]['lat'] for t in zone_times]
        s_zone_lngs = [sailed_aligned[t]['lng'] for t in zone_times]
        s_zone_lats = [sailed_aligned[t]['lat'] for t in zone_times]

        ax3.plot(p_zone_lngs, p_zone_lats, 'b-', linewidth=3, alpha=0.7, marker='o', markersize=4, label='Planned')
        ax3.plot(s_zone_lngs, s_zone_lats, 'r-', linewidth=3, alpha=0.7, marker='o', markersize=4, label='Sailed')

        # Draw connections between corresponding time points
        for t in zone_times[::2]:  # Every other point for clarity
            p = planned_aligned[t]
            s = sailed_aligned[t]
            dist = haversine(p['lat'], p['lng'], s['lat'], s['lng'])
            ax3.plot([p['lng'], s['lng']], [p['lat'], s['lat']], 'k--', alpha=0.3, linewidth=1)

            # Add time label
            mid_lng = (p['lng'] + s['lng']) / 2
            mid_lat = (p['lat'] + s['lat']) / 2
            ax3.text(mid_lng, mid_lat, f't={t}\n{dist:.0f}m', fontsize=7, ha='center',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))

        # Mark tacks in zone
        zone_p_tacks = [(t, planned_aligned[t]) for t in zone_times if planned_aligned[t]['decision'] in ('P', 'S')]
        zone_s_tacks = [(t, sailed_aligned[t]) for t in zone_times if sailed_aligned[t]['decision'] in ('P', 'S')]

        for t, d in zone_p_tacks:
            ax3.scatter(d['lng'], d['lat'], c='cyan', s=200, marker='*', edgecolors='blue', linewidths=2, zorder=6)
            ax3.text(d['lng'], d['lat']+0.0001, f"{d['decision']}", fontsize=10, ha='center', fontweight='bold')

        for t, d in zone_s_tacks:
            ax3.scatter(d['lng'], d['lat'], c='yellow', s=200, marker='*', edgecolors='red', linewidths=2, zorder=6)
            ax3.text(d['lng'], d['lat']-0.0001, f"{d['decision']}", fontsize=10, ha='center', fontweight='bold')

    ax3.set_xlabel('Longitude', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Latitude', fontsize=12, fontweight='bold')
    ax3.set_title(f'Worst Deviation Zone Detail (t={worst_zone_start}-{worst_zone_end})', fontsize=13, fontweight='bold')
    ax3.legend(loc='best', fontsize=10)
    ax3.grid(True, alpha=0.3)
    ax3.set_aspect('equal', adjustable='box')

    return fig

if __name__ == '__main__':
    print("Loading trajectories...")
    planned = parse_trajectory('mpc_planned.txt')
    sailed = parse_trajectory('mpc_sailed.txt')

    print(f"Planned: {len(planned)} points")
    print(f"Sailed: {len(sailed)} points")

    print("\nCreating time-aligned visualization...")
    fig = create_visualization(planned, sailed)

    output_file = 'trajectory_comparison.png'
    fig.savefig(output_file, dpi=150, bbox_inches='tight')

    print(f"\nVisualization saved to: {output_file}")
    print("Opening image...")

    plt.show()
