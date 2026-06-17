from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.app.api.routes.words import router as words_router
from backend.app.api.routes.stats import router as stats_router
from backend.app.api.routes.quiz import router as quiz_router
from backend.app.api.routes.questions import router as questions_router
from backend.app.api.routes.settings import router as settings_router
from backend.app.api.routes.search import router as search_router

from backend.app.db.database import get_db
from backend.app.services.stats_service import get_dashboard_data
from fastapi.responses import FileResponse



BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

app.include_router(words_router)
app.include_router(stats_router)
app.include_router(quiz_router)
app.include_router(questions_router)
app.include_router(settings_router)
app.include_router(search_router)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("backend/app/static/favicon.png")


app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "dashboard": get_dashboard_data(db),
        },
    )