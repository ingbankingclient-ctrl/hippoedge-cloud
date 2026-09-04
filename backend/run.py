import os

import uvicorn


if __name__ == "__main__":
    environment = os.getenv("HIPPOEDGE_ENVIRONMENT", "development")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=environment == "development",
        # Do not apply a global Uvicorn request-concurrency ceiling here.
        # The web UI legitimately sends several CORS preflights/API requests
        # in parallel. A low global limit causes 503 "Exceeded concurrency
        # limit" responses before the programme can load.
        #
        # Memory savings remain handled by the application-level fixes
        # (bounded caches, compact fingerprints and lower-duplication
        # opponent-network processing), without reducing history depth.
        timeout_keep_alive=5,
    )
