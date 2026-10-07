import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Ship,
} from "lucide-react";

const vessels = [
  {
    rank: 1,
    name: "VANGUARD",
    imo: "9182734",
    score: 94.2,
    speed: "2.1 kn",
    course: "184°",
    anomaly: "SPEED DROP",
    trend: "up",
  },
  {
    rank: 2,
    name: "OCEAN STAR",
    imo: "9273611",
    score: 71.8,
    speed: "8.7 kn",
    course: "201°",
    anomaly: "COURSE SHIFT",
    trend: "up",
  },
  {
    rank: 3,
    name: "MERIDIAN",
    imo: "9018273",
    score: 48.5,
    speed: "11.4 kn",
    course: "176°",
    anomaly: "PROXIMITY",
    trend: "down",
  },
  {
    rank: 4,
    name: "ATLANTIS",
    imo: "9348217",
    score: 31.2,
    speed: "13.2 kn",
    course: "164°",
    anomaly: "LOW",
    trend: "down",
  },
  {
    rank: 5,
    name: "PACIFIC",
    imo: "9182731",
    score: 18.7,
    speed: "14.8 kn",
    course: "158°",
    anomaly: "LOW",
    trend: "down",
  },
];

function VesselLeaderboard() {
  return (
    <section className="vessel-panel">
      <div className="vessel-header">
        <div>
          <span className="eyebrow">AIS CORRELATION ENGINE</span>
          <h2>Vessel Intelligence</h2>
        </div>

        <div className="analysis-count">
          <Ship size={15} />
          05 ANALYZED
        </div>
      </div>

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
            <span className="rank">{String(vessel.rank).padStart(2, "0")}</span>

            <span className="vessel-name">
              <Ship size={15} />
              {vessel.name}
            </span>

            <span className="imo">{vessel.imo}</span>

            <span>{vessel.speed}</span>

            <span>{vessel.course}</span>

            <span className="anomaly">
              {vessel.rank <= 2 && <AlertTriangle size={13} />}
              {vessel.anomaly}
            </span>

            <span className="score">
              <strong>{vessel.score}%</strong>

              <span className="score-bar">
                <span style={{ width: `${vessel.score}%` }} />
              </span>

              {vessel.trend === "up" ? (
                <ArrowUpRight size={14} />
              ) : (
                <ArrowDownRight size={14} />
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="demo-note">
        DEMO DATA — AIS correlation values are simulated for demonstration.
      </div>
    </section>
  );
}

export default VesselLeaderboard;