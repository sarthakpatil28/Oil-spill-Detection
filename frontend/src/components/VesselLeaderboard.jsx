import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Ship,
} from "lucide-react";

function VesselLeaderboard() {
  const [vessels, setVessels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/vessels")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to fetch vessel data");
        }

        return response.json();
      })
      .then((result) => {
        setVessels(result.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setError("Unable to connect to intelligence API");
        setLoading(false);
      });
  }, []);

  return (
    <section className="vessel-panel">
      <div className="vessel-header">
        <div>
          <span className="eyebrow">AIS CORRELATION ENGINE</span>
          <h2>Vessel Intelligence</h2>
        </div>

        <div className="analysis-count">
          <Ship size={15} />
          {loading ? "LOADING" : `${vessels.length} ANALYZED`}
        </div>
      </div>

      {loading && (
        <div className="api-state">
          Loading vessel intelligence...
        </div>
      )}

      {error && (
        <div className="api-error">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {!loading && !error && (
        <div className="vessel-table">
          <div className="vessel-table-header">
            <span>RANK</span>
            <span>VESSEL</span>
            <span>IMO</span>
            <span>SPEED</span>
            <span>COURSE</span>
            <span>ANOMALY</span>
            <span>SCORE</span>
          </div>

          {vessels.map((vessel) => (
            <div
              className={`vessel-row ${
                vessel.rank === 1 ? "top-suspect" : ""
              }`}
              key={vessel.imo}
            >
              <span className="rank">
                {String(vessel.rank).padStart(2, "0")}
              </span>

              <span className="vessel-name">
                <Ship size={15} />
                {vessel.name}
              </span>

              <span className="imo">{vessel.imo}</span>

              <span>{vessel.speed} kn</span>

              <span>{vessel.course}°</span>

              <span className="anomaly">
                {vessel.rank <= 2 && (
                  <AlertTriangle size={13} />
                )}

                {vessel.anomaly}
              </span>

              <span className="score">
                <strong>{vessel.score}%</strong>

                <span className="score-bar">
                  <span
                    style={{
                      width: `${vessel.score}%`,
                    }}
                  />
                </span>

                {vessel.rank <= 2 ? (
                  <ArrowUpRight size={14} />
                ) : (
                  <ArrowDownRight size={14} />
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="demo-note">
        DEMO DATA — AIS correlation values are simulated for demonstration.
      </div>
    </section>
  );
}

export default VesselLeaderboard;