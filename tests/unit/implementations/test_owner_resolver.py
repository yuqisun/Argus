"""Tests for GitHub owner resolver."""
import tempfile
import subprocess
from pathlib import Path
import pytest
from argus.implementations.owner.github_resolver import GitHubOwnerResolver


@pytest.fixture
def test_repo():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "testproject"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "owner@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Owner"], cwd=repo, capture_output=True)

        (repo / "app.py").write_text("def main():\n    pass\n")
        (repo / "CODEOWNERS").write_text("app.py @team-lead\n")

        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()

        yield str(repo.parent), "testproject", commit


class TestGitHubOwnerResolver:
    @pytest.mark.asyncio
    async def test_resolve_falls_back_to_blame(self, test_repo):
        repos_root, repo_name, commit = test_repo
        resolver = GitHubOwnerResolver(repos_root=repos_root)
        results = await resolver.resolve(repo_name, "app.py", 1, commit=commit)
        assert len(results) > 0
        # Last result is blame
        assert results[-1].source == "blame"
        assert "owner@test.com" in results[-1].email

    @pytest.mark.asyncio
    async def test_codeowners_found(self, test_repo):
        repos_root, repo_name, commit = test_repo
        resolver = GitHubOwnerResolver(repos_root=repos_root)
        results = await resolver.resolve(repo_name, "app.py", 1, commit=commit)
        # First result should be codeowners
        assert any(r.source == "codeowners" for r in results)
