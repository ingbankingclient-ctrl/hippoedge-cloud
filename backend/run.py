import os

import uvicorn


if __name__ == "__main__":
    environment = os.getenv("HIPPOEDGE_ENVIRONMENT", "development")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=environment == "development",
    )
