from __future__ import annotations

import base64
import os
from typing import Any

from openai import OpenAI
from playwright.async_api import Browser, Page, async_playwright


class BrowserAgent:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", headless: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self._playwright = None
        self.browser: Browser | None = None
        self.page: Page | None = None
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()

    async def stop(self) -> None:
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def goto(self, path: str) -> None:
        assert self.page is not None
        await self.page.goto(f"{self.base_url}{path}", wait_until="networkidle")

    async def open_users_page(self, role: str) -> None:
        await self.goto(f"/users?role={role}")

    async def open_create_user_page(self, role: str) -> None:
        await self.goto(f"/users/new?role={role}")

    async def search_user_by_email(self, email: str) -> bool:
        assert self.page is not None
        field = self.page.get_by_role("textbox", name="Search name or email")
        await field.fill(email)
        await field.press("Enter")
        await self.page.wait_for_load_state("networkidle")
        return await self.page.get_by_text(email).count() > 0

    async def open_user_profile(self, email: str, role: str) -> bool:
        assert self.page is not None
        row = self.page.locator("tr", has_text=email)
        if await row.count() == 0:
            return False
        await row.get_by_role("link", name="View").click()
        await self.page.wait_for_load_state("networkidle")
        return True

    async def click_reset_password(self) -> None:
        assert self.page is not None
        await self.page.get_by_role("button", name="Reset password").click()
        await self.page.wait_for_load_state("networkidle")

    async def create_user(self, role: str, payload: dict[str, Any], license_codes: list[str]) -> None:
        assert self.page is not None
        await self.open_create_user_page(role)
        await self.page.get_by_label("Name").fill(payload["name"])
        await self.page.get_by_label("Email").fill(payload["email"])
        await self.page.get_by_label("Department").fill(payload["department"])
        await self.page.get_by_label("Role").select_option(payload.get("role", "VIEWER"))
        for code in license_codes:
            await self.page.get_by_label(self._license_display_name(code)).check()
        await self.page.get_by_role("button", name="Create user").click()
        await self.page.wait_for_load_state("networkidle")

    async def assign_license(self, license_code: str) -> None:
        assert self.page is not None
        await self.page.get_by_label("License").select_option(label=self._license_display_name(license_code))
        await self.page.get_by_label("Operation").select_option("assign")
        await self.page.get_by_role("button", name="Apply").click()
        await self.page.wait_for_load_state("networkidle")

    async def update_status(self, status: str) -> None:
        assert self.page is not None
        await self.page.get_by_label("Status").select_option(status)
        await self.page.get_by_role("button", name="Update status").click()
        await self.page.wait_for_load_state("networkidle")

    async def verify_toast_or_content(self, text: str) -> bool:
        assert self.page is not None
        return await self.page.get_by_text(text).count() > 0

    async def verify_license_chip(self, text: str) -> bool:
        assert self.page is not None
        return await self.page.locator(".chip", has_text=text).count() > 0

    async def verify_status_badge(self, text: str) -> bool:
        assert self.page is not None
        return await self.page.get_by_text(text).count() > 0

    async def capture_observation(self, tag: str = "state") -> str:
        assert self.page is not None
        safe_tag = "".join(ch for ch in tag.lower() if ch.isalnum() or ch in ("-", "_")) or "state"
        path = f"tmp_{safe_tag}.png"
        await self.page.screenshot(path=path, full_page=True)
        return path

    async def suggest_action_from_screenshot(self, goal: str, candidates: list[str]) -> str | None:
        # CUA-style assist: infer best next action from current screenshot.
        if not self.client or not candidates:
            return None
        screenshot_path = await self.capture_observation("cua_observe")
        with open(screenshot_path, "rb") as image_file:
            b64_image = base64.b64encode(image_file.read()).decode("utf-8")
        prompt = (
            f"Goal: {goal}\n"
            f"Choose exactly one action from this list: {candidates}.\n"
            "Return only the exact action string."
        )
        try:
            response = self.client.responses.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": f"data:image/png;base64,{b64_image}"},
                        ],
                    }
                ],
            )
            text = (response.output_text or "").strip()
            return text if text in candidates else None
        except Exception:
            return None

    def _license_display_name(self, code: str) -> str:
        mapping = {
            "MICROSOFT_365": "Microsoft 365",
            "SLACK": "Slack",
            "NOTION": "Notion",
        }
        return mapping.get(code, code)

