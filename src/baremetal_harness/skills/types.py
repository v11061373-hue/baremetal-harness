from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    scope: str
    instructions: str
    source_id: str
    version: str = "0.0.0"
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class SkillMatch:
    skill: Skill
    score: int
    reason: str
