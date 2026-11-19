"""冒烟测试：工具自己也得过自己的检查。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import slopcheck  # noqa: E402


class TestDemo(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent / "demo"
        self.result = slopcheck.run(self.root)

    def test_demo_scores_bad(self):
        self.assertLess(self.result["score"], 40)

    def test_detects_hardcoded_secret(self):
        ids = {f["id"] for f in self.result["findings"]}
        self.assertIn("secret", ids)

    def test_detects_broken_readme(self):
        ids = {f["id"] for f in self.result["findings"]}
        self.assertIn("readmefake", ids)

    def test_every_finding_has_evidence(self):
        for f in self.result["findings"]:
            self.assertTrue(f["hits"], "规则 %s 没有证据" % f["id"])

    def test_every_finding_has_days(self):
        for f in self.result["findings"]:
            self.assertIsInstance(f["days"], int)


class TestClean(unittest.TestCase):
    def test_empty_dir_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            r = slopcheck.run(d)
            self.assertEqual(r["score"], 100)
            self.assertEqual(r["grade"], "S")


class TestBaseline(unittest.TestCase):
    def test_baseline_hides_known_issues(self):
        root = Path(__file__).resolve().parent.parent / "demo"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bl.json"
            first = slopcheck.run(root)
            slopcheck.save_baseline(first, path)

            base = slopcheck.load_baseline(path)
            second = slopcheck.apply_baseline(slopcheck.run(root), base)
            self.assertEqual(second["baseline"]["new"], 0)
            self.assertEqual(second["findings"], [])

    def test_baseline_detects_new_issue(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.py").write_text("print('hi')\n", encoding="utf-8")
            base = slopcheck.save_baseline(slopcheck.run(root), root / "bl.json")

            (root / "b.js").write_text('const password = "admin123";\n', encoding="utf-8")
            result = slopcheck.apply_baseline(slopcheck.run(root), base)
            self.assertGreaterEqual(result["baseline"]["new"], 1)
            ids = {f["id"] for f in result["findings"]}
            self.assertIn("secret", ids)


class TestFix(unittest.TestCase):
    def test_fix_plan_is_safe_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".env").write_text("API_KEY=abc\n", encoding="utf-8")
            acts = slopcheck.plan_fixes(root)
            descs = " ".join(a[3] for a in acts)
            self.assertIn(".gitignore", descs)
            self.assertIn(".env.example", descs)
            # 预演不应落盘
            self.assertFalse((root / ".gitignore").exists())

    def test_fix_apply_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".env").write_text("API_KEY=abc\n", encoding="utf-8")
            slopcheck.apply_fixes(slopcheck.plan_fixes(root))
            self.assertTrue((root / ".gitignore").exists())
            example = (root / ".env.example").read_text(encoding="utf-8")
            self.assertIn("API_KEY=", example)
            self.assertNotIn("abc", example)


if __name__ == "__main__":
    unittest.main()
