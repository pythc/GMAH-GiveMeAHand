"""Loader for Agent Skills directories."""

from pathlib import Path

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    name: str
    description: str
    path: Path
    body_loaded: bool = False
    body: str | None = None
    references: list[Path] = Field(default_factory=list)
    scripts: list[Path] = Field(default_factory=list)


class SkillLoader:
    """Discover `SKILL.md` files and load them progressively."""

    def __init__(self, skills_root: str | Path) -> None:
        self.skills_root = Path(skills_root)

    def discover(self) -> list[SkillMetadata]:
        skills: list[SkillMetadata] = []
        if not self.skills_root.exists():
            return skills
        for skill_file in sorted(self.skills_root.glob("*/SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            skills.append(self._metadata_from_text(skill_file, text, load_body=False))
        return skills

    def load(self, skill_name: str) -> SkillMetadata:
        for skill in self.discover():
            if skill.name == skill_name:
                text = skill.path.read_text(encoding="utf-8")
                return self._metadata_from_text(skill.path, text, load_body=True)
        raise FileNotFoundError(f"skill not found: {skill_name}")

    def _metadata_from_text(self, path: Path, text: str, *, load_body: bool) -> SkillMetadata:
        name = path.parent.name
        description = ""
        for line in text.splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip()
            if name and description:
                break
        references_dir = path.parent / "references"
        scripts_dir = path.parent / "scripts"
        references = sorted(references_dir.glob("*")) if references_dir.exists() else []
        scripts = sorted(scripts_dir.glob("*")) if scripts_dir.exists() else []
        return SkillMetadata(
            name=name,
            description=description or f"Skill from {path.parent.name}",
            path=path,
            body_loaded=load_body,
            body=text if load_body else None,
            references=references,
            scripts=scripts,
        )
