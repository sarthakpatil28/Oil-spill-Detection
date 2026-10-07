# 🌊 Ocean Sentinel

**End-to-end oil-spill detection, drift prediction and vessel attribution platform.**
Ocean Sentinel turns satellite SAR imagery and AIS vessel telemetry into actionable oil-spill intelligence for disaster response.

- **Hackathon:** Smart India Hackathon 2026 / INNOVA X Global Online Hackathon
- **Theme:** Disaster Management (Software)
- **Problem Statement:** SIH PS ID 1655 (NTRO) – Detecting Oil Spills in Marine Environment using AIS and Satellite Datasets

---

## 📌 Problem

1. **Ecological disasters** – Unannounced discharges and illegal bilge dumping damage ecosystems and fishing economies; the first hours decide containment.
2. **Attribution and drift** – Wind and currents move a slick far from its release point, so origin needs time-reversed modelling.
3. **Dark ships** – Offenders switch off AIS and disappear from conventional tracking.
4. **SAR limits** – 10–20 m pixels blur thin slicks; algal blooms, low-wind zones (< 3 m/s) and coastal shadows cause false alarms.

## 💡 Solution

Ocean Sentinel answers four questions: **Where is the spill? Where is it going? Who may be associated with it? What should the operator do next?**

`DETECT → LOCALIZE → PREDICT → ATTRIBUTE → ALERT → ACT`

It is CPU-optimised (no GPU required) and runs on cloud servers, field laptops or patrol-vessel hardware.

## 🧩 Modules

| Member | Module | Responsibilities |
|---|---|---|
| **M1** | AI & Computer Vision | 4× ESRGAN super-resolution (bicubic + unsharp fallback), land masking, Otsu / U-Net segmentation, circularity look-alike filter, dark-ship detection, georeferenced spill polygon |
| **M2** | Backend & Drift Engine | FastAPI REST router, validation, SOG speed-drop anomaly detection, Lagrangian drift engine (backward hindcast + 2–5 h forecast) |
| **M3** | AIS Attribution | AccessAIS ingestion and normalisation, space-time filtering around the leak origin, multi-factor risk scoring |
| **M4** | Frontend & Dispatch | React + Mapbox GL command center, time-slider, vector overlays, automated Coast Guard e-mail / PDF briefs |

## 🔄 Pipeline

1. **Telemetry ingestion** – Monitor AccessAIS; flag open-water SOG < 3 kn.
2. **Vision pipeline** – Fetch Sentinel-1 SAR → ESRGAN 4× → land mask (`cv2.bitwise_and`) → Otsu / U-Net → circularity filter.
3. **Dark-ship detection** – Isolate hyper-bright reflections (intensity > 240) in open water.
4. **Drift engine** – `V_oil = V_current + 0.03 · V_wind`; hindcast the origin, forecast 2–5 h ahead.
5. **AIS correlation and scoring** – Vessels within 15 km / 2 h of the origin, scored 50 % proximity, 30 % speed drop, 20 % heading shift.
6. **Command center** – Map, drift paths, suspect leaderboard and automated dispatch.

**Circularity filter:** `Circularity = 4πA / P²`. Values ≥ 0.70 are treated as compact look-alikes (e.g. algal blooms); values < 0.70 are kept as candidate slicks. The 0.70 threshold is a heuristic to be calibrated on validation data.

**Design principle:** invalid data is rejected or flagged, never fabricated. Vessels are *ranked by evidence*, not accused.

## ✨ Key Features

1. Real-time AIS speed-drop anomaly trigger
2. 4× ESRGAN cloud super-resolution with local fallback
3. Land masking and dual-domain segmentation (Otsu + U-Net)
4. Isoperimetric circularity look-alike filter
5. High-backscatter dark-ship radar detection
6. Lagrangian hydrodynamic drift engine (3 % windage)
7. Multi-factor vessel risk leaderboard (by IMO number)
8. Interactive command center with automated dispatcher

## 🛠 Tech Stack

| Area | Technologies |
|---|---|
| Languages | Python 3.12, JavaScript (ES6+ / Node.js) |
| Frontend | React.js, Mapbox GL JS, Tailwind CSS, Axios, `@gradio/client` |
| Backend | FastAPI, Uvicorn, Pydantic |
| Vision & data | OpenCV (`opencv-python-headless`), NumPy, Pandas, SciPy, PyTorch, Haversine |
| AI models | U-Net CNN, ESRGAN (Hugging Face Space `shivam12119/fire`), Lagrangian transport model |
| Formats | GeoJSON, WGS84 (EPSG:4326), CSV, CSV.zst, GeoPackage (.gpkg) |
| Deployment | Docker, Hugging Face Spaces, CPU-only local fallback |

## 📂 Data Sources

- Sentinel-1 SAR – Copernicus Data Space Ecosystem
- SAR Oil Spill Dataset – https://zenodo.org/records/10664073
- AccessAIS vessel traffic – MarineCadastre.gov (BOEM / NOAA / USCG)

## 🚀 Getting Started

> Adjust paths and commands to match your repository layout.

```bash
# 1. Clone
git clone https://github.com/<your-username>/ocean-sentinel.git
cd ocean-sentinel

# 2. Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.vision_api:app --reload

# 3. Frontend
cd frontend
npm install
npm start
```

Set the following environment variables (e.g. in a `.env` file):

```env
MAPBOX_TOKEN=<your-mapbox-token>
SMTP_HOST=<mail-server>          # Coast Guard e-mail dispatch
SMTP_USER=<user>
SMTP_PASSWORD=<password>
```

## 🔗 Project Links

- **Code Repository:** `<add link>`
- **Live Demo:** `<add link>`
- **Documentation:** `<add link>`
- **Demo Video:** `<add link>`

## 👥 Team

| Member | Role |
|---|---|
| `<name>` | M1 – AI & Computer Vision |
| `<name>` | M2 – Backend & Physics Drift |
| `<name>` | M3 – AIS Attribution |
| `<name>` | M4 – Frontend & Dispatch |

## 📜 References

- Wang et al., *ESRGAN: Enhanced Super-Resolution Generative Adversarial Networks* – https://arxiv.org/abs/1809.00219
- Ronneberger et al., *U-Net: Convolutional Networks for Biomedical Image Segmentation* – https://arxiv.org/abs/1505.04597
