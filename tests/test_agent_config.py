from unittest import TestCase

from agent_config import AgentConfigError, load_agent, render_agent


class AgentConfigTest(TestCase):
    def test_loads_model_and_thinking_from_the_code_registry(self) -> None:
        config = load_agent("social-post-editor")

        self.assertEqual(config.model, "gpt-5.6-luna")
        self.assertEqual(config.thinking, "xhigh")
        self.assertEqual(config.verbosity, "low")
        self.assertIn("You are the social media editor", config.instructions)

    def test_registers_every_worker_agent(self) -> None:
        for name in ("social-post-editor", "performance-analyst", "image-renderer"):
            config = load_agent(name)
            self.assertEqual(config.name, name)
            self.assertTrue(config.instructions.strip())
            self.assertTrue(config.model.strip())

    def test_renders_dynamic_values_without_leaving_placeholders(self) -> None:
        rendered = render_agent(
            "social-post-editor",
            {
                "topic": "Test topic",
                "performance_guidance": "No data yet.",
                "available_images": "- No reference images available.",
                "contact_facts": "- No contact info.",
            },
        )

        self.assertIn("Test topic", rendered)
        self.assertNotIn("{{", rendered)
        self.assertIn("Editorial brief:", rendered)

    def test_rejects_missing_template_values(self) -> None:
        with self.assertRaisesRegex(AgentConfigError, "topic"):
            render_agent("social-post-editor", {})

    def test_rejects_unknown_agents_with_available_names(self) -> None:
        with self.assertRaisesRegex(AgentConfigError, "performance-analyst"):
            load_agent("nonexistent")
