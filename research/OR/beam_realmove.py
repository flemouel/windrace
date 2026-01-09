#!/usr/bin/env python3
"""
Beam search (offline) planner for the WindGame.

Goal: minimize total sailed distance while reaching the mark.
Approach: expand tack/no-tack branches each step, keep the best K states.
"""

import argparse
import os

from mpc_realmove import (
    BoatState,
    DEFAULT_TACKANGLE,
    bearing_deg,
    haversine_m,
    load_wind_data,
    move_by_wind_real,
    update_tack_delay,
)


class BeamState:
    def __init__(self, lat, lng, tack_index=-1, tack_time=0, tack_delay=20):
        self.boat = BoatState(lat, lng, tack_index, tack_time, tack_delay)
        self.tacks = []
        self.step_count = 0
        self.trajectory = []

    def clone(self):
        cloned = BeamState(
            self.boat.lat,
            self.boat.lng,
            self.boat.tack_index,
            self.boat.tack_time,
            self.boat.tack_delay,
        )
        cloned.boat.total_distance = self.boat.total_distance
        cloned.tacks = list(self.tacks)
        cloned.step_count = self.step_count
        cloned.trajectory = list(self.trajectory)
        return cloned


def score_state(state, finish_lat, finish_lng, alpha):
    dist_to_mark = haversine_m(state.boat.lat, state.boat.lng, finish_lat, finish_lng)
    return state.boat.total_distance + alpha * dist_to_mark, dist_to_mark


def beam_search(
    wind_dir,
    wind_speed,
    start_lat,
    start_lng,
    finish_lat,
    finish_lng,
    tackangle=DEFAULT_TACKANGLE,
    horizon=None,
    goal_dist=20,
    alpha=0.0,
    beam_width=200,
    near_threshold=200,
    near_delay=10,
    far_delay=20,
):
    max_steps = horizon if horizon is not None else len(wind_speed)
    beam = [BeamState(start_lat, start_lng)]
    finished = []
    best_finished = None

    for step in range(max_steps):
        if not beam:
            break

        next_states = []
        for state in beam:
            state.step_count = step
            dist_to_mark = haversine_m(state.boat.lat, state.boat.lng, finish_lat, finish_lng)
            if dist_to_mark <= goal_dist:
                finished.append(state)
                if best_finished is None or state.boat.total_distance < best_finished.boat.total_distance:
                    best_finished = state
                continue

            update_tack_delay(state.boat, dist_to_mark, near_threshold, near_delay, far_delay)

            heading = bearing_deg(state.boat.lat, state.boat.lng, finish_lat, finish_lng)
            step_dist = wind_speed[step] / 2.2

            # Option A: keep tack
            keep_state = state.clone()
            move_by_wind_real(keep_state.boat, wind_dir[step], step_dist, heading, step, tackangle)
            keep_state.step_count = step + 1
            keep_state.trajectory.append((step, "KEEP", keep_state.boat.lat, keep_state.boat.lng))
            next_states.append(keep_state)

            # Option B: tack now (if allowed)
            if state.boat.can_tack(step):
                tack_state = state.clone()
                tack_state.boat.set_tack(step, -tack_state.boat.tack_index)
                tack_label = "P" if tack_state.boat.tack_index == 1 else "S"
                tack_state.tacks.append(f"{tack_label}{step}")
                move_by_wind_real(tack_state.boat, wind_dir[step], step_dist, heading, step, tackangle)
                tack_state.step_count = step + 1
                tack_state.trajectory.append((step, tack_label, tack_state.boat.lat, tack_state.boat.lng))
                next_states.append(tack_state)

        if not next_states:
            break

        # Prune to beam width by score.
        scored = []
        for state in next_states:
            score, dist_to_mark = score_state(state, finish_lat, finish_lng, alpha)
            scored.append((score, dist_to_mark, state))
        scored.sort(key=lambda item: item[0])
        beam = [item[2] for item in scored[:beam_width]]

        if best_finished is not None:
            min_distance = min(state.boat.total_distance for state in beam)
            if min_distance >= best_finished.boat.total_distance:
                break

    if finished:
        finished.sort(key=lambda st: st.boat.total_distance)
        return finished[0]
    if beam:
        beam.sort(key=lambda st: score_state(st, finish_lat, finish_lng, alpha)[0])
        return beam[0]
    return None


def main():
    parser = argparse.ArgumentParser(description="Beam search planner for WindGame.")
    parser.add_argument("--wind", default=os.path.join("winddata", "wind_data.json"))
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--start-lng", type=float, required=True)
    parser.add_argument("--finish-lat", type=float, required=True)
    parser.add_argument("--finish-lng", type=float, required=True)
    parser.add_argument("--horizon", type=int, default=None)
    parser.add_argument("--tackangle", type=float, default=DEFAULT_TACKANGLE)
    parser.add_argument("--goal", type=float, default=20)
    parser.add_argument("--alpha", type=float, default=0.0)
    parser.add_argument("--beam-width", type=int, default=200)
    parser.add_argument("--near-threshold", type=float, default=200)
    parser.add_argument("--near-delay", type=int, default=10)
    parser.add_argument("--far-delay", type=int, default=20)
    parser.add_argument("--verbose", type=int, default=1)
    args = parser.parse_args()

    wind_dir, wind_speed = load_wind_data(args.wind)
    best = beam_search(
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
        beam_width=args.beam_width,
        near_threshold=args.near_threshold,
        near_delay=args.near_delay,
        far_delay=args.far_delay,
    )
    if best is None:
        if args.verbose >= 1:
            print("steps: 0")
            print("distance_to_mark: -")
            print("total_sailed: 0")
            print("tacks: [] ... total 0 tack decisions")
        return

    dist_to_mark = haversine_m(best.boat.lat, best.boat.lng, args.finish_lat, args.finish_lng)
    if args.verbose >= 1:
        print("steps:", best.step_count)
        print("distance_to_mark:", round(dist_to_mark, 2), "m")
        print("total_sailed:", round(best.boat.total_distance, 2), "m")
        print("tacks:", best.tacks[:10], "... total", len(best.tacks), "tack decisions")
    if args.verbose >= 2:
        print("trajectory:")
        for step, decision, lat, lng in best.trajectory:
            print(f"{step:04d} {decision} {lat:.7f} {lng:.7f}")


if __name__ == "__main__":
    main()
