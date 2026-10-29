"""Real signing test: needs pypdf + reportlab + Pillow only (all present), no web framework or database."""
import io
import unittest
from datetime import datetime, timezone

from PIL import Image
from pypdf import PdfReader

from app.modules.documents.pdfsign import extract_text, make_simple_pdf, sha256_hex, stamp_count, stamp_pdf


def png(color):
    b = io.BytesIO()
    Image.new("RGBA", (300, 120), color).save(b, format="PNG")
    return b.getvalue()


class StampTests(unittest.TestCase):
    def setUp(self):
        self.original = make_simple_pdf("Test Contract", [("Party", "Placeholder Client A"), ("Value", "N5,000,000")])

    def test_two_signers_in_order_both_stamps_present(self):
        when = datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)
        step1, hash1 = stamp_pdf(self.original, "Amaka Nwachukwu", png((10, 40, 90, 255)), "197.210.1.1", "4.8156, 7.0498", when, 1)
        step2, hash2 = stamp_pdf(step1, "Chidi Okonkwo", png((200, 60, 20, 255)), "197.210.2.2", "", when, 2)
        text = extract_text(step2)
        for needle in ("Signature record", "Amaka Nwachukwu", "Chidi Okonkwo", "197.210.1.1", "197.210.2.2", "4.8156, 7.0498", "not provided", "10:30:00 WAT"):
            self.assertIn(needle, text)
        self.assertEqual(stamp_count(step2), 2)
        self.assertEqual(hash1, sha256_hex(self.original))
        self.assertEqual(hash2, sha256_hex(step1))
        self.assertIn(hash1[:32], text)
        self.assertIn(hash2[32:], text)
        self.assertEqual(len(PdfReader(io.BytesIO(step2)).pages), 2)  # original page + ONE shared signature page
        self.assertIn("Test Contract", text)  # original content untouched

    def test_signature_image_is_embedded(self):
        out, _ = stamp_pdf(self.original, "A B", png((0, 0, 0, 255)))
        page = PdfReader(io.BytesIO(out)).pages[-1]
        self.assertGreaterEqual(len(list(page.images)), 1)

    def test_fifth_signature_starts_new_record_page(self):
        data = self.original
        for i in range(5):
            data, _ = stamp_pdf(data, f"Signer {i + 1}", None, "1.1.1.1")
        self.assertEqual(len(PdfReader(io.BytesIO(data)).pages), 3)
        self.assertEqual(stamp_count(data), 5)

    def test_bad_signature_image_does_not_block(self):
        out, _ = stamp_pdf(self.original, "Safe Signer", b"not an image")
        self.assertIn("Safe Signer", extract_text(out))

    def test_tampering_changes_hash(self):
        out, _ = stamp_pdf(self.original, "X Y", None)
        self.assertNotEqual(sha256_hex(out), sha256_hex(self.original))


if __name__ == "__main__":
    unittest.main()
