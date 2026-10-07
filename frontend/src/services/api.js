/**
 * api.js — AquaGuard AI Backend API Client
 * Centralized API service connecting the Member 4 frontend to the active backend.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const config = {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  };

  const response = await fetch(url, config);
  if (!response.ok) {
    let errorDetail = `HTTP ${response.status} ${response.statusText}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = typeof errorJson.detail === "string" ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch (_) {
      // Use status text fallback
    }
    const err = new Error(errorDetail);
    err.status = response.status;
    throw err;
  }

  return response.json();
}

/**
 * Health check: GET /health
 */
export async function getHealth() {
  return request("/health");
}

/**
 * Vessel intelligence: GET /vessels
 * Returns normalized list of vessel dicts.
 */
export async function getVessels() {
  const data = await request("/vessels");
  const rawList = data.vessels || data.data || [];
  return rawList.map((v) => ({
    mmsi: v.MMSI || v.mmsi || "",
    imo: v.IMO || v.imo || "",
    name: v.VesselName || v.name || v.vessel_name || (v.IMO ? `IMO ${v.IMO}` : `MMSI ${v.MMSI}`),
    latitude: Number(v.LAT ?? v.lat ?? v.latitude ?? 0),
    longitude: Number(v.LON ?? v.lon ?? v.longitude ?? 0),
    speed: Number(v.SOG ?? v.speed ?? v.sog_knots ?? 0),
    course: Number(v.COG ?? v.course ?? v.cog_degrees ?? 0),
    vesselType: v.VesselType || v.vessel_type || "Unknown",
    timestamp: v.BaseDateTime || v.timestamp || "",
    distanceToShoreKm: v.DistanceToShoreKm ?? v.distance_to_shore_km ?? null,
  }));
}

/**
 * Vessel anomalies: GET /anomalies
 * Returns normalized list of detected anomalies.
 */
export async function getAnomalies() {
  const data = await request("/anomalies");
  const rawList = data.anomalies || data.data || [];
  return rawList.map((a, idx) => ({
    id: a.imo || a.mmsi || idx,
    vessel: a.vessel_name || a.vessel || (a.imo ? `IMO ${a.imo}` : `MMSI ${a.mmsi}`),
    imo: a.imo ? String(a.imo) : (a.mmsi ? String(a.mmsi) : "N/A"),
    type: a.anomaly_type || a.type || "ANOMALY",
    severity: a.severity || (a.is_high_severity ? "HIGH" : "MEDIUM"),
    description: a.description || "Anomalous vessel behavior detected in AIS track.",
    score: Number(a.score ?? (a.severity === "HIGH" ? 90 : 65)),
  }));
}

/**
 * Suspect vessels leaderboard: GET /suspects
 * Returns ranked suspects from Member 3.
 */
export async function getSuspects() {
  const data = await request("/suspects");
  const rawList = data.suspects || data.data || [];
  return rawList.map((s, idx) => ({
    rank: s.rank || idx + 1,
    vessel: s.vessel_name || s.name || s.vessel || (s.imo ? `IMO ${s.imo}` : `MMSI ${s.mmsi}`),
    imo: s.imo ? String(s.imo) : (s.mmsi ? String(s.mmsi) : "N/A"),
    mmsi: s.mmsi ? String(s.mmsi) : "",
    score: Number(s.score ?? s.suspect_score_pct ?? 0),
    speed: Number(s.sog_knots ?? s.speed ?? 0),
    course: Number(s.cog_degrees ?? s.course ?? 0),
    latitude: Number(s.latitude ?? 0),
    longitude: Number(s.longitude ?? 0),
    riskTier: s.risk_tier || (s.score >= 80 ? "CRITICAL" : s.score >= 50 ? "HIGH" : "MEDIUM"),
    anomaly: s.factors?.sog_drop > 0 ? "SPEED DROP" : (s.factors?.cog_deviation > 0 ? "COURSE SHIFT" : "PROXIMITY"),
    distanceToOriginKm: s.distance_to_origin_km ?? s.proximity_km ?? null,
  }));
}

/**
 * Hydrodynamic Drift: POST /drift
 * Calculates hindcast origin and forecast trajectory.
 */
export async function calculateDrift(driftPayload) {
  return request("/drift", {
    method: "POST",
    body: JSON.stringify(driftPayload),
  });
}

/**
 * Emergency Alert Dispatcher: POST /alert
 * Dispatches incident notification through Member 4 dispatcher.
 */
export async function dispatchAlert(alertPayload = {}) {
  return request("/alert", {
    method: "POST",
    body: JSON.stringify(alertPayload),
  });
}

export default {
  getHealth,
  getVessels,
  getAnomalies,
  getSuspects,
  calculateDrift,
  dispatchAlert,
};
