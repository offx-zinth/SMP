from __future__ import annotations

import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.markdown import Markdown

from vibecoder.agent.orchestrator_async import AsyncAgent
from vibecoder.context import AppContext


class AsyncVibeRepl:
    """Interactive async dashboard for streaming VibeCoder sessions."""

    def __init__(self, app_context: AppContext, orchestrator: AsyncAgent) -> None:
        self.context = app_context
        self.console = app_context.console
        self.orchestrator = orchestrator

    async def main_loop(self) -> None:
        if not self.context.config.gemini_api_key:
            self.console.print("[red]Missing Gemini API key.[/red]")
            return

        session: PromptSession[str] = PromptSession(
            multiline=True,
            is_async=True,
            key_bindings=self._build_key_bindings(),
        )
        self.console.print("[bold green]VibeCoder Async[/bold green] ready. Commands: /exit /undo")

        while True:
            with patch_stdout():
                prompt = (await session.prompt_async("(vibe-async)> ")).strip()
            if not prompt:
                continue

            if prompt == "/exit":
                self.console.print("[cyan]Goodbye.[/cyan]")
                break
            if prompt == "/undo":
                self.console.print("[yellow]Undo is not wired in async shell yet.[/yellow]")
                continue

            streamed = ""
            async for chunk in self.orchestrator.chat_stream(prompt):
                streamed += chunk
            self.console.print(Markdown(streamed or "Completed."))

    @staticmethod
    def _build_key_bindings() -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("escape", "enter")
        def submit(event) -> None:  # type: ignore[no-untyped-def]
            event.current_buffer.validate_and_handle()

        return bindings


async def run_repl_async(context: AppContext) -> None:
    orchestrator = AsyncAgent(app_context=context)
    repl = AsyncVibeRepl(app_context=context, orchestrator=orchestrator)
    await repl.main_loop()


if __name__ == "__main__":
    from vibecoder.config import Config

    asyncio.run(run_repl_async(AppContext.from_config(Config())))
