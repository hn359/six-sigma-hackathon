# Ithaca Bikeshare Fleet Simulator & Six Sigma DMAIC Engine

A high-fidelity, stateful Monte Carlo telemetry generator and real-time Statistical Process Control (SPC) engine designed for municipal bikeshare operations and Six Sigma process control.

The simulator models an Ithaca bikeshare network facing a "docks full / docks empty" crisis during commuter rush hours, providing realistic data for transport engineers, dashboard visualizations, statistical process control (SPC), and DMAIC optimization.

---

## Network Architecture & Specifications

- **City:** Ithaca, NY
- **Stations (5 named stations):**
  - **Lansing (Residential):** Residential zone; heavy morning outflow (6:00 – 10:00 AM). Legacy alias `A`.
  - **Maplewood (Residential):** Residential zone; heavy morning outflow (6:00 – 10:00 AM). Legacy alias `B`.
  - **Downtown (Commons / Transfer):** Mixed downtown transit hub; balanced midday and transfer demand. Legacy alias `C`.
  - **Central Campus (Employment):** Core working district; heavy evening return outflow (4:00 – 7:30 PM). Legacy alias `D`.
  - **North Campus (Employment):** Campus working district; heavy evening return outflow (4:00 – 7:30 PM). Legacy alias `E`.
- **Station Capacity:** Maximum 20 docks per station.
- **Initial Fleet (Monday 00:00):**
  - Exactly **10 bikes** at each of the 5 stations (50 bikes total).
  - Exactly **50 bikes** in central inventory / reserve depot.
  - Total Fleet: **100 bikes** strictly conserved across stations, reserve, and bikes in transit.
- **Process Control Limits:** Upper Control Limit ($\text{UCL}$) = **18**, Lower Control Limit ($\text{LCL}$) = **2**, Target = **10**.
- **Common vs. Special Cause Variation:**
  - *Common Cause* ($2 < \text{bikes} < 18$): Minor natural fluctuations self-correct over time.
  - *Special Cause* ($\le 2$ or $\ge 18$): Stations lock into a deficit/surplus crisis and **cannot self-correct** without an operator maintenance van dispatch remedy. The simulator continues running in real time while biasing the defective station until remedied.
- **Temporal Resolution:** 15 simulation minutes per tick.
- **Nighttime Quiescence:** After 10:00 PM (22:00) until 05:30 AM, trip activity drops to near zero, maintaining subtle natural variations without commuter fluctuations.
- **Proportional Overnight Rebalance:** Every night at midnight after Monday, the 50 station bikes are redistributed across stations strictly proportional to the previous day's time-averaged occupancy.

---

## Six Sigma (DMAIC) & Process Control Analytics

The simulator includes a built-in SPC engine ([`spc_analytics.py`](file:///c:/Users/sab484/Downloads/bikeshare-simulator/bikeshare-simulator/simulator/spc_analytics.py)):

- **Variable Control Charts (I-MR):**
  - **Individual Values ($X$):** Raw bike counts with 5-point moving average trendlines.
  - **Moving Range ($MR$):** $MR_t = |X_t - X_{t-1}|$ volatility with $\text{UCL}_{MR} = 3.267 \overline{MR}$.
  - **Nelson Rules:** Evaluates Rule 1 (beyond $\pm 3\sigma$), Rule 2 (9-point run shift), and Rule 3 (6-point trend).
- **Attribute Control Charts (Fraction Defective $p$-Chart & $np$-Chart):**
  - Based on Cornell SYSEN 5300 Lesson 5 (Slides 25 & 41–46).
  - Evaluates network-wide unserviceability proportion $p_t = \frac{\text{unusable stations}}{5}$ at each 15-minute interval under binomial distribution assumptions:
    $$\bar{p} = \frac{\text{Total Defective Station Ticks}}{\text{Total Station Audits}}$$
    $$\text{UCL}_p = \bar{p} + 3\sqrt{\frac{\bar{p}(1-\bar{p})}{n}}$$
    $$\text{LCL}_p = \max\left(0, \bar{p} - 3\sqrt{\frac{\bar{p}(1-\bar{p})}{n}}\right)$$
- **DMAIC 5-Phase Reporting:** Full Define, Measure, Analyze, Improve, Control structured output with Pareto defect ranking and capability metrics ($C_p$, $C_{pk}$, $C_{pm}$, Sigma Level, DPMO, Availability %).

---

## Quick Start & Usage

### 1. Run a 24-Hour or 7-Day Simulation

```bash
# 24-Hour simulation (96 ticks) with reproducible seed:
python -m simulator.bikeshare_simulator --ticks 96 --seed 42 --csv one_day.csv

# 7-Day full week simulation (672 ticks):
python -m simulator.bikeshare_simulator --ticks 672 --csv seven_days.csv
```

### 2. Run Continuously in Real Time

```bash
# Generates 1 tick (15 simulated minutes) every 10 wall-clock seconds:
python -m simulator.bikeshare_simulator --realtime --wall-seconds 10.0
```

### 3. Run the REST, SSE & 3D Web Dashboard

```bash
# Install dependencies:
pip install -r requirements.txt

# Start the web service:
python -m simulator.bikeshare_simulator --api --port 8000
```
Open [http://localhost:8000/dashboard](http://localhost:8000/dashboard) to view the 3D Google Maps interactive interface with live control charts.

---

## Validation & Test Suite

Run the unit test suite:
```bash
python -m unittest discover -s tests -v
```

