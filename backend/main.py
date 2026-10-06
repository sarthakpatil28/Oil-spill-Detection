from fastapi import FastAPI

app = FastAPI(
    title="Marine Oil Spill Intelligence API",
    description="Backend for oil spill detection, drift prediction and AIS vessel attribution.",
    version="0.1.0"
)


@app.get("/api/health")
def health_check():
    return {
        "status": "operational",
        "system": "Marine Oil Spill Intelligence",
        "version": "0.1.0"
    }