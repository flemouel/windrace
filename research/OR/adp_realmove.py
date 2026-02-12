#!/usr/bin/env python3
"""
Approximate Dynamic Programming (ADP) planner using game-like movement.

This is a light-weight ADP baseline:
- Two actions: KEEP tack vs TACK now (if allowed).
- One-step horizon cost + value-function estimate of next state.
- Online TD(0) update of a linear value function.

The move model mirrors the game's moveByWind behavior:
- tack angle applied to wind direction
- layline clamping vs bearing to mark
- tack cooldown (delay)
- 10-second speed reduction after a tack
"""
import argparse
import os
import random
import math
from dataclasses import dataclass

from mpc_simplemove import (
    bearing_deg,
    destination_point,
    haversine_m,
    load_wind_data,
)


DEFAULT_TACKANGLE = 43.0


@dataclass
class BoatState:
    lat: float
    lng: float
    tack_index: int = -1
    tack_time: int = 0
    tack_delay: int = 20
    total_distance: float = 0.0

    def can_tack(self, step_index):
        return (step_index - self.tack_time) > self.tack_delay

    def set_tack(self, step_index, tack_index):
        self.tack_index = tack_index
        self.tack_time = step_index


def clamp_heading_by_layline(wind_dir, heading_to_mark, tack_index, tackangle):
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
    sim = BoatState(state.lat, state.lng, state.tack_index, state.tack_time, state.tack_delay)
    sim.target_lat = state.target_lat
    sim.target_lng = state.target_lng
    traveled = 0.0
    t = start_index
    for _ in range(horizon):
        if t >= len(wind_speed):
            break
        dist_to_mark = haversine_m(sim.lat, sim.lng, sim.target_lat, sim.target_lng)
        update_tack_delay(sim, dist_to_mark, near_threshold, near_delay, far_delay)
        heading = bearing_deg(sim.lat, sim.lng, sim.target_lat, sim.target_lng)
        step_dist = wind_speed[t] / 2.2
        traveled += move_by_wind_real(sim, wind_dir[t], step_dist, heading, t, tackangle)
        t += 1
    return traveled, sim.lat, sim.lng


def features(lat, lng, target_lat, target_lng, boat_heading, wind_dir, tack_index, approx, normalize):
    dist = haversine_m(lat, lng, target_lat, target_lng) / 1000.0
    bearing = bearing_deg(lat, lng, target_lat, target_lng)
    diff = abs((bearing - boat_heading + 180) % 360 - 180)
    wind_angle = abs((wind_dir - boat_heading + 180) % 360 - 180)
    tack_side = 1.0 if tack_index >= 0 else -1.0
    if normalize:
        diff /= 180.0
        wind_angle /= 180.0
    feats = [1.0, dist, diff, wind_angle, tack_side]
    if approx == "poly":
        feats.extend([
            dist * dist,
            diff * diff,
            wind_angle * wind_angle,
            dist * diff,
        ])
    return feats


def value_linear(weights, feats):
    return sum(w * f for w, f in zip(weights, feats))


def update_linear(weights, feats, td_error, lr, l2):
    for i in range(len(weights)):
        weights[i] += lr * (td_error * feats[i] - l2 * weights[i])


def init_network(input_dim, hidden_size):
    # Small random init
    w1 = [[random.uniform(-0.01, 0.01) for _ in range(input_dim)] for _ in range(hidden_size)]
    b1 = [0.0 for _ in range(hidden_size)]
    w2 = [random.uniform(-0.01, 0.01) for _ in range(hidden_size)]
    b2 = 0.0
    return {"w1": w1, "b1": b1, "w2": w2, "b2": b2}


def forward_network(params, feats):
    w1 = params["w1"]
    b1 = params["b1"]
    w2 = params["w2"]
    b2 = params["b2"]
    hidden = []
    for i, row in enumerate(w1):
        s = b1[i]
        for j, w in enumerate(row):
            s += w * feats[j]
        # tanh activation
        hidden.append(math.tanh(s))
    out = b2
    for i, h in enumerate(hidden):
        out += w2[i] * h
    return out, hidden


