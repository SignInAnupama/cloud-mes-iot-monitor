# simulator/machine_sim.py
# ─────────────────────────────────────────────
# Simulates 3 machines publishing MQTT telemetry to AWS IoT Core.
# Machine profiles mirror real MES data: downtime codes, cycle times,
# scrap rates, shift tracking, and correlated downtime between machines.
# ─────────────────────────────────────────────

import paho.mqtt.client as mqtt
import json, time, random, ssl, argparse
from datetime import datetime, timezone
from config import (
    ENDPOINT, PORT, CERT_PATH, KEY_PATH,
    CA_PATH, CLIENT_ID, TOPIC, PUBLISH_INTERVAL_SEC
)
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET

# InfluxDB client
influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx.write_api(write_options=SYNCHRONOUS)

# ── Machine profiles ──────────────────────────────────────────────────────────
# Each machine has its own cycle time, scrap rate, and failure tendency.
# These mirror real differences you'd see between machine types on a shop floor.

MACHINES = {
    "CNC-01": {
        "type":         "CNC Machining Centre",
        "ideal_cycle":  38,       # seconds per part
        "cycle_stddev": 2,        # natural variation
        "scrap_rate":   0.02,     # 2% scrap - tight tolerances
        "failure_rate": 0.003,    # low - well maintained
        "warmup_time":  0,        # no warmup needed
    },
    "WELD-02": {
        "type":         "Robotic Welder",
        "ideal_cycle":  95,       # slower - complex weld paths
        "cycle_stddev": 8,
        "scrap_rate":   0.04,     # higher scrap - weld quality variation
        "failure_rate": 0.005,
        "warmup_time":  300,      # 5 min warmup at shift start
    },
    "PRESS-03": {
        "type":         "Hydraulic Press",
        "ideal_cycle":  22,       # fastest machine
        "cycle_stddev": 1,
        "scrap_rate":   0.01,
        "failure_rate": 0.008,    # highest failure - hydraulic issues
        "warmup_time":  0,
    },
}

# ── Downtime reason codes ─────────────────────────────────────────────────────
# PLN = planned (expected, scheduled)
# UNP = unplanned (unexpected, needs investigation)
# These are standard codes used in most MES systems (Siemens, Rockwell, SAP)

DOWNTIME_CODES = {
    "PLN-CHANGEOVER":   "Planned: product changeover",
    "PLN-MAINTENANCE":  "Planned: scheduled maintenance",
    "PLN-BREAK":        "Planned: operator break",
    "UNP-BREAKDOWN":    "Unplanned: mechanical breakdown",
    "UNP-MATERIAL":     "Unplanned: material shortage",
    "UNP-QUALITY":      "Unplanned: quality hold",
    "UNP-OPERATOR":     "Unplanned: no operator",
}

# ── Machine state tracker ─────────────────────────────────────────────────────
# Tracks each machine's current status and how long it has been in that state.
# This is how we simulate correlated downtime between machines.

machine_state = {
    mid: {
        "status":       "RUNNING",
        "status_since": time.time(),
        "parts_today":  0,
        "scrap_today":  0,
        "starved":      False,    # True when upstream machine is down
    }
    for mid in MACHINES
}

# ── Correlated downtime logic ─────────────────────────────────────────────────
# On a real production line, machines are linked.
# If CNC-01 (Machine 1) goes down, WELD-02 (Machine 2) runs out of
# parts to weld after ~2 minutes — this is called "starvation".

UPSTREAM = {
    "WELD-02":  "CNC-01",    # Welder is fed by CNC
    "PRESS-03": "WELD-02",   # Press is fed by Welder
}
STARVATION_DELAY_SEC = 120   # 2 minutes before downstream starves

def update_starvation():
    """If an upstream machine is down, starve the downstream after 2 min."""
    for downstream, upstream in UPSTREAM.items():
        up_state   = machine_state[upstream]
        down_state = machine_state[downstream]

        upstream_down = up_state["status"] != "RUNNING"
        down_time     = time.time() - up_state["status_since"]

        if upstream_down and down_time > STARVATION_DELAY_SEC:
            if not down_state["starved"]:
                print(f"  ⚠ {downstream} starved — {upstream} has been down {int(down_time/60)} min")
            down_state["starved"] = True
        else:
            down_state["starved"] = False

# ── Scenario: forced breakdown ────────────────────────────────────────────────
# Run with --scenario breakdown to force CNC-01 into unplanned downtime.
# Useful for demonstrating the alert pipeline in a live demo.

def apply_scenario(scenario):
    if scenario == "breakdown":
        print("\n🔴 SCENARIO: Forcing CNC-01 into UNP-BREAKDOWN")
        machine_state["CNC-01"]["status"]       = "UNP-BREAKDOWN"
        machine_state["CNC-01"]["status_since"] = time.time()

# ── Payload generator ─────────────────────────────────────────────────────────

def get_shift():
    hour = datetime.now().hour
    if   6  <= hour < 14: return "Day"
    elif 14 <= hour < 22: return "Afternoon"
    else:                  return "Night"

