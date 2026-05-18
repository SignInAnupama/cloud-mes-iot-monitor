# Cloud MES IoT Monitor

Real-time machine monitoring dashboard built with AWS IoT Core, InfluxDB Cloud, and Grafana — demonstrating cloud MES patterns used by Siemens Opcenter, Rockwell Plex, and GE Digital.

---

## Live Demo
- **Grafana Dashboard:** [your-grafana-url-here]
- **Demo Video:** [your-loom-video-url-here]

---

## Architecture

```
┌─────────────────┐     MQTT/TLS      ┌──────────────────┐
│  Python Machine  │ ──────────────▶  │  AWS IoT Core    │
│  Simulator       │                  │  (us-east-2)     │
│  (3 machines)    │                  └────────┬─────────┘
└─────────────────┘                            │
                                               │ IoT Rule
                                    ┌──────────▼─────────┐
                                    │   AWS Lambda        │
                                    │   MesAlertHandler   │
                                    └──────────┬──────────┘
                                               │ SNS
                                    ┌──────────▼──────────┐
                                    │   Email Alert        │
                                    │   (unplanned         │
                                    │    downtime)         │
                                    └─────────────────────┘

┌─────────────────┐   HTTP/Write     ┌──────────────────┐
│  Python Machine  │ ──────────────▶ │  InfluxDB Cloud  │
│  Simulator       │                 │  (time-series DB) │
└─────────────────┘                  └────────┬─────────┘
                                              │ SQL query
                                   ┌──────────▼──────────┐
                                   │   Grafana Cloud      │
                                   │   Dashboard          │
                                   │   - Machine status   │
                                   │   - Cycle time trend │
                                   │   - Downtime pareto  │
                                   │   - Parts per shift  │
                                   └─────────────────────┘
```

---

## MES Domain Context

This project simulates a 3-machine production line using industry-standard downtime reason codes from the OEE (Overall Equipment Effectiveness) framework — the same framework used in Siemens Opcenter, SAP ME, and Rockwell Plex MES systems.

### Machines

| Machine | Type | Ideal Cycle | Scrap Rate |
|---------|------|-------------|------------|
| CNC-01 | CNC Machining Centre | 38 sec | 2% |
| WELD-02 | Robotic Welder | 95 sec | 4% |
| PRESS-03 | Hydraulic Press | 22 sec | 1% |

### Downtime Reason Codes

| Code | Type | Description |
|------|------|-------------|
| PLN-CHANGEOVER | Planned | Product changeover between work orders |
| PLN-BREAK | Planned | Operator break per shift schedule |
| PLN-MAINTENANCE | Planned | Scheduled preventive maintenance |
| UNP-BREAKDOWN | Unplanned | Mechanical failure — triggers immediate alert |
| UNP-MATERIAL | Unplanned | Material shortage or upstream starvation |
| UNP-QUALITY | Unplanned | Quality hold — production stopped for inspection |
| UNP-OPERATOR | Unplanned | No operator available |

Planned downtime is expected and scheduled. Unplanned downtime is the key metric plant managers focus on — every unplanned minute directly reduces OEE.

### Correlated Machine Starvation

On a real production line machines are linked — if CNC-01 stops, WELD-02 runs out of parts to weld after approximately 2 minutes. This is called downstream starvation and is modelled explicitly in this simulator:

```
CNC-01 (breakdown)
    ↓ after 2 minutes
WELD-02 (UNP-MATERIAL — starved)
    ↓ after 2 more minutes
PRESS-03 (UNP-MATERIAL — starved)
```

This cascading behaviour is why a single machine breakdown can halt an entire production line — and why rapid alert response is critical.

### OEE Calculation

OEE = Availability × Performance × Quality

- **Availability:** 1.0 if running, 0.0 if in any downtime state
- **Performance:** Ideal cycle time ÷ Actual cycle time
- **Quality:** 1 − scrap rate

World-class OEE is considered 85%+. This simulator targets realistic OEE of 88-94% during normal operation.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Message broker | AWS IoT Core | MQTT over TLS with x.509 cert auth |
| Simulator | Python + paho-mqtt | Realistic machine telemetry generation |
| Time-series DB | InfluxDB Cloud | Stores all machine telemetry |
| Alert function | AWS Lambda + SNS | Detects and emails unplanned downtime |
| Dashboard | Grafana Cloud | Live OEE and downtime visualisation |
| Hosting | AWS EC2 t2.micro | Runs simulator 24/7 |

---

## Project Structure

```
cloud-mes-iot-monitor/
├── simulator/
│   ├── certs/              # AWS IoT certificates (not committed to git)
│   ├── machine_sim.py      # Main simulator — 3 machines with OEE logic
│   └── config.py           # Endpoint, cert paths, InfluxDB config
├── lambda/
│   └── alert_handler.py    # Unplanned downtime alert function
├── grafana/
│   └── dashboard.json      # Exportable Grafana dashboard config
├── terraform/
│   └── main.tf             # Infrastructure as code (future)
├── .gitignore
└── README.md
```

---

## Setup Instructions

### Prerequisites
- Python 3.10+
- AWS account (free tier sufficient)
- InfluxDB Cloud account (free tier sufficient)
- Grafana Cloud account (free tier sufficient)

### 1. Clone the repo
```bash
git clone https://github.com/SignInAnupama/cloud-mes-iot-monitor
cd cloud-mes-iot-monitor
```

### 2. Install dependencies
```bash
pip install paho-mqtt influxdb-client
```

### 3. Add your certificates
Download your AWS IoT certificates and place them in `simulator/certs/`:
```
simulator/certs/
├── device-cert.pem.crt
├── private.pem.key
└── AmazonRootCA1.pem
```

### 4. Configure endpoints
Edit `simulator/config.py` with your actual values:
```python
ENDPOINT      = "your-endpoint.iot.us-east-2.amazonaws.com"
INFLUX_URL    = "https://us-east-1-1.aws.cloud2.influxdata.com"
INFLUX_TOKEN  = "your-token"
INFLUX_ORG    = "mes-monitor"
INFLUX_BUCKET = "machine_data"
```

### 5. Run the simulator
Normal mode:
```bash
cd simulator
python machine_sim.py
```

Breakdown scenario (for demo):
```bash
python machine_sim.py --scenario breakdown
```

### 6. Verify data
- AWS Console → IoT Core → MQTT test client → subscribe to `mes/machines/#`
- InfluxDB Cloud → Data Explorer → query `machine_telemetry`

---

## Key Learnings

- **MQTT over TLS with x.509 certificates** — the same authentication pattern used in real OT/IT integrations at Siemens and Rockwell plants
- **Time-series data modelling** — tagging vs fields in InfluxDB, retention policies, downsampling
- **Serverless alerting pipeline** — IoT rule → Lambda → SNS for real-time unplanned downtime notification
- **OEE domain knowledge applied to cloud** — realistic machine profiles, shift tracking, correlated starvation logic that generic cloud tutorials don't include

---

## What This Maps To In Industry

| This Project | Industry Equivalent |
|-------------|-------------------|
| Python simulator | PLC / SCADA system publishing to IoT gateway |
| AWS IoT Core | Siemens MindSphere / Rockwell FactoryTalk Cloud |
| InfluxDB | OSIsoft PI System / Azure Data Explorer |
| Lambda alerts | MES downtime notification engine |
| Grafana dashboard | Wonderware / FactoryTalk View / Opcenter dashboards |

---

## Author
Anupama — MES Engineer transitioning to Cloud MES
[LinkedIn](your-linkedin-url) | [GitHub](https://github.com/SignInAnupama)
