from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from app.db import get_session, password_resets_today
from app.models import ActionStatus, AuditLog, License, LicenseStatus, User, UserLicense, UserRole, UserStatus
from app.services import (
    assign_license,
    can_perform,
    create_user,
    get_user_by_email,
    get_user_licenses,
    list_users,
    log_action,
    reset_password,
    revoke_license,
    set_user_status,
)


router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


def current_role(request: Request) -> UserRole:
    role = request.query_params.get("role", "IT_SUPPORT")
    try:
        return UserRole(role)
    except ValueError:
        return UserRole.IT_SUPPORT


def require_action(request: Request, action: str) -> UserRole:
    role = current_role(request)
    if not can_perform(role, action):
        raise HTTPException(status_code=403, detail=f"{role.value} cannot perform {action}")
    return role


def base_context(request: Request, **kwargs: Any) -> dict[str, Any]:
    return {"request": request, "current_role": current_role(request), **kwargs}


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    total_users = session.exec(select(func.count(User.id))).one()
    active_users = session.exec(select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)).one()
    inactive_users = session.exec(select(func.count(User.id)).where(User.status != UserStatus.ACTIVE)).one()
    licenses = session.exec(select(License)).all()
    license_usage = []
    for license_record in licenses:
        count = session.exec(
            select(func.count(UserLicense.id)).where(
                UserLicense.license_id == license_record.id,
                UserLicense.status == LicenseStatus.ASSIGNED,
            )
        ).one()
        license_usage.append({"product": license_record.name, "count": count})
    context = base_context(
        request,
        total_users=total_users,
        active_users=active_users,
        inactive_users=inactive_users,
        password_resets_today=password_resets_today(session),
        license_usage=license_usage,
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    session: Session = Depends(get_session),
):
    users = list_users(session, q, status)
    context = base_context(request, users=users, query=q, status_filter=status, user_statuses=list(UserStatus))
    return templates.TemplateResponse(request, "users_list.html", context)


@router.get("/users/new", response_class=HTMLResponse)
async def create_user_page(request: Request, session: Session = Depends(get_session)):
    licenses = session.exec(select(License)).all()
    context = base_context(request, roles=list(UserRole), licenses=licenses)
    return templates.TemplateResponse(request, "create_user.html", context)


@router.post("/users/new")
async def create_user_action(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    department: str = Form(...),
    role: UserRole = Form(...),
    licenses: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    require_action(request, "create_user")
    existing = get_user_by_email(session, email)
    if existing:
        return RedirectResponse(url=f"/users?role={current_role(request).value}&toast=User already exists", status_code=303)
    user = create_user(session, name=name, email=email, department=department, role=role, license_codes=licenses)
    log_action(
        session,
        "CREATE_USER",
        user.email,
        ActionStatus.SUCCESS,
        {"department": department, "role": role.value, "licenses": licenses},
    )
    return RedirectResponse(url=f"/users/{user.id}?role={current_role(request).value}&toast=User created successfully", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(request: Request, user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    context = base_context(
        request,
        user=user,
        user_licenses=get_user_licenses(session, user_id),
        licenses=session.exec(select(License)).all(),
        roles=list(UserRole),
    )
    return templates.TemplateResponse(request, "user_detail.html", context)


@router.post("/users/{user_id}/reset-password")
async def reset_password_action(request: Request, user_id: int, session: Session = Depends(get_session)):
    require_action(request, "reset_password")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    temp_password = reset_password(session, user)
    log_action(
        session,
        "PASSWORD_RESET",
        user.email,
        ActionStatus.SUCCESS,
        {"temporary_password": temp_password, "verified": True},
    )
    return RedirectResponse(
        url=f"/users/{user_id}?role={current_role(request).value}&toast=Password reset completed",
        status_code=303,
    )


@router.post("/users/{user_id}/status")
async def update_status_action(
    request: Request,
    user_id: int,
    status: UserStatus = Form(...),
    session: Session = Depends(get_session),
):
    require_action(request, "change_status")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    set_user_status(session, user, status)
    log_action(session, "UPDATE_STATUS", user.email, ActionStatus.SUCCESS, {"status": status.value})
    return RedirectResponse(
        url=f"/users/{user_id}?role={current_role(request).value}&toast=User status updated",
        status_code=303,
    )


@router.post("/users/{user_id}/licenses")
async def update_license_action(
    request: Request,
    user_id: int,
    license_code: str = Form(...),
    operation: str = Form(...),
    session: Session = Depends(get_session),
):
    require_action(request, "assign_license")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if operation == "assign":
        assign_license(session, user, license_code)
        log_action(session, "ASSIGN_LICENSE", user.email, ActionStatus.SUCCESS, {"license": license_code})
        toast = "License assigned successfully"
    else:
        revoke_license(session, user, license_code)
        log_action(session, "REVOKE_LICENSE", user.email, ActionStatus.SUCCESS, {"license": license_code})
        toast = "License revoked successfully"

    return RedirectResponse(url=f"/users/{user_id}?role={current_role(request).value}&toast={toast}", status_code=303)


@router.get("/licenses", response_class=HTMLResponse)
async def licenses_page(request: Request, session: Session = Depends(get_session)):
    licenses = session.exec(select(License)).all()
    rows = []
    for license_record in licenses:
        assigned = session.exec(
            select(func.count(UserLicense.id)).where(
                UserLicense.license_id == license_record.id,
                UserLicense.status == LicenseStatus.ASSIGNED,
            )
        ).one()
        rows.append({"license": license_record, "assigned": assigned})
    context = base_context(request, license_rows=rows)
    return templates.TemplateResponse(request, "licenses.html", context)


@router.get("/audit-logs", response_class=HTMLResponse)
async def audit_logs_page(
    request: Request,
    target: str = Query(default=""),
    action: str = Query(default=""),
    session: Session = Depends(get_session),
):
    statement = select(AuditLog).order_by(AuditLog.created_at.desc())
    if target:
        statement = statement.where(AuditLog.target.ilike(f"%{target}%"))
    if action:
        statement = statement.where(AuditLog.action_type == action)
    logs = list(session.exec(statement).all())
    context = base_context(request, logs=logs, target_filter=target, action_filter=action)
    return templates.TemplateResponse(request, "audit_logs.html", context)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html", base_context(request, chat_messages=[]))


@router.post("/api/chat/execute")
async def chat_execute(
    request: Request,
    payload: dict[str, Any],
    session: Session = Depends(get_session),
):
    planner = request.app.state.planner
    executor = request.app.state.executor
    message = payload.get("message", "").strip()
    if not message:
        return JSONResponse({"summary": "Please provide a request.", "steps": [], "logs": []}, status_code=400)

    plan = await planner.plan(message=message, role=current_role(request))
    result = await executor.execute(plan=plan, session=session, role=current_role(request))
    return JSONResponse(result)

