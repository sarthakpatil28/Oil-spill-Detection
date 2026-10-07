import {
  MapContainer,
  TileLayer,
  Circle,
  Marker,
  Popup,
  Polyline,
} from "react-leaflet";

import { useEffect, useState } from "react";

import L from "leaflet";
import "leaflet/dist/leaflet.css";

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

const center = [15.75, 68.65];

function IncidentMap({ trajectory = [] }) {
  const [vessels, setVessels] = useState([]);

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/vessels")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Failed to fetch vessels");
        }

        return response.json();
      })
      .then((result) => {
        setVessels(result.data);
      })
      .catch((error) => {
        console.error("Vessel API error:", error);
      });
  }, []);

  const driftPath = trajectory.map((point) => [
    point.latitude,
    point.longitude,
  ]);

  const origin = trajectory.find(
    (point) => point.label === "ORIGIN"
  );

  const detected = trajectory.find(
    (point) => point.label === "DETECTED"
  );

  return (
    <div className="incident-map">
      <MapContainer
        center={center}
        zoom={6}
        scrollWheelZoom={true}
        zoomControl={true}
        className="leaflet-map"
      >
        <TileLayer
          attribution="&copy; OpenStreetMap"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <Circle
          center={[15.90, 68.90]}
          radius={22000}
          pathOptions={{
            color: "#ff8b52",
            fillColor: "#ff7b45",
            fillOpacity: 0.18,
            weight: 2,
          }}
        />

        {origin && (
          <Marker
            position={[
              origin.latitude,
              origin.longitude,
            ]}
            icon={originIcon}
          >
            <Popup>
              <strong>Estimated Spill Origin</strong>
              <br />
              Reconstruction window: {origin.time}
              <br />
              Latitude: {origin.latitude}
              <br />
              Longitude: {origin.longitude}
            </Popup>
          </Marker>
        )}

        {detected && (
          <Marker
            position={[
              detected.latitude,
              detected.longitude,
            ]}
            icon={detectedIcon}
          >
            <Popup>
              <strong>Detected Spill</strong>
              <br />
              Current position: NOW
              <br />
              Latitude: {detected.latitude}
              <br />
              Longitude: {detected.longitude}
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
              dashArray: "10 8",
            }}
          />
        )}

        {vessels.map((vessel) => (
          <Marker
            key={vessel.name}
            position={[
              vessel.latitude,
              vessel.longitude,
            ]}
            icon={vesselIcon}
          >
            <Popup>
              <strong>{vessel.name}</strong>
              <br />
              Speed: {vessel.speed} kn
              <br />
              Course: {vessel.course}°
              <br />
              Suspect score: {vessel.score}%
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