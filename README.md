# NODAL — Bengaluru Metro Intelligence

Graph-theory analysis, realistic interchange cost modeling, failure impact simulation, and **hypothetical recovery & expansion planning** for Namma Metro.

---

## Quick Start (How to Run)

### 1. Requirements
* **Python 3.10+**
* Web browser (Chrome, Edge, Firefox, Brave)
* Internet access is only required for background map tiles; all graph analytics, GTFS feeds, algorithms, and frontend assets run 100% locally.

### 2. Run the Application
Open a terminal (PowerShell, Command Prompt, or bash) in the project directory:

```bash
# Navigate to the backend directory
cd backend

# (Optional) Activate your virtual environment if you use one
# e.g.: .venv\Scripts\activate

# Install dependencies (only needed once)
pip install -r requirements.txt

# Start the NODAL server
python -m uvicorn app.main:app --port 8000
```

### 3. Open in Browser
Once running, open:
👉 **[http://localhost:8000](http://localhost:8000)**

---

## Testing What Happens When Majestic Shuts Down

1. **Open the Failure Simulator**:
   * Click **⚠ Failure Simulator** in the left navigation sidebar.
2. **Disable Majestic**:
   * Search or select **Nadaprabhu Kempegowda Station, Majestic** (or click it on the map/graph).
   * Click **Simulate Failure**.
3. **What You Immediately See**:
   * **Severed Connections**: All 4 tracks connecting Majestic to Sampige Road, Mantri Square, Sir M. Visveshwaraya, and City Railway Station cut.
   * **Disconnected Network Components**: Network splits into isolated components (Purple Line East, Purple Line West, Green Line North, Green Line South).
   * **Travel Time Impact**: Average pairwise journey times across the network before vs. after.
   * **Alternative Connection Load**: Top surviving connections that receive redirected passenger load based on betweenness centrality.
4. **Test Network Recovery**:
   * In the **Network Recovery Simulator** panel at the bottom of the failure results:
   * Select an Origin (e.g., Srirampura or Mantri Square) and Destination (e.g., MG Road or Chickpet).
   * Choose Route Type (**Bus Route** or **Metro Extension**) and enter travel time.
   * Click **Add Connection** &rarr; **Calculate Recovery** to see how many components reconnect and what percentage of network travel time is recovered.

---

## Testing Realistic Interchange Times

1. Click **⇄ Interchange Lab** in the left navigation sidebar.
2. View real platform walking times, escalator traversal, and train wait times parsed directly from BMRCL GTFS `pathways.txt` and `transfers.txt`.
3. Compare **Naive (Instant)** vs **Realistic (GTFS)** route times for journeys passing through Majestic or other interchange stations.

---

## Running Unit Tests

To run the automated algorithm and graph-theory test suite:

```bash
cd backend
python -m pytest tests/test_nodal.py
```
