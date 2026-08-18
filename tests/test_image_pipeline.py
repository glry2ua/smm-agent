import base64
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from brand.brand_context import ContactInfo
from images.image_pipeline import (
    R2ImageAssetStore,
    ReferenceImage,
    generate_and_save_image,
    generate_and_store_image,
    image_key,
)
from schemas import ImagePrompt
from settings import Settings


def prompt() -> ImagePrompt:
    return ImagePrompt(
        visual_type="typographic-educational",
        subject="A calm editorial guide to comparing neighborhoods",
        setting="Warm ivory studio backdrop",
        composition="Large serif headline with three minimal architectural details",
        headline="COMPARE THE WHOLE MOVE",
        supporting_text="Home, commute, and timing all matter.",
        must_include=["subtle San Jose foothill silhouette"],
        avoid=["fake market statistics"],
    )


class ImagePromptTest(TestCase):
    def test_renders_structured_brief_with_fixed_brand_guardrails(self) -> None:
        rendered = prompt().render()

        self.assertIn("Warm ivory, charcoal, muted bronze", rendered)
        self.assertIn("COMPARE THE WHOLE MOVE", rendered)
        self.assertIn("Do not invent prices, statistics", rendered)

    def test_image_key_is_stable_and_partitioned_by_publish_date(self) -> None:
        due_at = datetime(2026, 8, 19, 15, 30, tzinfo=UTC)

        first = image_key(42, due_at, "same prompt")
        second = image_key(42, due_at, "same prompt")

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("generated_graphics/2026/08/19/topic-42-"))

    def test_renders_exact_profile_fields_and_typed_people_references(self) -> None:
        image_prompt = prompt().model_copy(
            update={"business_fields": ["logo", "phone", "city"]}
        )
        contact_info = ContactInfo(
            business_name="Test Business",
            phone="408.555.0100",
            city="San Jose, CA",
            website="https://test-business.example/",
        )
        references = [
            ReferenceImage(
                "people/team.jpg",
                b"team",
                "image/jpeg",
                role="headshot-group",
                description="Advisor with clients",
            ),
            ReferenceImage("brand/logo.png", b"logo", "image/png", role="logo"),
        ]

        rendered = image_prompt.render(references, contact_info)

        self.assertIn("phone: 408.555.0100", rendered)
        self.assertIn("city: San Jose, CA", rendered)
        self.assertIn("Attachment 1: key=people/team.jpg; role=headshot-group", rendered)
        self.assertIn("Preserve every face", rendered)
        self.assertIn("use the supplied role=logo attachment exactly", rendered)


