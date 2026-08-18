from unittest import TestCase

from brand.brand_context import infer_asset, parse_contact_info


class ContactInfoTest(TestCase):
    def test_accepts_exact_four_field_r2_document(self) -> None:
        contact = parse_contact_info(
            b'{"business_name":"Test Business","phone":"(555) 555-5555",'
            b'"city":"San Jose, CA","website":"https://test-business.example/"}'
        )

        self.assertEqual(contact.business_name, "Test Business")
        self.assertEqual(contact.phone, "(555) 555-5555")
        self.assertEqual(contact.city, "San Jose, CA")
        self.assertEqual(contact.website, "https://test-business.example/")

    def test_rejects_missing_or_extra_fields(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing: website"):
            parse_contact_info(
                b'{"business_name":"Test Business","phone":"(555) 555-5555",'
                b'"city":"San Jose, CA"}'
            )

        with self.assertRaisesRegex(RuntimeError, "unexpected: email"):
            parse_contact_info(
                b'{"business_name":"Test Business","phone":"(555) 555-5555",'
                b'"city":"San Jose, CA","website":"https://test-business.example/",'
                b'"email":"hello@example.com"}'
            )


class ReferenceRoleTest(TestCase):
    def test_maps_existing_r2_folders_to_distinct_roles(self) -> None:
        self.assertEqual(infer_asset("indoors/kitchen.jpg").role, "indoor")
        self.assertEqual(infer_asset("outdoors/front.jpg").role, "outdoor")
        self.assertEqual(infer_asset("headshots/realtor.png").role, "headshot")
        self.assertEqual(
            infer_asset("headshot group/realtor-with-clients.jpg").role,
            "headshot-group",
        )
        self.assertEqual(
            infer_asset("headshots/group/realtor-with-clients.jpg").role,
            "headshot-group",
        )
        self.assertEqual(infer_asset("info/logo.png").role, "logo")
