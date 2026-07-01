"""Local git repo code searcher using git grep + gitpython."""
from __future__ import annotations
import asyncio
import re
from pathlib import Path
import structlog
from argus.interfaces.code_search import CodeHit, CallGraphNode

logger = structlog.get_logger(__name__)


class LocalRepoCodeSearcher:
    """Code search via git grep and git blame on local repos."""

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

    async def grep(
        self, repo: str, pattern: str, *, commit: str, glob: str | None = None,
    ) -> list[CodeHit]:
        args = ["grep", "-n", "-i", pattern, commit]
        if glob:
            args.extend(["--", glob])
        output = await self._run_git(repo, *args)

        hits = []
        for line in output.strip().split('\n'):
            if not line or ':' not in line:
                continue
            # git grep <commit> outputs: <commit>:<file>:<line>:<content> (4 fields)
            # git grep (no commit) outputs: <file>:<line>:<content> (3 fields)
            parts = line.split(':', 3)
            if len(parts) == 4:
                _, file_path, lineno_str, content = parts
            elif len(parts) == 3:
                file_path, lineno_str, content = parts
            else:
                continue
            try:
                lineno = int(lineno_str)
            except ValueError:
                continue
            hits.append(CodeHit(
                file_path=file_path, line_number=lineno, content=content.strip(),
            ))
        return hits

    async def find_definition(
        self, repo: str, symbol: str, *, commit: str,
    ) -> CodeHit | None:
        patterns = [f"def {symbol}", f"class {symbol}", f"fun {symbol}"]
        for pattern in patterns:
            hits = await self.grep(repo, pattern, commit=commit)
            if hits:
                return hits[0]
        return None

    async def get_call_graph(
        self, repo: str, function: str, *, commit: str, depth: int = 2,
    ) -> CallGraphNode | None:
        hit = await self.find_definition(repo, function, commit=commit)
        if not hit:
            return None

        caller_hits = await self.grep(repo, f"{function}(", commit=commit)
        callers = [
            h.file_path for h in caller_hits
            if function not in h.content.lstrip().split('(')[0]
        ]

        try:
            repo_path = self._repo_path(repo)
            content = (repo_path / hit.file_path).read_text(encoding="utf-8", errors="replace")
            callees = []
            for line in content.split('\n'):
                match = re.match(r'\s+(\w+)\(', line)
                if match:
                    callees.append(match.group(1))
        except (FileNotFoundError, OSError):
            callees = []

        return CallGraphNode(
            function_name=function, file_path=hit.file_path,
            line_number=hit.line_number,
            callers=callers[:depth * 10], callees=callees[:depth * 10],
        )

    async def blame(
        self, repo: str, file_path: str, line_number: int, *, commit: str,
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
