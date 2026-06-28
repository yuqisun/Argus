"""Tests for LocalRepoCodeSearcher."""
import tempfile
import subprocess
from pathlib import Path
import pytest
from argus.implementations.code_search.local_searcher import LocalRepoCodeSearcher


@pytest.fixture
def test_repo():
    """Create a temporary git repo with sample code for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "testproject"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)

        (repo / "app.py").write_text("""def handle_request():\n    result = process()\n    return result\n\ndef process():\n    raise ValueError("bad input")\n""")
        (repo / "utils.py").write_text("""def helper():\n    return 42\n""")

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()

        yield str(repo.parent), "testproject", commit


class TestLocalRepoCodeSearcher:
    @pytest.mark.asyncio
    async def test_grep_finds_matches(self, test_repo):
        repos_root, repo_name, commit = test_repo
        searcher = LocalRepoCodeSearcher(repos_root=repos_root)
        hits = await searcher.grep(repo_name, "ValueError", commit=commit)
        assert len(hits) > 0
        assert any("ValueError" in h.content for h in hits)

    @pytest.mark.asyncio
    async def test_blame_returns_author(self, test_repo):
        repos_root, repo_name, commit = test_repo
        searcher = LocalRepoCodeSearcher(repos_root=repos_root)
        author, sha = await searcher.blame(repo_name, "app.py", 5, commit=commit)
        assert "test@test.com" in author

    @pytest.mark.asyncio
    async def test_find_definition_finds_function(self, test_repo):
        repos_root, repo_name, commit = test_repo
        searcher = LocalRepoCodeSearcher(repos_root=repos_root)
        hit = await searcher.find_definition(repo_name, "handle_request", commit=commit)
        assert hit is not None
        assert "handle_request" in hit.content

    @pytest.mark.asyncio
    async def test_get_call_graph_returns_node(self, test_repo):
        repos_root, repo_name, commit = test_repo
        searcher = LocalRepoCodeSearcher(repos_root=repos_root)
        node = await searcher.get_call_graph(repo_name, "handle_request", commit=commit)
        assert node is not None
        assert node.function_name == "handle_request"
