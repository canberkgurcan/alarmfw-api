import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import checks, notifiers, secrets, alarms, runner, policies, config, monitor, terminal, admin

app = FastAPI(title="AlarmFW API", version="0.1.0")

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(checks.router)
app.include_router(notifiers.router)
app.include_router(secrets.router)
app.include_router(alarms.router)
app.include_router(runner.router)
app.include_router(policies.router)
app.include_router(config.router)
app.include_router(monitor.router)
app.include_router(terminal.router)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
