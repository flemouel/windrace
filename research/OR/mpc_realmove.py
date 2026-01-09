#!/usr/bin/env python3
"""
Model Predictive Control (MPC) - receding-horizon planner using game-like movement.

Goal: minimize total sailed distance while reaching the mark.
Approach: at each step, compare "tack now" vs "no tack", simulate a short
horizon with fixed tack, and pick the lower cost.

This version mirrors the game's moveByWind behavior:
- tack angle applied to wind direction
- layline clamping vs bearing to mark
- tack cooldown (delay)
- 10-second speed reduction after a tack
"""

import argparse
import os

from mpc_simplemove import (
    bearing_deg,
    destination_point,
    haversine_m,
    load_wind_data,
)


DEFAULT_TACKANGLE = 43.0


class BoatState:
    def __init__(self, lat, lng, tack_index=-1, tack_time=0, tack_delay=20):
        self.lat = lat
        self.lng = lng
        self.tack_index = tack_index
        self.tack_time = tack_time
        self.tack_delay = tack_delay
        self.total_distance = 0.0

    def can_tack(self, step_index):
        return (step_index - self.tack_time) > self.tack_delay

    def set_tack(self, step_index, tack_index):
        self.tack_index = tack_index
        self.tack_time = step_index


def clamp_heading_by_layline(wind_dir, heading_to_mark, tack_index, tackangle):
    """
    Mirror the in-game layline clamp used in moveByWind.
    """
    boat_dir = wind_dir + (tack_index * tackangle)
    wr = wind_dir - heading_to_mark
    if wr > 180:
        wr -= 360
    if wr > tackangle:
        if tack_index == -1:
            boat_dir = heading_to_mark
    elif wr < -tackangle:
        if tack_index == 1:
            boat_dir = heading_to_mark

    boat_dir = (boat_dir + 360.0) % 360.0
    return boat_dir


def move_by_wind_real(state, wind_dir, base_step_dist, heading_to_mark, step_index, tackangle):
    """
    Apply a single move using the game's logic.
    """
    elapsed = step_index - state.tack_time
    step_dist = base_step_dist * (0.9 if elapsed < 10 else 1.0)

    boat_dir = clamp_heading_by_layline(wind_dir, heading_to_mark, state.tack_index, tackangle)
    new_lat, new_lng = destination_point(state.lat, state.lng, boat_dir, step_dist)

    state.lat = new_lat
    state.lng = new_lng
    state.total_distance += step_dist
    return step_dist


def update_tack_delay(state, distance_to_mark, near_threshold=200, near_delay=10, far_delay=20):
    state.tack_delay = near_delay if distance_to_mark < near_threshold else far_delay


def simulate_horizon_real(state, wind_dir, wind_speed, start_index, horizon, tackangle,
                          near_threshold=200, near_delay=10, far_delay=20):
    """
    Simulate a fixed tack for a short horizon and return (traveled, end_lat, end_lng).
    """
    sim = BoatState(state.lat, state.lng, state.tack_index, state.tack_time, state.tack_delay)
    traveled = 0.0
    t = start_index
    for _ in range(horizon):
        if t >= len(wind_speed):
            break
        dist_to_mark = haversine_m(sim.lat, sim.lng, state.target_lat, state.target_lng)
        update_tack_delay(sim, dist_to_mark, near_threshold, near_delay, far_delay)
        heading = bearing_deg(sim.lat, sim.lng, state.target_lat, state.target_lng)
        step_dist = wind_speed[t] / 2.2
        traveled += move_by_wind_real(sim, wind_dir[t], step_dist, heading, t, tackangle)
        t += 1
    return traveled, sim.lat, sim.lng


