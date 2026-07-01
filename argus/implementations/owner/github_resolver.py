"""GitHub owner resolver — CODEOWNERS → blame fallback."""
from __future__ import annotations
import asyncio
from pathlib import Path
import structlog
from argus.interfaces.owner_resolver import OwnerResult

logger = structlog.get_logger(__name__)


class GitHubOwnerResolver:
    """Resolve code owner via CODEOWNERS and git blame."""

    def __init__(self, repos_root: str):
        self.repos_root = Path(repos_root)

    def _repo_path(self, repo_name: str) -> Path:
        return self.repos_root / repo_name

    async def _run_git(self, repo_name: str, *args: str, timeout: float = 10.0) -> str:
        """Run git command asynchronously with timeout."""
        repo = self._repo_path(repo_name)
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", str(repo), *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode("utf-8", errors="replace")
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            logger.warning("git command failed", repo=repo_name, args=args[:3])
            return ""

    async def resolve(
        self, repo: str, file_path: str, line_number: int, *, commit: str,
    ) -> list[OwnerResult]:
        results: list[OwnerResult] = []

        # 1. Try CODEOWNERS
        codeowners = self._parse_codeowners(repo, file_path)
        if codeowners:
            results.append(OwnerResult(
                name=codeowners, email="",
                source="codeowners", confidence=0.9,
            ))

        # 2. Try blame
        email, _ = await self._blame(repo, file_path, line_number, commit)
        if email and email != "unknown":
            results.append(OwnerResult(
                name=email.split('@')[0], email=email,
                source="blame", confidence=0.7,
            ))

        return results

    def _parse_codeowners(self, repo: str, file_path: str) -> str | None:
        repo_path = self._repo_path(repo)
        codeowners_file = repo_path / "CODEOWNERS"
        if not codeowners_file.exists():
            alt = repo_path / ".github" / "CODEOWNERS"
            if alt.exists():
                codeowners_file = alt
            else:
                return None

        for line in codeowners_file.read_text(encoding="utf-8", errors="replace").split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                pattern, owners = parts[0], parts[1:]
                if pattern == file_path or pattern == "*":
                    return owners[0].lstrip('@')

        return None

    async def _blame(
        self, repo: str, file_path: str, line_number: int, commit: str,
    ) -> tuple[str, str]:
        try:
            output = await self._run_git(
                repo, "blame", "-L", f"{line_number},{line_number}",
                "--porcelain", commit, "--", file_path,
            )
            for line in output.strip().split('\n'):
                if line.startswith('author-mail '):
                    email = line.split('<', 1)[1].rstrip('>')
                    return (email, commit)
            output = await self._run_git(repo, "log", "-1", "--format=%ae", commit)
            return (output.strip(), commit)
        except Exception:
            return ("unknown", commit)
