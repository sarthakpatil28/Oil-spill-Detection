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

const center = [15.5, 68.5];


const driftPath = [
  [15.15, 67.85],
  [15.28, 68.02],
  [15.4, 68.2],
  [15.5, 68.5],
  [15.6, 68.7],
  [15.72, 68.85],
];


function IncidentMap() {
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
  attribution='&copy; OpenStreetMap'
  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
/>

        <Circle
          center={[15.5, 68.5]}
          radius={22000}
          pathOptions={{
            color: "#ff8b52",
            fillColor: "#ff7b45",
            fillOpacity: 0.18,
            weight: 2,
          }}
        />

        <Marker
          position={[15.15, 67.85]}
          icon={originIcon}
        >
          <Popup>
            <strong>Estimated Spill Origin</strong>
            <br />
            Reconstruction window: T − 3H
          </Popup>
        </Marker>

        <Polyline
          positions={driftPath}
          pathOptions={{
            color: "#53d5e6",
            weight: 3,
            dashArray: "8 8",
          }}
        />

        {vessels.map((vessel) => (
          <Marker
            key={vessel.name}
            position={[vessel.latitude, vessel.longitude]}
            icon={vesselIcon}
          >
            <Popup>
              <strong>{vessel.name}</strong>
              <br />
              Speed: {vessel.speed}
              <br />
              Course: {vessel.course}
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