
import {
  Activity,
  AlertTriangle,
  Anchor,
  Bell,
  Map,
  Radio,
  Satellite,
  ShieldCheck,
  Waves,
} from "lucide-react";


import VesselLeaderboard from "../components/VesselLeaderboard";

import IncidentMap from "../components/IncidentMap";

import AnomalyPanel from "../components/AnomalyPanel";

function CommandCenter() {
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

         <IncidentMap />
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

          <button className="alert-button">
            <Bell size={17} />
            DISPATCH ALERT
          </button>
        </aside>

        <section className="bottom-panel">
          <div className="panel-title">
            <Activity size={18} />
            DRIFT RECONSTRUCTION
          </div>

          <div className="timeline">
            <div className="timeline-line" />

            <div className="timeline-point">
              <span>T − 3H</span>
              <strong>ORIGIN</strong>
            </div>

            <div className="timeline-point">
              <span>T − 2H</span>
              <strong>DRIFT</strong>
            </div>

            <div className="timeline-point">
              <span>T − 1H</span>
              <strong>DRIFT</strong>
            </div>

            <div className="timeline-point active">
              <span>NOW</span>
              <strong>DETECTED</strong>
            </div>
          </div>
        </section>
	<AnomalyPanel />	
	<VesselLeaderboard />
      </main>
    </div>
  );
}

export default CommandCenter;
