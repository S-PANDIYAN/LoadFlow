"""LoadFlow — FastAPI application entrypoint."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import Base, engine, SessionLocal
from app.permissions_catalog import seed_permissions
from app.seed import seed_demo_data
from app.routers import auth, rbac, loads, compliance

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="LoadFlow", description="Freight Brokerage Operations Suite")

# --- startup: create tables + seed catalog & demo data ---
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    seed_permissions(db)
    seed_demo_data(db)

# --- API routers (all enforcement lives here, server-side) ---
app.include_router(auth.router)
app.include_router(rbac.router)
app.include_router(loads.router)
app.include_router(compliance.router)

# --- UI (server-rendered shell; pages call the JWT-protected APIs via fetch) ---
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    # Auth happens client-side against /auth/me; APIs enforce server-side.
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/health")
def health():
    return {"status": "ok"}
