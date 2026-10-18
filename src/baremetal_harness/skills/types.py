from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    scope: str
    instructions: str
    source_id: str


@dataclass(frozen=True, slots=True)
class SkillMatch:
    skill: Skill
    score: int
    reason: str