class GenerateAndStoreImageTest(IsolatedAsyncioTestCase):
    async def test_generates_png_and_stores_public_asset(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                "OPENAI_IMAGE_WIDTH": "1088",
                "OPENAI_IMAGE_HEIGHT": "1360",
                "OPENAI_IMAGE_QUALITY": "medium",
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
                "ASSET_PUBLIC_BASE_URL": "https://social.example",
            }
        )
        image_data = AsyncMock()
        image_data.b64_json = base64.b64encode(b"png-bytes").decode()
        response = AsyncMock()
        response.data = [image_data]
        client = AsyncMock()
        client.images.generate.return_value = response
        store = AsyncMock()

        with patch("openai.AsyncOpenAI", return_value=client):
            generated = await generate_and_store_image(
                settings,
                prompt(),
                42,
                datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
                store,
            )

        self.assertEqual(generated.model, "gpt-image-2")
        self.assertEqual(generated.size, "1088x1360")
        self.assertTrue(
            generated.url.startswith("https://social.example/assets/generated_graphics/")
        )
        store.put.assert_awaited_once_with(generated.key, b"png-bytes", "image/png")
        client.images.generate.assert_awaited_once()
        self.assertEqual(client.images.generate.await_args.kwargs["size"], "1088x1360")

    async def test_uses_selected_r2_images_as_edit_inputs(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                "OPENAI_IMAGE_WIDTH": "1088",
                "OPENAI_IMAGE_HEIGHT": "1360",
                "OPENAI_IMAGE_QUALITY": "medium",
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
                "ASSET_PUBLIC_BASE_URL": "https://social.example",
            }
        )
        image_data = AsyncMock()
        image_data.b64_json = base64.b64encode(b"edited-png").decode()
        response = AsyncMock()
        response.data = [image_data]
        client = AsyncMock()
        client.images.edit.return_value = response
        store = AsyncMock()
        references = [
            ReferenceImage("indoors/kitchen.jpg", b"kitchen", "image/jpeg", role="indoor"),
            ReferenceImage(
                "headshots/advisor.png", b"advisor", "image/png", role="headshot"
            ),
        ]

        with patch("openai.AsyncOpenAI", return_value=client):
            await generate_and_store_image(
                settings,
                prompt(),
                42,
                datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
                store,
                references,
            )

        client.images.generate.assert_not_awaited()
        client.images.edit.assert_awaited_once()
        edit_args = client.images.edit.await_args.kwargs
        self.assertNotIn("input_fidelity", edit_args)
        self.assertEqual(
            edit_args["image"],
            [
                ("01-indoor-kitchen.jpg", b"kitchen", "image/jpeg"),
                ("02-headshot-advisor.png", b"advisor", "image/png"),
            ],
        )
        self.assertIn("indoors/kitchen.jpg", edit_args["prompt"])
        self.assertIn("Attachment 2: key=headshots/advisor.png; role=headshot", edit_args["prompt"])

    async def test_dry_run_saves_generated_png_to_local_output_directory(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                "OPENAI_IMAGE_WIDTH": "1088",
                "OPENAI_IMAGE_HEIGHT": "1360",
                "OPENAI_IMAGE_QUALITY": "medium",
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
            }
        )
        image_data = AsyncMock()
        image_data.b64_json = base64.b64encode(b"local-png-bytes").decode()
        response = AsyncMock()
        response.data = [image_data]
        client = AsyncMock()
        client.images.generate.return_value = response

        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            with patch("openai.AsyncOpenAI", return_value=client):
                generated = await generate_and_save_image(
                    settings,
                    prompt(),
                    42,
                    datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
                    output_root,
                    output_root,
                )

            saved_path = Path(generated.local_path_absolute or "")
            self.assertTrue(saved_path.is_file())
            self.assertEqual(saved_path.read_bytes(), b"local-png-bytes")
            self.assertEqual(generated.url, None)
            self.assertEqual(
                generated.local_path_relative,
                "2026/08/19/" + saved_path.name,
            )


class R2ReferenceStoreTest(IsolatedAsyncioTestCase):
    async def test_lists_only_source_images_and_downloads_selected_asset(self) -> None:
        class Item:
            def __init__(self, key: str) -> None:
                self.key = key

        class Page:
            objects = [
                Item("indoors/kitchen.jpg"),
                Item("outdoors/front.webp"),
                Item("info/logo.png"),
                Item("generated_graphics/old.png"),
                Item("notes/readme.txt"),
            ]
            truncated = False

        class Metadata:
            contentType = "image/jpeg"

        class Asset:
            httpMetadata = Metadata()

            async def arrayBuffer(self) -> bytearray:
                return bytearray(b"photo")

        bucket = AsyncMock()
        bucket.list.return_value = Page()
        bucket.get.return_value = Asset()
        store = R2ImageAssetStore(bucket)

        keys = await store.list_reference_keys()
        image = await store.get_reference_image("indoors/kitchen.jpg")

        self.assertEqual(keys, ["indoors/kitchen.jpg", "outdoors/front.webp"])
        self.assertEqual(image.body, b"photo")
        self.assertEqual(image.content_type, "image/jpeg")

    async def test_loads_strict_contact_json_and_fixed_logo_key(self) -> None:
        class Asset:
            httpMetadata = None

            def __init__(self, body: bytes) -> None:
                self.body = body

            async def arrayBuffer(self) -> bytearray:
                return bytearray(self.body)

        bucket = AsyncMock()
        bucket.get.side_effect = [
            Asset(
                b'{"business_name":"Test Business","phone":"(555) 555-5555",'
                b'"city":"San Jose, CA","website":"https://test-business.example/"}'
            ),
            Asset(b"logo-png"),
        ]
        store = R2ImageAssetStore(bucket)

        contact = await store.get_contact_info()
        logo = await store.get_logo_image()

        self.assertEqual(contact.city, "San Jose, CA")
        self.assertEqual(contact.website, "https://test-business.example/")
        self.assertEqual(logo.key, "info/logo.png")
        self.assertEqual(logo.role, "logo")
        self.assertEqual(
            [call.args[0] for call in bucket.get.await_args_list],
            ["info/contact.json", "info/logo.png"],
        )
