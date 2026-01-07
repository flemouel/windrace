#!/usr/bin/env python3
"""
Model Predictive Control (MPC) - receding-horizon planner for the WindGame

Goal: minimize total sailed distance while reaching the mark.
Approach: at each step, compare "tack now" vs "no tack", simulate a short
horizon with fixed tack, and pick the lower cost.
"""

import json
import math
import os
import argparse


EARTH_R = 6378137.0  # meters


def to_radians(deg):
    return deg * math.pi / 180.0


def to_degrees(rad):
    return rad * 180.0 / math.pi


def destination_point(lat, lng, bearing_deg, distance_m):
    """Return (lat, lng) after moving along bearing for distance."""
    lat1 = to_radians(lat)
    lng1 = to_radians(lng)
    bearing = to_radians(bearing_deg)
    dr = distance_m / EARTH_R

    lat2 = math.asin(
        math.sin(lat1) * math.cos(dr)
        + math.cos(lat1) * math.sin(dr) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(dr) * math.cos(lat1),
        math.cos(dr) - math.sin(lat1) * math.sin(lat2),
    )
    return to_degrees(lat2), to_degrees(lng2)


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in meters."""
    phi1 = to_radians(lat1)
    phi2 = to_radians(lat2)
    dphi = to_radians(lat2 - lat1)
    dlambda = to_radians(lng2 - lng1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
        dlambda / 2.0
    ) ** 2
    return 2.0 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def bearing_deg(lat1, lng1, lat2, lng2):
    """Initial bearing from point A to B."""
    phi1 = to_radians(lat1)
    phi2 = to_radians(lat2)
    dlambda = to_radians(lng2 - lng1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        dlambda
    )
    brng = to_degrees(math.atan2(y, x))
    return (brng + 360.0) % 360.0


def boat_step(lat, lng, wind_dir, step_dist, tack_index, tackangle):
    """
    Simple boat model: heading is wind_dir +/- tackangle.
    This is a draft and intentionally minimal.
    """
    boat_dir = wind_dir + (tack_index * tackangle)
    boat_dir = (boat_dir + 360.0) % 360.0
    return destination_point(lat, lng, boat_dir, step_dist)


def simulate_horizon(lat, lng, wind_dir, wind_speed, start_index, horizon, tack_index, tackangle):
    """Simulate a fixed tack for a short horizon and return (cost, end_lat, end_lng)."""
    traveled = 0.0
    t = start_index
    lat_i, lng_i = lat, lng
    for _ in range(horizon):
        if t >= len(wind_speed):
            break
        step_dist = wind_speed[t] / 2.2
        lat_i, lng_i = boat_step(lat_i, lng_i, wind_dir[t], step_dist, tack_index, tackangle)
        traveled += step_dist
        t += 1
    return traveled, lat_i, lng_i


def mpc_plan(wind_dir, wind_speed, start_lat, start_lng, finish_lat, finish_lng, tackangle=43,
             horizon=60, goal_dist=20, max_steps=None, alpha=1.0):
    """
    Run a MPC loop.

    alpha weights remaining distance in the horizon cost:
      cost = traveled + alpha * distance_to_mark
    """
    tacks_log = []
    lat, lng = start_lat, start_lng
    tack_index = -1  # start on starboard by default
    step_count = 0
    total_sailed = 0.0
    max_steps = max_steps or len(wind_speed)

    while step_count < max_steps:
        dist_to_mark = haversine_m(lat, lng, finish_lat, finish_lng)
        if dist_to_mark <= goal_dist:
            break

        # Option A: keep tack
        travel_a, lat_a, lng_a = simulate_horizon(
            lat, lng, wind_dir, wind_speed, step_count, horizon, tack_index, tackangle
        )
        cost_a = travel_a + alpha * haversine_m(lat_a, lng_a, finish_lat, finish_lng)

        # Option B: tack now
        tack_b = -tack_index
        travel_b, lat_b, lng_b = simulate_horizon(
            lat, lng, wind_dir, wind_speed, step_count, horizon, tack_b, tackangle
        )
        cost_b = travel_b + alpha * haversine_m(lat_b, lng_b, finish_lat, finish_lng)

        if cost_b < cost_a:
            tack_index = tack_b
            tack_label = "P" if tack_index == 1 else "S"
            tacks_log.append(f"{tack_label}{step_count}")

        # Execute 1-step move with chosen tack
        step_dist = wind_speed[step_count] / 2.2
        lat, lng = boat_step(lat, lng, wind_dir[step_count], step_dist, tack_index, tackangle)
        total_sailed += step_dist
        step_count += 1

    return {
        "steps": step_count,
        "tacks": tacks_log,
        "end_lat": lat,
        "end_lng": lng,
        "distance_to_mark": haversine_m(lat, lng, finish_lat, finish_lng),
        "total_sailed": total_sailed,
    }


def load_wind_data(path):
    with open(path, "r") as f:
        data = json.load(f)
    return data["direction"], data["speed"]


def main():
    parser = argparse.ArgumentParser(description="Draft MPC planner for WindGame.")
    parser.add_argument("--wind", default=os.path.join("winddata", "wind_data.json"))
    parser.add_argument("--start-lat", type=float, required=True)
    parser.add_argument("--start-lng", type=float, required=True)
    parser.add_argument("--finish-lat", type=float, required=True)
    parser.add_argument("--finish-lng", type=float, required=True)
    parser.add_argument("--horizon", type=int, default=60)
    parser.add_argument("--tackangle", type=float, default=43)
    parser.add_argument("--goal", type=float, default=20)
    parser.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()

    wind_dir, wind_speed = load_wind_data(args.wind)
    result = mpc_plan(
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
    )
    print("steps:", result["steps"])
    print("distance_to_mark:", round(result["distance_to_mark"], 2), "m")
    print("total_sailed:", round(result["total_sailed"], 2), "m")
    print("tacks:", result["tacks"][:10], "... total", len(result["tacks"]), "tack decisions")


if __name__ == "__main__":
    main()