def mpc_plan_real(
    wind_dir,
    wind_speed,
    start_lat,
    start_lng,
    finish_lat,
    finish_lng,
    tackangle=DEFAULT_TACKANGLE,
    horizon=60,
    goal_dist=20,
    alpha=1.0,
    near_threshold=200,
    near_delay=10,
    far_delay=20,
):
    tacks_log = []
    state = BoatState(start_lat, start_lng)
    state.target_lat = finish_lat
    state.target_lng = finish_lng
    step_count = 0
    trajectory = []

    while step_count < len(wind_speed):
        dist_to_mark = haversine_m(state.lat, state.lng, finish_lat, finish_lng)
        if dist_to_mark <= goal_dist:
            break

        update_tack_delay(state, dist_to_mark, near_threshold, near_delay, far_delay)

        # Option A: keep tack
        travel_a, lat_a, lng_a = simulate_horizon_real(
            state, wind_dir, wind_speed, step_count, horizon, tackangle,
            near_threshold=near_threshold, near_delay=near_delay, far_delay=far_delay
        )
        cost_a = travel_a + alpha * haversine_m(lat_a, lng_a, finish_lat, finish_lng)

        # Option B: tack now (if allowed)
        cost_b = float("inf")
        if state.can_tack(step_count):
            sim_b = BoatState(state.lat, state.lng, -state.tack_index, step_count, state.tack_delay)
            sim_b.target_lat = finish_lat
            sim_b.target_lng = finish_lng
            travel_b, lat_b, lng_b = simulate_horizon_real(
                sim_b, wind_dir, wind_speed, step_count, horizon, tackangle,
                near_threshold=near_threshold, near_delay=near_delay, far_delay=far_delay
            )
            cost_b = travel_b + alpha * haversine_m(lat_b, lng_b, finish_lat, finish_lng)

        decision = "KEEP"
        if cost_b < cost_a:
            state.set_tack(step_count, -state.tack_index)
            tack_label = "P" if state.tack_index == 1 else "S"
            tacks_log.append(f"{tack_label}{step_count}")
            decision = tack_label

        heading = bearing_deg(state.lat, state.lng, finish_lat, finish_lng)
        step_dist = wind_speed[step_count] / 2.2
        move_by_wind_real(state, wind_dir[step_count], step_dist, heading, step_count, tackangle)
        trajectory.append((step_count, decision, state.lat, state.lng))
        step_count += 1

    return {
        "steps": step_count,
        "tacks": tacks_log,
        "end_lat": state.lat,
        "end_lng": state.lng,
        "distance_to_mark": haversine_m(state.lat, state.lng, finish_lat, finish_lng),
        "total_sailed": state.total_distance,
        "trajectory": trajectory,
    }


def main():
    parser = argparse.ArgumentParser(description="MPC planner with game-like movement.")
    parser.add_argument("--wind", default=os.path.join("winddata", "wind_data.json"))
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--start-lng", type=float, required=True)
    parser.add_argument("--finish-lat", type=float, required=True)
    parser.add_argument("--finish-lng", type=float, required=True)
    parser.add_argument("--horizon", type=int, default=60)
    parser.add_argument("--tackangle", type=float, default=DEFAULT_TACKANGLE)
    parser.add_argument("--goal", type=float, default=20)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--near-threshold", type=float, default=200)
    parser.add_argument("--near-delay", type=int, default=10)
    parser.add_argument("--far-delay", type=int, default=20)
    parser.add_argument("--verbose", type=int, default=1)
    args = parser.parse_args()

    wind_dir, wind_speed = load_wind_data(args.wind)
    result = mpc_plan_real(
        wind_dir,
        wind_speed,
        args.start_lat,
        args.start_lng,
        args.finish_lat,
        args.finish_lng,
        tackangle=args.tackangle,
        horizon=args.horizon,
        goal_dist=args.goal,
        alpha=args.alpha,
        near_threshold=args.near_threshold,
        near_delay=args.near_delay,
        far_delay=args.far_delay,
    )
    if args.verbose >= 1:
        print("steps:", result["steps"])
        print("distance_to_mark:", round(result["distance_to_mark"], 2), "m")
        print("total_sailed:", round(result["total_sailed"], 2), "m")
        print("tacks:", result["tacks"][:10], "... total", len(result["tacks"]), "tack decisions")
    if args.verbose >= 2:
        print("trajectory:")
        for step, decision, lat, lng in result["trajectory"]:
            print(f"{step:04d} {decision} {lat:.7f} {lng:.7f}")


if __name__ == "__main__":
    main()
