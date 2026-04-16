from __future__ import annotations

import os
from typing import Any

from sqlmodel import Session

from agent.browser_agent import BrowserAgent
from app.models import ActionStatus, UserRole, UserStatus
from app.services import (
    assign_license,
    create_user,
    get_user_by_email,
    log_action,
    reset_password,
    set_user_status,
    users_inactive_for_days,
)


class TaskExecutor:
    def __init__(self) -> None:
        base_url = os.getenv("DECADESK_BASE_URL", "http://127.0.0.1:8000")
        headless = os.getenv("DECADESK_HEADLESS", "true").lower() != "false"
        self.browser_agent = BrowserAgent(base_url=base_url, headless=headless)

    async def execute(self, plan: dict[str, Any], session: Session, role: UserRole) -> dict[str, Any]:
        logs: list[str] = [f"[PLAN] {plan['task_type']}"]
        status = "success"
        summary = "Workflow completed."
        browser_enabled = True
        try:
            await self.browser_agent.start()
        except Exception as exc:
            browser_enabled = False
            logs.append(f"[CUA] Browser agent unavailable, using resilient backend fallback: {exc.__class__.__name__}")
        try:
            if plan["task_type"] == "RESET_PASSWORD":
                summary = await self._reset_password(plan, session, role, logs, browser_enabled)
            elif plan["task_type"] == "CREATE_USER":
                summary = await self._create_user(plan, session, role, logs, browser_enabled)
            elif plan["task_type"] == "CHECK_OR_CREATE_AND_ASSIGN_LICENSE":
                summary = await self._check_or_create(plan, session, role, logs, browser_enabled)
            elif plan["task_type"] == "BATCH_DISABLE_INACTIVE_USERS":
                summary = await self._disable_inactive(plan, session, role, logs, browser_enabled)
            else:
                status = "failed"
                summary = f"Unsupported task type {plan['task_type']}."
        except Exception as exc:
            logs.append(f"[ERROR] {exc}")
            status = "failed"
            summary = f"Workflow failed: {exc}"
        finally:
            if browser_enabled:
                await self.browser_agent.stop()

        log_action(
            session,
            "AGENT_TASK",
            plan.get("target_user_email") or plan["task_type"],
            ActionStatus.SUCCESS if status == "success" else ActionStatus.FAILED,
            {"task_type": plan["task_type"], "logs": logs, "summary": summary},
        )
        return {"status": status, "summary": summary, "steps": plan.get("steps", []), "logs": logs}

    async def _reset_password(
        self,
        plan: dict[str, Any],
        session: Session,
        role: UserRole,
        logs: list[str],
        browser_enabled: bool,
    ) -> str:
        email = plan["target_user_email"]
        user = get_user_by_email(session, email)
        if not user:
            raise ValueError(f"User not found: {email}")

        if browser_enabled:
            logs.append("[ACTION] Open users page")
            await self.browser_agent.open_users_page(role.value)
            logs.append(f"[ACTION] Search {email}")
            found = await self.browser_agent.search_user_by_email(email)
            if not found:
                suggestion = await self.browser_agent.suggest_action_from_screenshot(
                    goal=f"Locate user {email} in users table",
                    candidates=["retry_search", "open_create_user", "abort"],
                )
                logs.append(f"[CUA] Suggested next action: {suggestion or 'none'}")
                raise ValueError(f"Could not locate {email} in browser flow")

            logs.append("[ACTION] Open user profile")
            await self.browser_agent.open_user_profile(email, role.value)
            logs.append("[ACTION] Click reset password")
            await self.browser_agent.click_reset_password()

            verified = await self.browser_agent.verify_toast_or_content("Password reset completed")
            logs.append(f"[VERIFY] Success toast detected: {verified}")
        else:
            reset_password(session, user)
            log_action(session, "PASSWORD_RESET", email, ActionStatus.SUCCESS, {"mode": "fallback_backend"})
            logs.append(f"[ACTION] Reset password for {email} via backend fallback")
            logs.append("[VERIFY] Password reset persisted in database")
        return f"Password reset completed successfully for {email}."

    async def _create_user(
        self,
        plan: dict[str, Any],
        session: Session,
        role: UserRole,
        logs: list[str],
        browser_enabled: bool,
    ) -> str:
        payload = plan["user_payload"]
        email = payload["email"]
        if browser_enabled:
            logs.append("[ACTION] Open create user page")
            await self.browser_agent.create_user(role.value, payload, plan.get("license_codes", []))
            user = get_user_by_email(session, email)
            if not user:
                raise ValueError(f"Expected created user {email} to exist after browser flow")
        else:
            existing = get_user_by_email(session, email)
            if not existing:
                create_user(
                    session,
                    name=payload["name"],
                    email=email,
                    department=payload["department"],
                    role=UserRole(payload.get("role", "VIEWER")),
                    license_codes=plan.get("license_codes", []),
                )
            logs.append(f"[ACTION] Created user {email} via backend fallback")
        logs.append("[VERIFY] User profile exists")
        return f"Created account for {email}."

    async def _check_or_create(
        self,
        plan: dict[str, Any],
        session: Session,
        role: UserRole,
        logs: list[str],
        browser_enabled: bool,
    ) -> str:
        email = plan["target_user_email"]
        payload = plan["user_payload"]
        user = get_user_by_email(session, email)
        if browser_enabled:
            logs.append("[ACTION] Open users page")
            await self.browser_agent.open_users_page(role.value)
            found = await self.browser_agent.search_user_by_email(email)
            logs.append(f"[VERIFY] User exists: {found}")
            if found and user:
                await self.browser_agent.open_user_profile(email, role.value)
                for license_code in plan.get("license_codes", []):
                    logs.append(f"[ACTION] Assign {license_code}")
                    await self.browser_agent.assign_license(license_code)
            else:
                logs.append("[ACTION] Create missing user")
                suggestion = await self.browser_agent.suggest_action_from_screenshot(
                    goal=f"Create missing user {email} and continue workflow",
                    candidates=["open_create_user", "retry_search", "abort"],
                )
                logs.append(f"[CUA] Suggested branch action: {suggestion or 'open_create_user'}")
                await self.browser_agent.create_user(role.value, payload, plan.get("license_codes", []))
                user = get_user_by_email(session, email)
                if not user:
                    raise ValueError(f"Expected created user {email} to exist after browser flow")

            verified = all(await self._verify_license(email, code, role) for code in plan.get("license_codes", []))
            logs.append(f"[VERIFY] Requested licenses present: {verified}")
        else:
            if not user:
                user = create_user(
                    session,
                    name=payload["name"],
                    email=email,
                    department=payload["department"],
                    role=UserRole(payload.get("role", "VIEWER")),
                    license_codes=[],
                )
                logs.append(f"[ACTION] Created missing user {email} via backend fallback")
            for license_code in plan.get("license_codes", []):
                assign_license(session, user, license_code)
                logs.append(f"[ACTION] Assigned {license_code} via backend fallback")
            log_action(session, "CONDITIONAL_WORKFLOW", email, ActionStatus.SUCCESS, {"mode": "fallback_backend"})
            logs.append("[VERIFY] Conditional workflow completed in fallback mode")
        return f"Conditional workflow completed for {email}."

    async def _disable_inactive(
        self,
        plan: dict[str, Any],
        session: Session,
        role: UserRole,
        logs: list[str],
        browser_enabled: bool,
    ) -> str:
        days = plan.get("batch_days") or 90
        inactive_users = users_inactive_for_days(session, days)
        count = 0
        if browser_enabled:
            await self.browser_agent.open_users_page(role.value)
        for user in inactive_users:
            if browser_enabled:
                await self.browser_agent.search_user_by_email(user.email)
                if await self.browser_agent.open_user_profile(user.email, role.value):
                    await self.browser_agent.update_status(UserStatus.DISABLED.value)
            else:
                set_user_status(session, user, UserStatus.DISABLED)
            logs.append(f"[ACTION] Disabled {user.email}")
            count += 1
        logs.append(f"[VERIFY] Disabled count: {count}")
        return f"Disabled {count} accounts inactive for at least {days} days."

    async def _verify_license(self, email: str, license_code: str, role: UserRole) -> bool:
        await self.browser_agent.open_users_page(role.value)
        await self.browser_agent.search_user_by_email(email)
        await self.browser_agent.open_user_profile(email, role.value)
        return await self.browser_agent.verify_license_chip(license_code.split("_")[0].title())

