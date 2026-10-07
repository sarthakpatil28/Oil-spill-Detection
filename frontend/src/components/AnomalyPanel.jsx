import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Activity,
  Navigation,
  Target,
} from "lucide-react";
import { getAnomalies } from "../services/api";

function AnomalyPanel() {
  const [anomalies, setAnomalies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    getAnomalies()
      .then((data) => {
        if (mounted) {
          setAnomalies(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          console.error("Anomaly API error:", err);
          setError(err.message || "Unable to connect to anomaly engine");
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  const getIcon = (type) => {
    if (type?.includes("SPEED") || type?.includes("SOG")) {
      return <Activity size={17} />;
    }
    if (type?.includes("COURSE") || type?.includes("COG") || type?.includes("SHIFT")) {
      return <Navigation size={17} />;
    }
    return <Target size={17} />;
  };

  return (
    <section className="anomaly-panel">
      <div className="anomaly-header">
        <div>
          <span className="eyebrow">ANOMALY DETECTION ENGINE</span>
          <h2>Vessel Anomalies</h2>
        </div>

        <div className="anomaly-count">
          <AlertTriangle size={15} />
          {loading ? "SCANNING" : `${anomalies.length} EVENTS`}
        </div>
      </div>

      {loading && (
        <div className="api-state">
          Scanning AIS telemetry...
        </div>
      )}

      {error && (
        <div className="api-error">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {!loading && !error && anomalies.length === 0 && (
        <div className="api-state">
          No anomalous vessel behaviors detected in active AIS window.
        </div>
      )}

      {!loading && !error && anomalies.length > 0 && (
        <div className="anomaly-list">
          {anomalies.map((anomaly, idx) => (
            <div
              className={`anomaly-card ${
                anomaly.severity === "HIGH" || anomaly.severity === "CRITICAL"
                  ? "anomaly-high"
                  : "anomaly-medium"
              }`}
              key={`${anomaly.imo}-${idx}`}
            >
              <div className="anomaly-icon">
                {getIcon(anomaly.type)}
              </div>

              <div className="anomaly-main">
                <div className="anomaly-vessel">
                  {anomaly.vessel}
                </div>

                <div className="anomaly-type">
                  {anomaly.type}
                </div>

                <p>{anomaly.description}</p>
              </div>

              <div className="anomaly-meta">
                <span className="severity">
                  {anomaly.severity}
                </span>

                <strong>{anomaly.score}%</strong>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export default AnomalyPanel;