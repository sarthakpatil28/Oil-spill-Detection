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




# --------------------------------------------------
# Vessel Anomaly Intelligence
# --------------------------------------------------

@app.get("/api/anomalies")
def get_anomalies():
    return {
        "status": "success",
        "data": [
            {
                "vessel": "VANGUARD",
                "imo": "9182734",
                "type": "SPEED DROP",
                "severity": "HIGH",
                "description": "Sudden reduction in vessel speed detected.",
                "score": 94.2
            },
            {
                "vessel": "OCEAN STAR",
                "imo": "9273611",
                "type": "COURSE SHIFT",
                "severity": "MEDIUM",
                "description": "Significant deviation from expected course detected.",
                "score": 71.8
            },
            {
                "vessel": "MERIDIAN",
                "imo": "9018273",
                "type": "PROXIMITY",
                "severity": "MEDIUM",
                "description": "Vessel passed within the reconstructed incident corridor.",
                "score": 48.5
            }
        ]
    }

# --------------------------------------------------
# Suspect Scoring Engine
# --------------------------------------------------

def calculate_suspect_score(
    speed_anomaly,
    course_anomaly,
    proximity,
    additional_evidence
):
    score = (
        speed_anomaly * 0.40
        + course_anomaly * 0.25
        + proximity * 0.25
        + additional_evidence * 0.10
    )

    return round(score, 1)


@app.get("/api/suspects")
def get_suspects():

    evidence = [
        {
            "vessel": "VANGUARD",
            "imo": "9182734",
            "speed_anomaly": 100,
            "course_anomaly": 92,
            "proximity": 94,
            "additional_evidence": 88
        },
        {
            "vessel": "OCEAN STAR",
            "imo": "9273611",
            "speed_anomaly": 72,
            "course_anomaly": 86,
            "proximity": 62,
            "additional_evidence": 58
        },
        {
            "vessel": "MERIDIAN",
            "imo": "9018273",
            "speed_anomaly": 42,
            "course_anomaly": 38,
            "proximity": 72,
            "additional_evidence": 44
        },
        {
            "vessel": "ATLANTIS",
            "imo": "9348217",
            "speed_anomaly": 28,
            "course_anomaly": 24,
            "proximity": 38,
            "additional_evidence": 35
        },
        {
            "vessel": "PACIFIC",
            "imo": "9182731",
            "speed_anomaly": 18,
            "course_anomaly": 20,
            "proximity": 22,
            "additional_evidence": 18
        }
    ]

    suspects = []

    for vessel in evidence:
        score = calculate_suspect_score(
            vessel["speed_anomaly"],
            vessel["course_anomaly"],
            vessel["proximity"],
            vessel["additional_evidence"]
        )

        suspects.append({
            "vessel": vessel["vessel"],
            "imo": vessel["imo"],
            "score": score,
            "evidence": {
                "speed_anomaly": vessel["speed_anomaly"],
                "course_anomaly": vessel["course_anomaly"],
                "proximity": vessel["proximity"],
                "additional_evidence": vessel["additional_evidence"]
            }
        })

    suspects.sort(
        key=lambda vessel: vessel["score"],
        reverse=True
    )

    for rank, vessel in enumerate(suspects, start=1):
        vessel["rank"] = rank

    return {
        "status": "success",
        "disclaimer": (
            "Suspect scores are evidence-based rankings "
            "and do not establish responsibility or guilt."
        ),
        "weights": {
            "speed_anomaly": 0.40,
            "course_anomaly": 0.25,
            "proximity": 0.25,
            "additional_evidence": 0.10
        },
        "data": suspects
    }