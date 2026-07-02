from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    root: Path
    manifest: Path
    database: Path
    manuscript: Path
    assets: Path
    exports: Path
    backups: Path
    pipeline: Path
    history: Path
    trash: Path
    reports: Path

    @classmethod
    def at(cls, root: Path) -> "ProjectLayout":
        resolved = root.resolve()
        pipeline = resolved / ".ai_pipeline"
        return cls(
            root=resolved,
            manifest=resolved / "project.json",
            database=resolved / "project.sqlite3",
            manuscript=resolved / "manuscript",
            assets=resolved / "assets",
            exports=resolved / "exports",
            backups=resolved / "backups",
            pipeline=pipeline,
            history=pipeline / "history",
            trash=pipeline / "trash",
            reports=pipeline / "migration_reports",
        )

    def create_directories(self) -> None:
        for path in (
            self.manuscript,
            self.assets,
            self.exports,
            self.backups,
            self.history,
            self.trash,
            self.reports,
            self.pipeline / "checkpoints",
            self.pipeline / "manifests",
            self.pipeline / "audit_reports",
            self.pipeline / "recovery",
        ):
            path.mkdir(parents=True, exist_ok=True)
