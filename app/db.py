from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, func, select

from app.models import (
    ActionStatus,
    AuditLog,
    License,
    LicenseStatus,
    User,
    UserLicense,
    UserRole,
    UserStatus,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "decadesk.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def get_session():
    with Session(engine) as session:
        yield session


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def seed_data() -> None:
    with Session(engine) as session:
        existing = session.exec(select(User)).first()
        if existing:
            return

        licenses = [
            License(code="MICROSOFT_365", name="Microsoft 365", description="Email, Office, Teams"),
            License(code="SLACK", name="Slack", description="Workspace messaging"),
            License(code="NOTION", name="Notion", description="Knowledge workspace"),
        ]
        session.add_all(licenses)
        session.commit()

        users = [
            User(
                name="John Carter",
                email="john@company.com",
                department="Engineering",
                role=UserRole.IT_SUPPORT,
                status=UserStatus.ACTIVE,
                last_login_at=datetime.utcnow() - timedelta(days=2),
            ),
            User(
                name="Alex Morgan",
                email="alex@company.com",
                department="Operations",
                role=UserRole.VIEWER,
                status=UserStatus.ACTIVE,
                last_login_at=datetime.utcnow() - timedelta(days=8),
            ),
            User(
                name="Priya Sharma",
                email="priya@company.com",
                department="Finance",
                role=UserRole.HR_ADMIN,
                status=UserStatus.INACTIVE,
                last_login_at=datetime.utcnow() - timedelta(days=93),
            ),
            User(
                name="Noah Wilson",
                email="noah@company.com",
                department="Sales",
                role=UserRole.VIEWER,
                status=UserStatus.INACTIVE,
                last_login_at=datetime.utcnow() - timedelta(days=124),
            ),
        ]
        session.add_all(users)
        session.commit()

        john = session.exec(select(User).where(User.email == "john@company.com")).one()
        alex = session.exec(select(User).where(User.email == "alex@company.com")).one()
        microsoft = session.exec(select(License).where(License.code == "MICROSOFT_365")).one()
        slack = session.exec(select(License).where(License.code == "SLACK")).one()

        session.add_all(
            [
                UserLicense(user_id=john.id, license_id=microsoft.id),
                UserLicense(user_id=alex.id, license_id=slack.id),
            ]
        )
        session.add_all(
            [
                AuditLog(
                    action_type="SEED",
                    target="system",
                    status=ActionStatus.SUCCESS,
                    details={"message": "Initial DecaDesk seed data created."},
                ),
                AuditLog(
                    action_type="PASSWORD_RESET",
                    target="john@company.com",
                    status=ActionStatus.SUCCESS,
                    details={"message": "Previous successful password reset for demo metrics."},
                ),
            ]
        )
        session.commit()


def reset_database() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    create_db_and_tables()
    seed_data()


def password_resets_today(session: Session) -> int:
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    statement = select(func.count(AuditLog.id)).where(
        AuditLog.action_type == "PASSWORD_RESET",
        AuditLog.created_at >= start_of_day,
    )
    return session.exec(statement).one()

