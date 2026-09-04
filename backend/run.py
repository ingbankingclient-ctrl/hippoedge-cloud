import os

import uvicorn


if __name__ == "__main__":
    environment = os.getenv("HIPPOEDGE_ENVIRONMENT", "development")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=environment == "development",
        # Heavy analyses load complete careers. Bound simultaneous in-flight
        # requests so two browser refreshes cannot multiply the same RAM peak.
        # This changes only scheduling, never history depth or scoring.
        limit_concurrency=max(1, int(os.getenv("HIPPOEDGE_MAX_CONCURRENCY", "2"))),
        backlog=max(16, int(os.getenv("HIPPOEDGE_BACKLOG", "32"))),
        timeout_keep_alive=5,
    )
