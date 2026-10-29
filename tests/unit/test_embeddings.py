import unittest

from app.modules.documents.embeddings import chunk_text, cosine, local_embed


class ChunkTests(unittest.TestCase):
    def test_short_text_one_chunk(self):
        self.assertEqual(chunk_text("Hello world."), ["Hello world."])

    def test_empty(self):
        self.assertEqual(chunk_text("   "), [])

    def test_long_text_splits_with_overlap_and_covers_everything(self):
        text = " ".join(f"Sentence number {i} about pumps." for i in range(200))
        chunks = chunk_text(text, size=300, overlap=50)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 300 for c in chunks))
        self.assertIn("Sentence number 0 ", chunks[0])
        self.assertIn("Sentence number 199", chunks[-1])


class SearchTests(unittest.TestCase):
    def test_relevant_chunk_ranks_first(self):
        docs = {
            "safety": "Hydrotest safety procedure: isolate the line, check gauges, evacuate the area before pressurising.",
            "hr": "Annual leave policy: staff receive twenty days of leave and must apply two weeks ahead.",
            "rental": "Equipment rental terms: daily rate for flooding pumps, return within agreed dates, late fees apply.",
        }
        vecs = {k: local_embed(v) for k, v in docs.items()}
        q = local_embed("What is the leave policy for staff?")
        ranked = sorted(vecs, key=lambda k: cosine(q, vecs[k]), reverse=True)
        self.assertEqual(ranked[0], "hr")
        q2 = local_embed("pressure test safety isolate line")
        self.assertEqual(sorted(vecs, key=lambda k: cosine(q2, vecs[k]), reverse=True)[0], "safety")

    def test_vectors_are_normalised_and_deterministic(self):
        a, b = local_embed("flooding pump service"), local_embed("flooding pump service")
        self.assertEqual(a, b)
        self.assertAlmostEqual(cosine(a, a), 1.0)
        self.assertEqual(cosine([1.0], [1.0, 2.0]), 0.0)


if __name__ == "__main__":
    unittest.main()
