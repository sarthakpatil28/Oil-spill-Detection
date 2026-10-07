import { useEffect, useState } from "react";

import {
  Activity,
  AlertTriangle,
  Bell,
  ShieldCheck,
  Waves,
} from "lucide-react";

import VesselLeaderboard from "../components/VesselLeaderboard";
import IncidentMap from "../components/IncidentMap";
import AnomalyPanel from "../components/AnomalyPanel";

function CommandCenter() {
  const [alertStatus, setAlertStatus] = useState("READY");
const [alertLoading, setAlertLoading] = useState(false);
  const [driftData, setDriftData] = useState(null);
  const [driftLoading, setDriftLoading] = useState(true);

  useEffect(() => {
    async function loadDrift() {
      try {
        const response = await fetch("http://127.0.0.1:8000/api/drift", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        });

        if (!response.ok) {
          throw new Error("Drift API request failed");
        }

        const data = await response.json();
        setDriftData(data);
      } catch (error) {
        console.error("Drift API error:", error);
      } finally {
        setDriftLoading(false);
      }
    }

    loadDrift();
  }, []);



const dispatchAlert = async () => {
  try {
    setAlertLoading(true);
    setAlertStatus("DISPATCHING...");

    const response = await fetch(
      "http://127.0.0.1:8000/api/alert",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          incident: "Arabian Sea Oil Spill",
          priority: "HIGH",
          vessel: "VANGUARD",
          score: 95.3,
        }),
      }
    );

    if (!response.ok) {
      throw new Error("Alert dispatch failed");
    }

    const result = await response.json();

    if (result.status === "success") {
      setAlertStatus("ALERT SENT");
    }
  } catch (error) {
    console.error("Alert dispatch error:", error);
    setAlertStatus("DISPATCH FAILED");
  } finally {
    setAlertLoading(false);
  }
};



  const trajectory = driftData?.data?.trajectory || [];

  return (
    <div className="command-center">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <Waves size={24} />
          </div>

          <div>
            <h1>OCEAN SENTINEL</h1>
            <span>MARITIME OIL SPILL INTELLIGENCE</span>
          </div>
        </div>

        <div className="system-status">
          <span className="status-dot" />
          SYSTEM OPERATIONAL
        </div>
      </header>

      <main className="dashboard">

        <section className="hero-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">LIVE INCIDENT MONITOR</span>
              <h2>Arabian Sea Surveillance</h2>
            </div>

            <div className="incident-status">
              <AlertTriangle size={16} />
              ACTIVE INCIDENT
            </div>
          </div>

          <IncidentMap trajectory={trajectory} />
        </section>

        <aside className="intelligence-panel">
          <div className="panel-title">
            <ShieldCheck size={18} />
            INCIDENT INTELLIGENCE
          </div>

          <div className="metric">
            <span>SPILL AREA</span>
            <strong>12.4 km²</strong>
          </div>

          <div className="metric">
            <span>DRIFT WINDOW</span>
            <strong>3h 00m</strong>
          </div>

          <div className="metric">
            <span>VESSELS ANALYZED</span>
            <strong>05</strong>
          </div>

          <div className="metric">
            <span>TOP SUSPECT</span>
            <strong>VANGUARD</strong>
          </div>

          <button
  className={`alert-button ${
    alertStatus === "ALERT SENT" ? "alert-sent" : ""
  }`}
  onClick={dispatchAlert}
  disabled={alertLoading}
>
  <Bell size={17} />

  {alertLoading ? "DISPATCHING..." : alertStatus}
</button>
        </aside>

        <section className="bottom-panel">
          <div className="panel-title">
            <Activity size={18} />
            DRIFT RECONSTRUCTION
          </div>

          {driftLoading ? (
            <div className="drift-loading">
              CALCULATING DRIFT TRAJECTORY...
            </div>
          ) : trajectory.length > 0 ? (
            <div className="timeline">
              <div className="timeline-line" />

              {trajectory.map((point, index) => (
                <div
                  className={`timeline-point ${
                    index === trajectory.length - 1 ? "active" : ""
                  }`}
                  key={`${point.time}-${index}`}
                >
                  <span>{point.time}</span>
                  <strong>{point.label}</strong>
                </div>
              ))}
            </div>
          ) : (
            <div className="drift-loading">
              DRIFT DATA UNAVAILABLE
            </div>
          )}
        </section>

        <AnomalyPanel />

        <VesselLeaderboard />

      </main>
    </div>
  );
}

export default CommandCenter;