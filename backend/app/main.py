import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.words import router as words_router
from backend.app.api.routes.stats import router as stats_router
from backend.app.api.routes.quiz import router as quiz_router
from backend.app.api.routes.questions import router as questions_router
from backend.app.api.routes.settings import router as settings_router
from backend.app.api.routes.search import router as search_router
from backend.app.api.routes import writing
from backend.app.api.routes.flashcards import router as flashcards_router

from backend.app.db.database import get_db
from backend.app.services.stats_service import get_dashboard_data
from backend.app.services.daily_paragraph_service import get_or_create_today_paragraph



load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_paths = [
        "/login",
        "/favicon.ico",
    ]

    if (
        request.url.path.startswith("/static")
        or request.url.path in public_paths
    ):
        return await call_next(request)

    if not request.session.get("authenticated"):
        return RedirectResponse(
            url="/login",
            status_code=303,
        )

    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv(
        "SESSION_SECRET_KEY",
        "gptictionary-default-session-secret-key",
    ),
)


app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)


templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(str(BASE_DIR / "static" / "favicon.png"))


app.include_router(auth_router)
app.include_router(words_router)
app.include_router(stats_router)
app.include_router(quiz_router)
app.include_router(questions_router)
app.include_router(settings_router)
app.include_router(search_router)
app.include_router(writing.router)
app.include_router(flashcards_router)

@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "dashboard": get_dashboard_data(db),
            "today_paragraph": get_or_create_today_paragraph(db),
        },
    )