import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.S)


class SkillManifestTests(unittest.TestCase):
    def test_frontmatter_and_required_env(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        match = FRONTMATTER.search(text)
        self.assertIsNotNone(match)
        front = match.group(1)
        self.assertIn("name: ai-fitness-coach", front)
        self.assertIn("description:", front)
        for key in ("XUNJI_TRAIN_API_KEY", "XUNJI_FOOD_API_KEY", "XUNJI_FOOD_SEARCH_API_KEY", "MI_HEALTH_API_KEY"):
            self.assertIn(key, front)

    def test_referenced_files_exist(self):
        pattern = re.compile(r"(?<![A-Za-z0-9_./-])(?:references|assets)/[A-Za-z0-9._/-]+")
        paths = [SKILL / "SKILL.md", SKILL / "README.md", *sorted((SKILL / "references").glob("*.md"))]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for relative in set(pattern.findall(text)):
                if relative.endswith("/"):
                    continue
                self.assertTrue((SKILL / relative).exists(), f"{relative} referenced by {path.name}")

    def test_markdown_links_exist(self):
        link = re.compile(r"\]\(([^)]+)\)")
        paths = [SKILL / "SKILL.md", SKILL / "README.md", *sorted((SKILL / "references").glob("*.md"))]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for target in link.findall(text):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                candidate = (path.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(candidate.exists(), f"{target} linked from {path.name}")

    def test_no_real_secret_patterns(self):
        patterns = (
            re.compile(r"xjllm_[0-9a-f]{20,}"),
            re.compile(r"xjfood_[0-9a-f]{20,}"),
            re.compile(r"mhk_[0-9a-f]{20,}"),
        )
        for path in SKILL.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".sqlite", ".pyc"):
                continue
            if path.name == "test_skill_manifest.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f"secret-like value in {path}")


if __name__ == "__main__":
    unittest.main()
