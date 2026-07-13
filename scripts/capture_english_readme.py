from __future__ import annotations

from pathlib import Path

from ai_novel_studio.app import create_application  # noqa: E402
from ai_novel_studio.ui.demo_data import (  # noqa: E402
    DemoBrief,
    DemoChapter,
    DemoCharacter,
    DemoMessage,
    DemoVolume,
    WorkspaceDemoData,
)
from ai_novel_studio.ui.i18n import Language, language_manager  # noqa: E402
from ai_novel_studio.ui.main_window import MainWindow  # noqa: E402
from ai_novel_studio.ui.pages.detached_chat_window import DetachedChatWindow  # noqa: E402
from ai_novel_studio.ui.pages.memory_window import MemoryWindow  # noqa: E402
from ai_novel_studio.ui.pages.settings_dialog import SettingsDialog  # noqa: E402
from ai_novel_studio.ui.pages.style_rules_window import StyleRulesWindow  # noqa: E402
from ai_novel_studio.ui.theme import application_stylesheet  # noqa: E402


def english_demo() -> WorkspaceDemoData:
    chapters = (
        DemoChapter("chapter-1", "Chapter 1", "Visitor on a Snowy Night", 3268, "Confirmed"),
        DemoChapter("chapter-2", "Chapter 2", "The Unsent Letter", 2984, "Editing"),
        DemoChapter("chapter-3", "Chapter 3", "Bells of the Old City", 0, "Not started"),
    )
    return WorkspaceDemoData(
        project_title="Letters from Mist Harbor",
        current_volume="Volume I · Tides",
        volumes=(DemoVolume("volume-1", "Volume I · Tides", chapters),),
        characters=(
            DemoCharacter(
                "character-lin",
                "Lin Mo",
                "Alert, but affected by memories of home",
                "Learn whether his missing brother is still alive",
                "Enter the old harbor archive without alerting the investigators",
                "Received an unsigned letter using his brother's old code",
            ),
        ),
        messages=(
            DemoMessage(
                "assistant",
                "Let the letter trigger action, but do not confirm the sender's identity yet.",
            ),
            DemoMessage(
                "user",
                "Keep the doubt, while letting Lin Mo choose to investigate the old harbor.",
            ),
            DemoMessage(
                "assistant",
                "Focus on his choice to approach the truth despite recognizing the trap.",
            ),
        ),
        brief=DemoBrief(
            status="Draft",
            fingerprint="brief-demo-en-a31f",
            warnings=("The source of the bell-tower record has not been confirmed",),
            sources=("Current requirements", "Author outline", "Previous chapter"),
            sections=(
                ("Dramatic purpose", "Move Lin Mo from waiting to active investigation."),
                ("Required events", "The letter appears; Lin Mo identifies the code."),
                ("Knowledge boundary", "Lin Mo does not know the sender's identity."),
                ("Style", "Close third person; restrained emotion."),
            ),
        ),
        chapter_requirement=(
            "Lin Mo receives an unsigned letter using his brother's old code. Keep the sender "
            "unknown and end with his decision to investigate the old harbor."
        ),
        generated_requirement="",
        chapter_text=(
            "The snow only began to thicken after dusk.\n\n"
            "When Lin Mo opened the door, an envelope lay just inside the threshold. "
            "There was no signature, only an ink mark blurred by rain."
        ),
        memory_tabs=(
            (
                "Compressed history",
                "Chapter 1: Lin Mo returned to Mist Harbor and found signs of entry.",
            ),
            (
                "Character state",
                "Lin Mo is alert and determined to learn what happened to his brother.",
            ),
            ("Character knowledge", "Lin Mo recognizes the code but does not know the sender."),
            ("Reader knowledge", "The reader saw an unknown figure deliver a letter."),
            ("Canon", "The old bell tower has been closed since the fire twelve years ago."),
            ("Narrative clues", "CL-04 is genuine; CL-07 is an author-locked misdirection."),
        ),
        style_rules=(
            ("Book voice", "Restrained close third person", "Author locked"),
            ("Character voice", "Lin Mo avoids directly admitting fear", "Author locked"),
            ("Avoid", "Do not overuse silent pauses", "Once per chapter"),
        ),
        audit_findings=(
            ("Deterministic", "Repeated action", "The same gesture appears four times."),
            ("Model", "Knowledge boundary", "Paragraph two may reveal information too early."),
        ),
    )


def capture(window: object, destination: Path) -> None:
    if not hasattr(window, "show") or not hasattr(window, "grab"):
        raise TypeError("capture target must be a Qt widget")
    window.show()
    app = create_application([])
    app.processEvents()
    language_manager().apply(window)
    app.processEvents()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(destination), "PNG"):
        raise RuntimeError(f"failed to save screenshot: {destination}")
    window.close()


def main() -> int:
    app = create_application([])
    app.setStyleSheet(application_stylesheet())
    manager = language_manager()
    manager.set_language(Language.ENGLISH)
    manager.install(app)
    data = english_demo()
    output = Path(__file__).resolve().parents[1] / "docs" / "assets" / "product-overview-en"

    main_window = MainWindow()
    main_window.resize(1440, 900)
    capture(main_window, output / "01-main-workspace.png")

    memory = MemoryWindow(data)
    memory.resize(1200, 800)
    capture(memory, output / "02-memory-library.png")

    style = StyleRulesWindow(data)
    style.resize(1100, 760)
    capture(style, output / "03-style-system.png")

    settings = SettingsDialog()
    settings.tabs.setCurrentIndex(0)
    settings.resize(920, 780)
    capture(settings, output / "04-model-settings.png")

    chat = DetachedChatWindow(data.messages)
    chat.resize(760, 820)
    capture(chat, output / "05-plot-chat.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