def generate_payload(machine_id):
    cfg   = MACHINES[machine_id]
    state = machine_state[machine_id]

    # Randomly transition into downtime
    if state["status"] == "RUNNING":
        if random.random() < cfg["failure_rate"]:
            code = random.choice(["UNP-BREAKDOWN","UNP-MATERIAL","UNP-QUALITY","UNP-OPERATOR"])
            state["status"]       = code
            state["status_since"] = time.time()
            print(f"  ⚠ {machine_id} → {code}")
        elif random.random() < 0.002:
            code = random.choice(["PLN-CHANGEOVER","PLN-BREAK"])
            state["status"]       = code
            state["status_since"] = time.time()
            print(f"  📋 {machine_id} → {code}")

    # Randomly recover from downtime (avg 8 minutes down)
    elif state["status"] != "RUNNING":
        down_seconds = time.time() - state["status_since"]
        recovery_chance = min(0.02, down_seconds / 2400)
        if random.random() < recovery_chance:
            print(f"  ✅ {machine_id} → RUNNING (was down {int(down_seconds/60)} min)")
            state["status"]       = "RUNNING"
            state["status_since"] = time.time()

    # Apply starvation from upstream
    status = state["status"]
    if state["starved"] and status == "RUNNING":
        status = "UNP-MATERIAL"   # starved = no material from upstream

    running = status == "RUNNING"

    # Calculate cycle time with natural variation
    if running:
        cycle = round(random.gauss(cfg["ideal_cycle"], cfg["cycle_stddev"]), 1)
        cycle = max(cycle, cfg["ideal_cycle"] * 0.8)   # never unrealistically fast
    else:
        cycle = 0

    # Parts and scrap
    produced = 1 if running else 0
    scrap    = 1 if running and random.random() < cfg["scrap_rate"] else 0
    if produced: state["parts_today"] += produced
    if scrap:    state["scrap_today"] += scrap

    # OEE components (simplified)
    availability = 1.0 if running else 0.0
    performance  = round(cfg["ideal_cycle"] / cycle, 3) if cycle > 0 else 0.0
    quality      = round(1 - cfg["scrap_rate"], 3)
    oee          = round(availability * performance * quality * 100, 1)

    return {
        "machine_id":     machine_id,
        "machine_type":   cfg["type"],
        "timestamp":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "shift":          get_shift(),
        "status":         status,
        "cycle_time_sec": cycle,
        "ideal_cycle_sec":cfg["ideal_cycle"],
        "temperature_c":  round(random.gauss(75, 4), 1),
        "parts_produced": produced,
        "scrap_count":    scrap,
        "parts_today":    state["parts_today"],
        "scrap_today":    state["scrap_today"],
        "oee_pct":        oee,
        "downtime_reason":DOWNTIME_CODES.get(status, "Running normally"),
    }

# ── MQTT setup ────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    codes = {
        0: "Connected successfully",
        1: "Bad protocol version",
        2: "Client ID rejected",
        3: "Server unavailable",
        4: "Bad credentials",
        5: "Not authorized",
    }
    print(f"\n{'✅' if rc==0 else '❌'} MQTT: {codes.get(rc, f'Unknown code {rc}')}")

def on_publish(client, userdata, mid):
    pass   # suppress per-message noise; we print in the main loop

def build_client():
    client = mqtt.Client(client_id=CLIENT_ID, protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_publish = on_publish

    # TLS with x.509 certificates - same auth used in real OT/IT integrations
    client.tls_set(
        ca_certs    = CA_PATH,
        certfile    = CERT_PATH,
        keyfile     = KEY_PATH,
        tls_version = ssl.PROTOCOL_TLSv1_2
    )
    return client

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MES IoT machine simulator")
    parser.add_argument("--scenario", choices=["breakdown","normal"], default="normal",
                        help="breakdown: force CNC-01 into unplanned downtime")
    args = parser.parse_args()

    print("=" * 55)
    print("  MES IoT Machine Simulator")
    print(f"  Endpoint : {ENDPOINT}")
    print(f"  Machines : {', '.join(MACHINES.keys())}")
    print(f"  Interval : every {PUBLISH_INTERVAL_SEC}s")
    print(f"  Scenario : {args.scenario}")
    print("=" * 55)

    client = build_client()
    print(f"\nConnecting to {ENDPOINT}:{PORT} ...")
    client.connect(ENDPOINT, PORT, keepalive=60)
    client.loop_start()
    time.sleep(2)   # wait for connection

    if args.scenario == "breakdown":
        apply_scenario("breakdown")

    try:
        while True:
            update_starvation()
            for machine_id in MACHINES:
                payload = generate_payload(machine_id)
                topic   = f"{TOPIC}/{machine_id}"
                client.publish(topic, json.dumps(payload), qos=1)
                status_icon = "🟢" if payload["status"] == "RUNNING" else "🔴"
                print(f"  {status_icon} {machine_id} | {payload['status']:<20} | "
                      f"cycle={payload['cycle_time_sec']:5.1f}s | "
                      f"OEE={payload['oee_pct']:5.1f}% | "
                      f"parts={payload['parts_today']}")
            print()
            time.sleep(PUBLISH_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\nStopping simulator...")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
