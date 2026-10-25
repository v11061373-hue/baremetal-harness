from baremetal_harness.skills.rules import ProjectRulesProvider, parse_project_rules


def test_parse_rules_reads_version_and_body() -> None:
    rules = parse_project_rules("---\nversion: 1.2.3\n---\nnever force-push")
    assert rules.version == "1.2.3"
    assert rules.content == "never force-push"


async def test_provider_returns_required_source(tmp_path) -> None:
    (tmp_path / ".baremetal_harness").mkdir()
    (tmp_path / ".baremetal_harness" / "AGENTS.md").write_text(
        "---\nversion: 0.1.0\n---\nrun tests before commit"
    )
    provider = ProjectRulesProvider.load(tmp_path)
    (source,) = await provider.build("hello")
    assert source.source_id == "project-rules"
    assert source.required is True


async def test_provider_abstains_when_missing(tmp_path) -> None:
    provider = ProjectRulesProvider.load(tmp_path)
    assert await provider.build("hello") == ()