def update_network(params, feats, td_error, lr, l2, hidden):
    w1 = params["w1"]
    b1 = params["b1"]
    w2 = params["w2"]
    b2 = params["b2"]
    # Output layer gradients
    for i in range(len(w2)):
        w2[i] += lr * (td_error * hidden[i] - l2 * w2[i])
    b2 += lr * td_error
    # Hidden layer gradients
    for i in range(len(w1)):
        dh = td_error * w2[i] * (1.0 - hidden[i] * hidden[i])
        b1[i] += lr * dh
        row = w1[i]
        for j in range(len(row)):
            row[j] += lr * (dh * feats[j] - l2 * row[j])
    params["b2"] = b2


def adp_plan_real(
    wind_dir,
    wind_speed,
    start_lat,
    start_lng,
    finish_lat,
    finish_lng,
    tackangle=DEFAULT_TACKANGLE,
    goal_dist=20,
    alpha=1.0,
    start_index=0,
    near_threshold=200,
    near_delay=10,
    far_delay=20,
    goal_penalty=10.0,
    gamma=0.95,
    lr=0.01,
    horizon=10,
    epsilon=0.0,
    approx="linear",
    l2=0.0,
    hidden_size=8,
    epsilon_decay=1.0,
    epsilon_min=0.0,
    normalize_features=False,
):
    tacks_log = []
    state = BoatState(start_lat, start_lng)
    state.target_lat = finish_lat
    state.target_lng = finish_lng
    step_count = start_index
    trajectory = []

    # Simple linear value function weights.
    feats0 = features(
        start_lat, start_lng, finish_lat, finish_lng,
        bearing_deg(start_lat, start_lng, finish_lat, finish_lng),
        wind_dir[start_index] if start_index < len(wind_dir) else 0.0,
        state.tack_index,
        approx,
        normalize_features,
    )
    weights = [0.0 for _ in range(len(feats0))]
    if approx == "network":
        net_params = init_network(len(feats0), hidden_size)
    else:
        net_params = None

    while step_count < len(wind_speed):
        dist_to_mark = haversine_m(state.lat, state.lng, finish_lat, finish_lng)
        if dist_to_mark <= goal_dist:
            break

        update_tack_delay(state, dist_to_mark, near_threshold, near_delay, far_delay)
        heading = bearing_deg(state.lat, state.lng, finish_lat, finish_lng)
        step_dist = wind_speed[step_count] / 2.2

        # Evaluate KEEP with mini-horizon
        keep_state = BoatState(state.lat, state.lng, state.tack_index, state.tack_time, state.tack_delay)
        keep_state.target_lat = finish_lat
        keep_state.target_lng = finish_lng
        travel_a, lat_a, lng_a = simulate_horizon_real(
            keep_state, wind_dir, wind_speed, step_count, horizon, tackangle,
            near_threshold=near_threshold, near_delay=near_delay, far_delay=far_delay
        )
        keep_cost = travel_a + (alpha * goal_penalty) * haversine_m(lat_a, lng_a, finish_lat, finish_lng)
        keep_feats = features(
            lat_a, lng_a, finish_lat, finish_lng, heading, wind_dir[step_count], state.tack_index, approx,
            normalize_features
        )
        if approx == "network":
            keep_v, _ = forward_network(net_params, keep_feats)
        else:
            keep_v = value_linear(weights, keep_feats)

        # Evaluate TACK (if allowed)
        tack_cost = float("inf")
        tack_v = float("inf")
        if state.can_tack(step_count):
            tack_state = BoatState(state.lat, state.lng, -state.tack_index, step_count, state.tack_delay)
            tack_state.target_lat = finish_lat
            tack_state.target_lng = finish_lng
            travel_b, lat_b, lng_b = simulate_horizon_real(
                tack_state, wind_dir, wind_speed, step_count, horizon, tackangle,
                near_threshold=near_threshold, near_delay=near_delay, far_delay=far_delay
            )
            tack_cost = travel_b + (alpha * goal_penalty) * haversine_m(lat_b, lng_b, finish_lat, finish_lng)
            tack_feats = features(
                lat_b, lng_b, finish_lat, finish_lng, heading, wind_dir[step_count], -state.tack_index, approx,
                normalize_features
            )
            if approx == "network":
                tack_v, _ = forward_network(net_params, tack_feats)
            else:
                tack_v = value_linear(weights, tack_feats)

        # Choose action by 1-step horizon + value estimate
        keep_score = keep_cost + gamma * keep_v
        tack_score = tack_cost + gamma * tack_v

        decision = "KEEP"
        next_state = keep_state
        if tack_score < keep_score:
            state.set_tack(step_count, -state.tack_index)
            tack_label = "P" if state.tack_index == 1 else "S"
            tacks_log.append(f"{tack_label}{step_count}")
            decision = tack_label
            next_state = tack_state
        if epsilon > 0.0 and random.random() < epsilon:
            if state.can_tack(step_count):
                if random.random() < 0.5:
                    state.set_tack(step_count, -state.tack_index)
                    tack_label = "P" if state.tack_index == 1 else "S"
                    tacks_log.append(f"{tack_label}{step_count}")
                    decision = tack_label
                    next_state = tack_state
                else:
                    decision = "KEEP"
                    next_state = keep_state

        # Decay epsilon after each step.
        if epsilon_decay < 1.0:
            epsilon = max(epsilon_min, epsilon * epsilon_decay)

        # TD(0) update on current state (1-step move as observed)
        feats_now = features(
            state.lat, state.lng, finish_lat, finish_lng, heading, wind_dir[step_count], state.tack_index, approx,
            normalize_features
        )
        if approx == "network":
            v_now, hidden_now = forward_network(net_params, feats_now)
        else:
            v_now = value_linear(weights, feats_now)
        next_feats = features(
            next_state.lat, next_state.lng, finish_lat, finish_lng, heading,
            wind_dir[step_count], next_state.tack_index, approx, normalize_features
        )
        if approx == "network":
            next_v, _ = forward_network(net_params, next_feats)
        else:
            next_v = value_linear(weights, next_feats)
        target = step_dist + (alpha * goal_penalty) * haversine_m(
            next_state.lat, next_state.lng, finish_lat, finish_lng
        ) + gamma * next_v
        td_error = target - v_now
        if approx == "network":
            update_network(net_params, feats_now, td_error, lr, l2, hidden_now)
        else:
            update_linear(weights, feats_now, td_error, lr, l2)

        # Apply chosen move to real state
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
    parser = argparse.ArgumentParser(description="ADP planner with game-like movement.")
    parser.add_argument("--wind", default=os.path.join("winddata", "wind_data.json"))
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--start-lng", type=float, required=True)
    parser.add_argument("--finish-lat", type=float, required=True)
    parser.add_argument("--finish-lng", type=float, required=True)
    parser.add_argument("--tackangle", type=float, default=DEFAULT_TACKANGLE)
    parser.add_argument("--goal", type=float, default=20)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--near-threshold", type=float, default=200)
    parser.add_argument("--near-delay", type=int, default=10)
    parser.add_argument("--far-delay", type=int, default=20)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--goal-penalty", type=float, default=10.0)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--horizon", type=int, default=90)
    parser.add_argument("--epsilon", type=float, default=0.0)
    parser.add_argument("--approx", type=str, default="linear", choices=["linear", "poly", "network"])
    parser.add_argument("--l2", type=float, default=0.0)
    parser.add_argument("--hidden-size", type=int, default=8)
    parser.add_argument("--epsilon-decay", type=float, default=1.0)
    parser.add_argument("--epsilon-min", type=float, default=0.0)
    parser.add_argument("--normalize-features", action="store_true")
    parser.add_argument("--verbose", type=int, default=1)
    args = parser.parse_args()

    wind_dir, wind_speed = load_wind_data(args.wind)
    result = adp_plan_real(
        wind_dir,
        wind_speed,
        args.start_lat,
        args.start_lng,
        args.finish_lat,
        args.finish_lng,
        tackangle=args.tackangle,
        goal_dist=args.goal,
        alpha=args.alpha,
        start_index=args.start_index,
        near_threshold=args.near_threshold,
        near_delay=args.near_delay,
        far_delay=args.far_delay,
        goal_penalty=args.goal_penalty,
        gamma=args.gamma,
        lr=args.lr,
        horizon=args.horizon,
        epsilon=args.epsilon,
        approx=args.approx,
        l2=args.l2,
        hidden_size=args.hidden_size,
        epsilon_decay=args.epsilon_decay,
        epsilon_min=args.epsilon_min,
        normalize_features=args.normalize_features,
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
