from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from backend.app.core.templates import templates
from backend.app.core.auth import check_password

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "request": request,
            "error": None,
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    password: str = Form(...),
):
    if check_password(password):
        request.session["authenticated"] = True
        return RedirectResponse(
            url="/",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "request": request,
            "error": "비밀번호가 틀렸습니다.",
        },
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(
        url="/login",
        status_code=303,
    )