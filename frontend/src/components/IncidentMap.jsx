import {
  MapContainer,
  TileLayer,
  Circle,
  Marker,
  Popup,
  Polyline,
  useMap,
} from "react-leaflet";
import { useEffect, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { getVessels } from "../services/api";

function MapController({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center && Array.isArray(center) && center.length === 2 && !isNaN(center[0]) && !isNaN(center[1])) {
      map.setView(center, zoom);
    }
  }, [center, zoom, map]);
  return null;
}

const vesselIcon = L.divIcon({
  className: "custom-vessel-marker",
  html: `
    <div class="vessel-marker">
      <span>⚓</span>
    </div>
  `,
  iconSize: [34, 34],
  iconAnchor: [17, 17],
});

const originIcon = L.divIcon({
  className: "custom-origin-marker",
  html: `
    <div class="origin-marker">
      <div class="origin-pulse"></div>
      <span>O</span>
    </div>
  `,
  iconSize: [34, 34],
  iconAnchor: [17, 17],
});

const detectedIcon = L.divIcon({
  className: "custom-detected-marker",
  html: `
    <div class="detected-marker">
      <span>●</span>
    </div>
  `,
  iconSize: [34, 34],
  iconAnchor: [17, 17],
});

function IncidentMap({ trajectory = [], origin = null, detected = null }) {
  const [vessels, setVessels] = useState([]);

  useEffect(() => {
    let mounted = true;
    getVessels()
      .then((data) => {
        if (mounted) {
          setVessels(data.filter((v) => v.latitude && v.longitude));
        }
      })
      .catch((err) => {
        console.error("Vessel tracking error:", err);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const driftPath = trajectory
    .filter((pt) => pt.latitude !== undefined && pt.longitude !== undefined)
    .map((pt) => [pt.latitude, pt.longitude]);

  // Dynamic map center resolution
  const defaultCenter = [25.0, -40.0];
  let center = defaultCenter;

  if (detected?.latitude && detected?.longitude) {
    center = [detected.latitude, detected.longitude];
  } else if (origin?.latitude && origin?.longitude) {
    center = [origin.latitude, origin.longitude];
  } else if (vessels.length > 0) {
    center = [vessels[0].latitude, vessels[0].longitude];
  }

  return (
    <div className="incident-map">
      <MapContainer
        center={center}
        zoom={vessels.length > 0 || detected ? 8 : 4}
        scrollWheelZoom={true}
        zoomControl={true}
        className="leaflet-map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapController center={center} zoom={vessels.length > 0 || detected ? 8 : 4} />

        {detected?.latitude && detected?.longitude && (
          <Circle
            center={[detected.latitude, detected.longitude]}
            radius={detected.radius_meters || 15000}
            pathOptions={{
              color: "#ff8b52",
              fillColor: "#ff7b45",
              fillOpacity: 0.22,
              weight: 2,
            }}
          />
        )}

        {origin?.latitude && origin?.longitude && (
          <Marker
            position={[origin.latitude, origin.longitude]}
            icon={originIcon}
          >
            <Popup>
              <strong>Estimated Spill Origin (Hindcast)</strong>
              <br />
              Time: {origin.timestamp || origin.time || "Origin"}
              <br />
              Latitude: {Number(origin.latitude).toFixed(4)}
              <br />
              Longitude: {Number(origin.longitude).toFixed(4)}
            </Popup>
          </Marker>
        )}

        {detected?.latitude && detected?.longitude && (
          <Marker
            position={[detected.latitude, detected.longitude]}
            icon={detectedIcon}
          >
            <Popup>
              <strong>Detected Slick (Satellite / Observation)</strong>
              <br />
              Latitude: {Number(detected.latitude).toFixed(4)}
              <br />
              Longitude: {Number(detected.longitude).toFixed(4)}
              {detected.area_sq_km && (
                <>
                  <br />
                  Estimated Area: {detected.area_sq_km} km²
                </>
              )}
            </Popup>
          </Marker>
        )}

        {driftPath.length > 1 && (
          <Polyline
            positions={driftPath}
            pathOptions={{
              color: "#0b9fb3",
              weight: 4,
              opacity: 0.9,
              dashArray: "8 6",
            }}
          />
        )}

        {vessels.map((vessel, idx) => (
          <Marker
            key={`${vessel.imo || vessel.mmsi || idx}`}
            position={[vessel.latitude, vessel.longitude]}
            icon={vesselIcon}
          >
            <Popup>
              <strong>{vessel.name}</strong>
              <br />
              MMSI: {vessel.mmsi || "—"} | IMO: {vessel.imo || "—"}
              <br />
              Speed: {vessel.speed} kn | Course: {vessel.course}°
              <br />
              Position: ({Number(vessel.latitude).toFixed(4)}, {Number(vessel.longitude).toFixed(4)})
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      <div className="map-live-badge">
        ● LIVE AIS / INCIDENT MAP
      </div>
    </div>
  );
}

export default IncidentMap;