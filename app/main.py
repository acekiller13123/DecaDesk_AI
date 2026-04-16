from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
from dotenv import load_dotenv

from agent.executor import TaskExecutor
from agent.planner import PlannerAgent
from app.db import create_db_and_tables, seed_data
from app.routes import router


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "app", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "app", "static")
load_dotenv(os.path.join(BASE_DIR, ".env"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    create_db_and_tables()
    seed_data()
    application.state.templates = templates
    application.state.planner = PlannerAgent()
    application.state.executor = TaskExecutor()
    yield


app = FastAPI(title="DecaDesk AI Admin", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/dashboard")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

