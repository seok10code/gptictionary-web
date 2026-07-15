from fastapi import (
    APIRouter,
    Depends,
    Request,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.app.core.templates import templates
from backend.app.db.database import get_db
from backend.app.services.stats_service import (
    get_daily_review_activity,
    get_recent_senses,
    get_stats,
    get_top_correct_senses,
    get_top_wrong_senses,
)


router = APIRouter()


@router.get(
    "/stats",
    response_class=HTMLResponse,
)
def stats_page(
    request: Request,
    db: Session = Depends(get_db),
):
    wrong_senses = get_top_wrong_senses(db)
    correct_senses = get_top_correct_senses(db)
    recent_senses = get_recent_senses(db)

    daily_labels, daily_data = (
        get_daily_review_activity(db)
    )

    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "request": request,
            "stats": get_stats(db),
            "recent_senses": recent_senses,
            "wrong_chart_labels": [
                item["label"]
                for item in wrong_senses
            ],
            "wrong_chart_data": [
                item["value"]
                for item in wrong_senses
            ],
            "correct_chart_labels": [
                item["label"]
                for item in correct_senses
            ],
            "correct_chart_data": [
                item["value"]
                for item in correct_senses
            ],
            "daily_labels": daily_labels,
            "daily_data": daily_data,
        },
    )
