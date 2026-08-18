from pathlib import Path
from unittest import TestCase

from agent_config import AgentConfigError, load_agent, render_agent

AGENTS = Path(__file__).parents[1] / "agents"


class AgentConfigTest(TestCase):
    def test_loads_frontmatter_and_model_thinking_suffix(self) -> None:
        config = load_agent("social-post-editor", directory=AGENTS)

        self.assertEqual(config.model, "gpt-5.6-luna")
        self.assertEqual(config.thinking, "xhigh")
        self.assertEqual(config.verbosity, "low")
        self.assertIn("You are the social media editor", config.instructions)

    def test_renders_dynamic_values_without_leaving_placeholders(self) -> None:
        rendered = render_agent(
            "performance-analyst",
            {"content_brief": "Be useful and specific."},
            directory=AGENTS,
        )

        self.assertIn("Editorial brief:\nBe useful and specific.", rendered)
        self.assertNotIn("{{content_brief}}", rendered)

    def test_rejects_missing_template_values(self) -> None:
        with self.assertRaisesRegex(AgentConfigError, "content_brief"):
            render_agent("performance-analyst", {}, directory=AGENTS)

    def test_rejects_unknown_frontmatter_keys(self) -> None:
        path = AGENTS / "invalid.md"
        path.write_text(
            "---\ndescription: Invalid\nmodel: example#high\nowner: test\n---\nPrompt\n",
            encoding="utf-8",
        )
        self.addCleanup(path.unlink)

        with self.assertRaisesRegex(AgentConfigError, "owner"):
            load_agent("invalid", directory=AGENTS)
