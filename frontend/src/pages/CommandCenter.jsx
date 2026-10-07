import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  ShieldCheck,
  Waves,
} from "lucide-react";

import VesselLeaderboard from "../components/VesselLeaderboard";
import IncidentMap from "../components/IncidentMap";
import AnomalyPanel from "../components/AnomalyPanel";
import {
  getHealth,
  getSuspects,
  getVessels,
  calculateDrift,
  dispatchAlert,
} from "../services/api";

function CommandCenter() {
  const [systemOnline, setSystemOnline] = useState(false);
  const [alertStatus, setAlertStatus] = useState("READY");
  const [alertLoading, setAlertLoading] = useState(false);
  const [alertDetails, setAlertDetails] = useState(null);
  const [suspects, setSuspects] = useState([]);
  const [vesselsCount, setVesselsCount] = useState(0);
  const [driftData, setDriftData] = useState(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  // Check backend health & telemetry on load
  useEffect(() => {
    let mounted = true;

    async function initSystem() {
      try {
        const health = await getHealth();
        if (mounted && health.status === "ok") {
          setSystemOnline(true);
        }
      } catch (err) {
        console.warn("Backend health check:", err.message);
        if (mounted) setSystemOnline(false);
      }

      try {
        const allVessels = await getVessels();
        if (mounted) setVesselsCount(allVessels.length);
      } catch (err) {
        console.warn("Vessels fetch error:", err.message);
      }

      try {
        const rankedSuspects = await getSuspects();
        if (mounted) setSuspects(rankedSuspects);
      } catch (err) {
        // Suspects may not be calculated yet if no drift run
        console.log("Suspects status:", err.message);
      }
    }

    initSystem();
    return () => {
      mounted = false;
    };
  }, []);

  const topSuspect = suspects.length > 0 ? suspects[0] : null;

  // Real alert dispatch triggered by user
  const handleDispatchAlert = async () => {
    try {
      setAlertLoading(true);
      setAlertStatus("DISPATCHING...");
      setErrorMessage("");

      const payload = topSuspect
        ? {
            incident: "Marine Oil Spill Incident",
            priority: topSuspect.riskTier || "HIGH",
            vessel: topSuspect.vessel,
            score: topSuspect.score,
          }
        : {};

      const response = await dispatchAlert(payload);

      if (response.status === "success" && response.alert) {
        setAlertStatus("ALERT SENT");
        setAlertDetails(response.alert);
      } else {
        throw new Error("Unexpected alert response schema");
      }
    } catch (error) {
      console.error("Alert dispatch error:", error);
      setAlertStatus("DISPATCH FAILED");
      setErrorMessage(error.message || "Failed to dispatch alert.");
    } finally {
      setAlertLoading(false);
    }
  };

  const handleRunDrift = async () => {
    try {
      setDriftLoading(true);
      setErrorMessage("");
      const driftPayload = {
        slick: {
          polygon: null,
          centroid: { lat: 36.7, lon: -15.0 },
          area_sq_km: 3.8,
          perimeter_km: 8.6,
          observation_timestamp: "2024-06-01T08:30:00Z",
        },
        environment: {
          wind_U: 2.5,
          wind_V: -1.0,
          current_U: 0.4,
          current_V: 0.2,
        },
        elapsed_hours: 2.0,
        forecast_hours: 5,
      };
      const result = await calculateDrift(driftPayload);
      setDriftData(result);

      // Fetch newly correlated suspects from Member 3
      const ranked = await getSuspects();
      setSuspects(ranked);
    } catch (err) {
      console.error("Drift simulation error:", err);
      setErrorMessage("Drift simulation error: " + err.message);
    } finally {
      setDriftLoading(false);
    }
  };

  const trajectory = driftData?.forecast?.map((pt) => ({
    time: `+${pt.hour}h`,
    label: `FC ${pt.hour}H`,
    latitude: pt.lat,
    longitude: pt.lon,
  })) || [];

  return (
    <div className="command-center">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <Waves size={24} />
          </div>

          <div>
            <h1>AQUAGUARD AI</h1>
            <span>MARITIME OIL SPILL SURVEILLANCE &amp; ATTRIBUTION</span>
          </div>
        </div>

        <div className="system-status">
          <span className={`status-dot ${systemOnline ? "" : "offline"}`} />
          {systemOnline ? "BACKEND OPERATIONAL" : "BACKEND CONNECTING..."}
        </div>
      </header>

      <main className="dashboard">
        <section className="hero-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">LIVE INCIDENT MONITOR</span>
              <h2>Autonomous Maritime Surveillance</h2>
            </div>

            <div className="incident-status">
              <AlertTriangle size={16} />
              ATTRIBUTION READY
            </div>
          </div>

          <IncidentMap
            trajectory={trajectory}
            origin={driftData?.origin ? { latitude: driftData.origin.lat, longitude: driftData.origin.lon } : null}
            detected={driftData?.slick ? {
              latitude: driftData.slick.centroid?.lat,
              longitude: driftData.slick.centroid?.lon,
              area_sq_km: driftData.slick.area_sq_km,
            } : null}
          />
        </section>

        <aside className="intelligence-panel">
          <div className="panel-title">
            <ShieldCheck size={18} />
            INCIDENT INTELLIGENCE
          </div>

          <div className="metric">
            <span>VESSELS IN CORRIDOR</span>
            <strong>{vesselsCount > 0 ? String(vesselsCount).padStart(2, "0") : "—"}</strong>
          </div>

          <div className="metric">
            <span>CANDIDATES RANKED</span>
            <strong>{suspects.length > 0 ? String(suspects.length).padStart(2, "0") : "—"}</strong>
          </div>

          <div className="metric">
            <span>PRIME ATTRIBUTION</span>
            <strong>{topSuspect ? topSuspect.vessel : "Awaiting Run"}</strong>
            {topSuspect && (
              <span style={{ color: "#ff887d", fontSize: "11px", marginTop: "4px" }}>
                Score: {topSuspect.score}% ({topSuspect.riskTier})
              </span>
            )}
          </div>

          <button
            className={`alert-button ${
              alertStatus === "ALERT SENT" ? "alert-sent" : ""
            }`}
            onClick={handleDispatchAlert}
            disabled={alertLoading}
          >
            {alertStatus === "ALERT SENT" ? <CheckCircle2 size={17} /> : <Bell size={17} />}
            {alertLoading ? "DISPATCHING..." : alertStatus === "ALERT SENT" ? "ALERT DISPATCHED" : "DISPATCH EMERGENCY ALERT"}
          </button>

          {alertDetails && (
            <div style={{ marginTop: "14px", padding: "10px", background: "rgba(103, 232, 165, 0.08)", border: "1px solid rgba(103, 232, 165, 0.3)", borderRadius: "8px", fontSize: "11px" }}>
              <div style={{ color: "#67e8a5", fontWeight: 700 }}>EMERGENCY ALERT RECORDED</div>
              <div>Suspect: {alertDetails.top_suspect}</div>
              <div>Priority: {alertDetails.priority}</div>
              <div>Score: {alertDetails.suspect_score}%</div>
              <div>Status: {alertDetails.dispatch_status}</div>
            </div>
          )}

          {errorMessage && (
            <div style={{ marginTop: "12px", color: "#ff725f", fontSize: "11px" }}>
              {errorMessage}
            </div>
          )}
        </aside>

        <section className="bottom-panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", borderBottom: "1px solid rgba(120, 190, 210, 0.1)", paddingBottom: "12px" }}>
            <div className="panel-title" style={{ paddingBottom: 0, borderBottom: "none" }}>
              <Activity size={18} />
              DRIFT RECONSTRUCTION TRAJECTORY
            </div>
            <button
              onClick={handleRunDrift}
              disabled={driftLoading}
              style={{
                background: "rgba(83, 213, 230, 0.12)",
                border: "1px solid rgba(83, 213, 230, 0.4)",
                color: "#53d5e6",
                borderRadius: "7px",
                padding: "8px 14px",
                fontSize: "11px",
                fontWeight: 700,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "7px",
                transition: "all 0.2s ease",
              }}
            >
              <Activity size={14} />
              {driftLoading ? "COMPUTING DRIFT..." : (driftData ? "RE-RUN DRIFT SIMULATION" : "RUN DRIFT & ATTRIBUTION")}
            </button>
          </div>

          {driftLoading ? (
            <div className="drift-loading">
              COMPUTING HYDRODYNAMIC DRIFT...
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
                  <div style={{ fontSize: "9px", color: "#8faab6" }}>
                    {point.latitude.toFixed(2)}, {point.longitude.toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="drift-loading">
              HYDRODYNAMIC DRIFT ENGINE READY (5h FORECAST + 3h HINDCAST)
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