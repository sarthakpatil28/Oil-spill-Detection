from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Marine Oil Spill Intelligence API",
    description="Backend for oil spill detection, drift prediction and AIS vessel attribution.",
    version="0.2.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Health
# --------------------------------------------------

@app.get("/api/health")
def health_check():
    return {
        "status": "operational",
        "system": "Marine Oil Spill Intelligence",
        "version": "0.2.0"
    }


# --------------------------------------------------
# Vessel Intelligence
# --------------------------------------------------

@app.get("/api/vessels")
def get_vessels():
    return {
        "status": "success",
        "count": 5,
        "data": [
           {
    "rank": 1,
    "name": "VANGUARD",
    "imo": "9182734",
    "speed": 2.1,
    "course": 184,
    "anomaly": "SPEED DROP",
    "score": 94.2,
    "latitude": 15.9,
    "longitude": 68.1
},
           {
    "rank": 2,
    "name": "OCEAN STAR",
    "imo": "9273611",
    "speed": 8.7,
    "course": 201,
    "anomaly": "COURSE SHIFT",
    "score": 71.8,
    "latitude": 15.2,
    "longitude": 68.9
},
           {
    "rank": 3,
    "name": "MERIDIAN",
    "imo": "9018273",
    "speed": 11.4,
    "course": 176,
    "anomaly": "PROXIMITY",
    "score": 48.5,
    "latitude": 16.1,
    "longitude": 69.3
},
           {
    "rank": 4,
    "name": "ATLANTIS",
    "imo": "9348217",
    "speed": 13.2,
    "course": 164,
    "anomaly": "LOW",
    "score": 31.2,
    "latitude": 15.7,
    "longitude": 69.6
},
            {
    "rank": 5,
    "name": "PACIFIC",
    "imo": "9182731",
    "speed": 14.8,
    "course": 158,
    "anomaly": "LOW",
    "score": 18.7,
    "latitude": 16.4,
    "longitude": 68.7
}
        ]
    }