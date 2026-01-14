#!/usr/bin/env python3
"""
Beam search (offline) planner for the WindGame.

Goal: minimize total sailed distance while reaching the mark.
Approach: at each step, use beam search over a lookahead horizon to decide
whether to tack or not, then execute the best first move and repeat.

This version uses horizon as a lookahead window (like MPC), continuing
until the mark is reached or wind data is exhausted.
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
        self.first_decision = None
        self.first_tacked = None

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
        cloned.first_decision = self.first_decision
        cloned.first_tacked = self.first_tacked
        return cloned


def score_state(state, finish_lat, finish_lng, alpha):
    dist_to_mark = haversine_m(state.boat.lat, state.boat.lng, finish_lat, finish_lng)
    return state.boat.total_distance + alpha * dist_to_mark, dist_to_mark


def beam_search_horizon(
    state,
    wind_dir,
    wind_speed,
    start_step,
    horizon,
    finish_lat,
    finish_lng,
    tackangle,
    alpha,
    beam_width,
    goal_dist,
    near_threshold,
    near_delay,
    far_delay,
):
    """
    Run beam search for a limited horizon to find the best first move.
    Returns the best first decision ("KEEP", "P", or "S") and whether a tack was made.
    """
    # Clone state but clear trajectory for simulation
    initial = state.clone()
    initial.trajectory = []  # Clear trajectory for this simulation
    initial.first_decision = None
    initial.first_tacked = None
    beam = [initial]
    finished = []
    best_finished = None
    max_step = min(start_step + horizon, len(wind_speed))

    for step in range(start_step, max_step):
        if not beam:
            break

        next_states = []
        for st in beam:
            st.step_count = step
            dist_to_mark = haversine_m(st.boat.lat, st.boat.lng, finish_lat, finish_lng)
            if dist_to_mark <= goal_dist:
                finished.append(st)
                if best_finished is None or st.boat.total_distance < best_finished.boat.total_distance:
                    best_finished = st
                continue

            update_tack_delay(st.boat, dist_to_mark, near_threshold, near_delay, far_delay)

            heading = bearing_deg(st.boat.lat, st.boat.lng, finish_lat, finish_lng)
            step_dist = wind_speed[step] / 2.2

            # Option A: keep tack
            keep_state = st.clone()
            move_by_wind_real(keep_state.boat, wind_dir[step], step_dist, heading, step, tackangle)
            keep_state.step_count = step + 1
            if st.first_decision is None:
                keep_state.first_decision = "KEEP"
                keep_state.first_tacked = False
            keep_state.trajectory.append((step, "KEEP", keep_state.boat.lat, keep_state.boat.lng))
            next_states.append(keep_state)

            # Option B: tack now (if allowed)
            if st.boat.can_tack(step):
                tack_state = st.clone()
                tack_state.boat.set_tack(step, -tack_state.boat.tack_index)
                tack_label = "P" if tack_state.boat.tack_index == 1 else "S"
                tack_state.tacks.append(f"{tack_label}{step}")
                move_by_wind_real(tack_state.boat, wind_dir[step], step_dist, heading, step, tackangle)
                tack_state.step_count = step + 1
                if st.first_decision is None:
                    tack_state.first_decision = tack_label
                    tack_state.first_tacked = True
                tack_state.trajectory.append((step, tack_label, tack_state.boat.lat, tack_state.boat.lng))
                next_states.append(tack_state)

        if not next_states:
            break

        # Prune to beam width by score.
        scored = []
        for st in next_states:
            score, _ = score_state(st, finish_lat, finish_lng, alpha)
            scored.append((score, st))
        scored.sort(key=lambda item: item[0])
        beam = [item[1] for item in scored[:beam_width]]

        if best_finished is not None:
            min_distance = min(st.boat.total_distance for st in beam)
            if min_distance >= best_finished.boat.total_distance:
                break

    # Find the best state (finished or from beam)
    if finished:
        finished.sort(key=lambda st: st.boat.total_distance)
        best = finished[0]
    elif beam:
        beam.sort(key=lambda st: score_state(st, finish_lat, finish_lng, alpha)[0])
        best = beam[0]
    else:
        return "KEEP", False

    return getattr(best, 'first_decision', "KEEP"), getattr(best, 'first_tacked', False)


def beam_search(
    wind_dir,
    wind_speed,
    start_lat,
    start_lng,
    finish_lat,
    finish_lng,
    tackangle=DEFAULT_TACKANGLE,
    horizon=60,
    goal_dist=20,
    alpha=0.0,
    beam_width=200,
    start_index=0,
    near_threshold=200,
    near_delay=10,
    far_delay=20,
):
    """
    MPC-style beam search: at each step, run beam search over horizon to decide,
    then execute one step and repeat until mark is reached.
    """
    state = BeamState(start_lat, start_lng)
    step_count = start_index

    while step_count < len(wind_speed):
        dist_to_mark = haversine_m(state.boat.lat, state.boat.lng, finish_lat, finish_lng)
        if dist_to_mark <= goal_dist:
            break

        update_tack_delay(state.boat, dist_to_mark, near_threshold, near_delay, far_delay)

        # Use beam search over horizon to decide best first move
        decision, should_tack = beam_search_horizon(
            state,
            wind_dir,
            wind_speed,
            step_count,
            horizon,
            finish_lat,
            finish_lng,
            tackangle,
            alpha,
            beam_width,
            goal_dist,
            near_threshold,
            near_delay,
            far_delay,
        )

        # Execute the decision
        if should_tack and state.boat.can_tack(step_count):
            state.boat.set_tack(step_count, -state.boat.tack_index)
            tack_label = "P" if state.boat.tack_index == 1 else "S"
            state.tacks.append(f"{tack_label}{step_count}")
            decision = tack_label
        else:
            decision = "KEEP"

        heading = bearing_deg(state.boat.lat, state.boat.lng, finish_lat, finish_lng)
        step_dist = wind_speed[step_count] / 2.2
        move_by_wind_real(state.boat, wind_dir[step_count], step_dist, heading, step_count, tackangle)
        state.trajectory.append((step_count, decision, state.boat.lat, state.boat.lng))
        state.step_count = step_count + 1
        step_count += 1

    return state


def main():
    parser = argparse.ArgumentParser(description="Beam search planner for WindGame.")
    parser.add_argument("--wind", default=os.path.join("winddata", "wind_data.json"))
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--start-lng", type=float, required=True)
    parser.add_argument("--finish-lat", type=float, required=True)
    parser.add_argument("--finish-lng", type=float, required=True)
    parser.add_argument("--horizon", type=int, default=60, help="Lookahead horizon for beam search (default: 60)")
    parser.add_argument("--tackangle", type=float, default=DEFAULT_TACKANGLE)
    parser.add_argument("--goal", type=float, default=20)
    parser.add_argument("--alpha", type=float, default=0.0)
    parser.add_argument("--beam-width", type=int, default=200)
    parser.add_argument("--start-index", type=int, default=0, help="Starting index in the wind data trace (default: 0)")
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
        start_index=args.start_index,
        near_threshold=args.near_threshold,
        near_delay=args.near_delay,
        far_delay=args.far_delay,
    )

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
