from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field

from agent.prompts import FEW_SHOT_EXAMPLE, SYSTEM_PROMPT
from app.models import UserRole


class TaskPlan(BaseModel):
    task_type: str
    target_user_email: str | None = None
    user_payload: dict[str, Any] = Field(default_factory=dict)
    license_codes: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    conditional_logic: list[dict[str, Any]] = Field(default_factory=list)
    expected_verifications: list[str] = Field(default_factory=list)
    batch_days: int | None = None


class PlannerAgent:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None

    async def plan(self, message: str, role: UserRole) -> dict[str, Any]:
        if self.client:
            try:
                completion = self.client.responses.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    input=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Current role: {role.value}\n{FEW_SHOT_EXAMPLE}\nUser request: {message}"},
                    ],
                )
                text = getattr(completion, "output_text", "").strip()
                parsed = TaskPlan.model_validate(json.loads(text))
                return parsed.model_dump()
            except Exception:
                pass
        return self._heuristic_plan(message, role).model_dump()

    def _heuristic_plan(self, message: str, role: UserRole) -> TaskPlan:
        lower = message.lower()
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", lower)
        email = email_match.group(0) if email_match else None
        license_codes = []
        for code, aliases in {
            "MICROSOFT_365": ["microsoft 365", "office 365", "m365"],
            "SLACK": ["slack"],
            "NOTION": ["notion"],
        }.items():
            if any(alias in lower for alias in aliases):
                license_codes.append(code)

        if "reset password" in lower:
            return TaskPlan(
                task_type="RESET_PASSWORD",
                target_user_email=email,
                steps=["open users page", "search user", "open profile", "reset password", "verify success"],
                expected_verifications=["success toast appears", "temporary password field updates"],
            )

        if "disable all" in lower and "inactive" in lower:
            days_match = re.search(r"(\d+)\s*days", lower)
            days = int(days_match.group(1)) if days_match else 90
            return TaskPlan(
                task_type="BATCH_DISABLE_INACTIVE_USERS",
                batch_days=days,
                steps=["open users page", "filter inactive users", "disable matching accounts", "verify count"],
                expected_verifications=["status badges change to disabled", "summary count matches actions"],
            )

        if "if not" in lower or "check if" in lower:
            return TaskPlan(
                task_type="CHECK_OR_CREATE_AND_ASSIGN_LICENSE",
                target_user_email=email,
                license_codes=license_codes,
                user_payload=self._extract_user_payload(message, email),
                steps=["open users page", "search user", "branch on existence", "create if missing", "assign licenses", "verify success"],
                conditional_logic=[
                    {
                        "condition": "user_exists",
                        "then_steps": ["open profile", "assign requested licenses"],
                        "else_steps": ["open create user form", "create user", "assign requested licenses"],
                    }
                ],
                expected_verifications=["user row exists", "license chips appear", "success toast appears"],
            )

        return TaskPlan(
            task_type="CREATE_USER",
            target_user_email=email,
            user_payload=self._extract_user_payload(message, email),
            license_codes=license_codes,
            steps=["open create user page", "fill form", "submit", "verify user created"],
            expected_verifications=["success toast appears", "user profile exists"],
        )

    def _extract_user_payload(self, message: str, email: str | None) -> dict[str, Any]:
        lower = message.lower()
        name = "Sarah"
        name_match = re.search(r"named\s+([a-zA-Z]+)", message)
        if name_match:
            name = name_match.group(1)
        department = "Engineering" if "engineering" in lower else "Operations"
        return {
            "name": name,
            "email": email or f"{name.lower()}@company.com",
            "department": department,
            "role": "VIEWER",
        }

