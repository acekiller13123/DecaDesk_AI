from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlmodel import Session, select

from app.models import ActionStatus, AuditLog, License, LicenseStatus, User, UserLicense, UserRole, UserStatus


ROLE_ACTIONS = {
    UserRole.SUPER_ADMIN: {"reset_password", "assign_license", "change_status", "create_user", "view_logs"},
    UserRole.IT_SUPPORT: {"reset_password", "assign_license", "change_status", "create_user", "view_logs"},
    UserRole.HR_ADMIN: {"create_user", "change_status", "view_logs"},
    UserRole.VIEWER: set(),
}


def can_perform(role: UserRole, action: str) -> bool:
    return action in ROLE_ACTIONS.get(role, set())


def log_action(
    session: Session,
    action_type: str,
    target: str,
    status: ActionStatus = ActionStatus.SUCCESS,
    details: dict[str, Any] | None = None,
    actor: str = "DecaDesk AI",
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action_type=action_type,
        target=target,
        status=status,
        details=details or {},
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_users(session: Session, query: str = "", status: str = "") -> list[User]:
    statement = select(User)
    if query:
        like = f"%{query.lower()}%"
        statement = statement.where((User.email.ilike(like)) | (User.name.ilike(like)))
    if status:
        statement = statement.where(User.status == status)
    statement = statement.order_by(User.created_at.desc())
    return list(session.exec(statement).all())


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()


def get_user_licenses(session: Session, user_id: int) -> list[dict[str, Any]]:
    assignments = session.exec(select(UserLicense).where(UserLicense.user_id == user_id)).all()
    licenses = []
    for assignment in assignments:
        license_record = session.get(License, assignment.license_id)
        if not license_record:
            continue
        licenses.append(
            {
                "code": license_record.code,
                "name": license_record.name,
                "status": assignment.status,
                "assigned_at": assignment.assigned_at,
            }
        )
    return licenses


def assign_license(session: Session, user: User, license_code: str) -> None:
    license_record = session.exec(select(License).where(License.code == license_code)).first()
    if not license_record:
        raise ValueError(f"Unknown license {license_code}")

    existing = session.exec(
        select(UserLicense).where(
            UserLicense.user_id == user.id,
            UserLicense.license_id == license_record.id,
            UserLicense.status == LicenseStatus.ASSIGNED,
        )
    ).first()
    if existing:
        return

    assignment = UserLicense(user_id=user.id, license_id=license_record.id, status=LicenseStatus.ASSIGNED)
    session.add(assignment)
    session.commit()


def revoke_license(session: Session, user: User, license_code: str) -> bool:
    license_record = session.exec(select(License).where(License.code == license_code)).first()
    if not license_record:
        return False

    assignment = session.exec(
        select(UserLicense).where(
            UserLicense.user_id == user.id,
            UserLicense.license_id == license_record.id,
            UserLicense.status == LicenseStatus.ASSIGNED,
        )
    ).first()
    if not assignment:
        return False

    assignment.status = LicenseStatus.REVOKED
    assignment.revoked_at = datetime.utcnow()
    session.add(assignment)
    session.commit()
    return True


def create_user(
    session: Session,
    name: str,
    email: str,
    department: str,
    role: UserRole,
    license_codes: Iterable[str] | None = None,
) -> User:
    user = User(name=name, email=email, department=department, role=role, status=UserStatus.ACTIVE)
    session.add(user)
    session.commit()
    session.refresh(user)
    for code in license_codes or []:
        assign_license(session, user, code)
    return user


def reset_password(session: Session, user: User) -> str:
    temporary_password = f"Temp-{user.id or 0}-{datetime.utcnow().strftime('%H%M%S')}"
    user.temporary_password = temporary_password
    session.add(user)
    session.commit()
    return temporary_password


def set_user_status(session: Session, user: User, status: UserStatus) -> User:
    user.status = status
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def users_inactive_for_days(session: Session, days: int) -> list[User]:
    threshold = datetime.utcnow() - timedelta(days=days)
    statement = select(User).where(User.last_login_at <= threshold, User.status != UserStatus.DISABLED)
    return list(session.exec(statement).all())

