from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from markupsafe import escape
from sqlalchemy import text

from app.deps import DbSession
from app.errors import LoginRequired, ServiceError
from app.routers import analytics, auth, exercises, pages, workouts
from app.templating import render

app = FastAPI(
    title="Liftbook API",
    version="2.0.0",
    description=(
        "Log strength-training sessions and analyse progress: estimated one-rep max "
        "trends, personal records, weekly volume, training frequency and plateau "
        "detection, computed in PostgreSQL.\n\n"
        "Authenticate with **Authorize** (email as username) or `POST /api/auth/token`."
    ),
    openapi_tags=[
        {"name": "auth", "description": "Registration and JWT login"},
        {"name": "workouts", "description": "Log, edit and review sessions"},
        {"name": "exercises", "description": "Shared catalog plus custom exercises"},
        {"name": "analytics", "description": "SQL-powered training analytics"},
    ],
)

api = APIRouter(prefix="/api")
for module in (auth, workouts, exercises, analytics):
    api.include_router(module.router)
app.include_router(api)
app.include_router(pages.router)


@app.get("/healthz", include_in_schema=False)
def healthz(db: DbSession):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    if _is_htmx(request):
        return Response(headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
    if _is_htmx(request):
        # htmx doesn't swap error statuses, so send the message as a normal fragment.
        return HTMLResponse(f'<p class="text-sm font-medium text-pencil">{escape(exc.message)}</p>')
    return render(request, "error.html", status_code=exc.status_code, message=exc.message)
