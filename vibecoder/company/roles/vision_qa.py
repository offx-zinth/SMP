from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from google import genai
from pydantic import BaseModel

from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.company.roles.architect import BaseAgent

logger = logging.getLogger(__name__)


class VisionVerdict(BaseModel):
    status: str
    reasons: list[str]


class VisionQAAgent(BaseAgent):
    """Visual QA persona that validates UI changes with Playwright + Gemini Vision."""

    def __init__(self, *, bus: AsyncEventBus, gemini_api_key: str, artifacts_dir: Path) -> None:
        super().__init__(name="VisionQA", bus=bus)
        self._client = genai.Client(api_key=gemini_api_key).aio
        self._artifacts_dir = artifacts_dir
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

    def register(self) -> None:
        self.bus.subscribe("ticket_completed", self._on_ticket_completed)

    async def _on_ticket_completed(self, event: Event) -> None:
        ticket_id = str(event.payload.get("id", "unknown"))
        requirement = str(event.payload.get("requirement") or event.payload.get("description") or "")
        app_url = str(event.payload.get("app_url", "http://127.0.0.1:3000"))
        screenshot_path = self._artifacts_dir / f"{ticket_id}-screenshot.png"

        console_errors = await self._capture_ui_artifacts(app_url=app_url, screenshot_path=screenshot_path)
        verdict = await self._verify_with_vision(
            screenshot_path=screenshot_path,
            requirement=requirement,
            console_errors=console_errors,
        )

        topic = "qa_passed" if verdict.status.upper() == "PASS" else "bug_found"
        await self.bus.publish(
            Event(
                topic=topic,
                sender=self.name,
                payload={
                    "ticket_id": ticket_id,
                    "status": verdict.status,
                    "reasons": verdict.reasons,
                    "screenshot": str(screenshot_path),
                },
            )
        )

    async def _capture_ui_artifacts(self, *, app_url: str, screenshot_path: Path) -> list[str]:
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("playwright is not installed; VisionQA cannot run") from exc

        errors: list[str] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            page.on(
                "console",
                lambda msg: errors.append(msg.text)
                if msg.type.lower() in {"error", "warning"}
                else None,
            )
            await page.goto(app_url, wait_until="networkidle")
            await page.screenshot(path=str(screenshot_path), full_page=True)
            await browser.close()
        return errors

    async def _verify_with_vision(
        self,
        *,
        screenshot_path: Path,
        requirement: str,
        console_errors: list[str],
    ) -> VisionVerdict:
        image_bytes = screenshot_path.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        prompt = (
            "Does this UI match the requirements? Are there console errors? "
            "Return PASS or FAIL with reasons.\n\n"
            f"Requirements:\n{requirement}\n\n"
            f"Console errors/warnings:\n{console_errors}"
        )
        response = await self._client.models.generate_content(
            model="gemini-2.0-pro-vision",
            contents=[
                prompt,
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": image_b64,
                    }
                },
            ],
        )
        text = (response.text or "").strip()
        status = "PASS" if "PASS" in text.upper() and "FAIL" not in text.upper() else "FAIL"
        reasons = [line.strip("- ") for line in text.splitlines() if line.strip()][:8] or ["No rationale returned by model."]
        return VisionVerdict(status=status, reasons=reasons)
