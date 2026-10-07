import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Activity,
  Navigation,
  Target,
} from "lucide-react";

function AnomalyPanel() {
  const [anomalies, setAnomalies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/anomalies")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to fetch anomaly data");
        }

        return response.json();
      })
      .then((result) => {
        setAnomalies(result.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setError("Unable to connect to anomaly engine");
        setLoading(false);
      });
  }, []);

  const getIcon = (type) => {
    if (type === "SPEED DROP") {
      return <Activity size={17} />;
    }

    if (type === "COURSE SHIFT") {
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

      {!loading && !error && (
        <div className="anomaly-list">
          {anomalies.map((anomaly) => (
            <div
              className={`anomaly-card ${
                anomaly.severity === "HIGH"
                  ? "anomaly-high"
                  : "anomaly-medium"
              }`}
              key={anomaly.imo}
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