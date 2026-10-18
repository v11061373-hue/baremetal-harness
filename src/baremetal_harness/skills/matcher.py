import re
from dataclasses import dataclass

from baremetal_harness.skills.types import Skill, SkillMatch


def _terms(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


@dataclass(frozen=True, slots=True)
class _MatchQuery:
    prompt: str
    explicit: str | None

    def select(self, skills: tuple[Skill, ...]) -> tuple[SkillMatch, ...]:
        matches = []
        prompt = self.prompt.casefold()
        prompt_terms = _terms(prompt)
        for skill in skills:
            if self.explicit is not None:
                score = 100 if skill.name == self.explicit else 0
                reason = "explicit selection"
            else:
                trigger_hits = sum(
                    1
                    for trigger in skill.triggers
                    if re.search(
                        rf"(?<!\w){re.escape(trigger.casefold())}(?!\w)",
                        prompt,
                    )
                )
                overlap = len(prompt_terms & _terms(skill.description))
                score = 20 * trigger_hits + 2 * overlap
                reason = "trigger" if trigger_hits else "description overlap"
            if score >= 2:
                matches.append(SkillMatch(skill, score, reason))
        matches.sort(key=lambda item: (-item.score, item.skill.name))
        return tuple(matches[:1] if self.explicit else matches[:4])


class SkillMatcher:
    def match(self, prompt: str) -> _MatchQuery:
        explicit_match = re.fullmatch(r"\s*/skill\s+([a-z][a-z0-9-]{0,63})\s*", prompt)
        return _MatchQuery(
            prompt,
            explicit_match.group(1) if explicit_match else None,
        )
