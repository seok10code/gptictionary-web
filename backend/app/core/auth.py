import os

from fastapi import Request
from dotenv import load_dotenv

load_dotenv()

APP_PASSWORD = os.getenv("APP_PASSWORD")


def is_logged_in(request: Request) -> bool:
    return request.session.get("authenticated", False)


def check_password(password: str) -> bool:
    return password == APP_PASSWORD