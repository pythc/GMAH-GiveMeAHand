from pathlib import Path

import pytest

from agent_workflow.skills.loader import SkillLoader


def test_skill_loader_discovers_metadata() -> None:
    root = Path(__file__).resolve().parents[1] / "skills"
    skills = SkillLoader(root).discover()
    names = {skill.name for skill in skills}
    assert "grading-review" in names
    assert "qq-ops" in names
    assert all(skill.body_loaded is False for skill in skills)


def test_skill_loader_loads_body() -> None:
    root = Path(__file__).resolve().parents[1] / "skills"
    skill = SkillLoader(root).load("grading-review")
    assert skill.body_loaded is True
    assert skill.body is not None
    assert "Grading Review Skill" in skill.body


def test_skill_loader_rejects_missing_skill() -> None:
    root = Path(__file__).resolve().parents[1] / "skills"
    with pytest.raises(FileNotFoundError):
        SkillLoader(root).load("missing")
