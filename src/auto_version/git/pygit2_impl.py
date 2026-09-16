"""Real git repository implementation using pygit2."""

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pygit2

from auto_version.git.interface import (GitRepository, PushRejected,
                                        redact_remote, scrub_credentials)
from auto_version.models import CommitInfo

# Markers git uses when the remote ref moved under us — the one rejection a
# retry can clear. Anything else (auth, unknown remote, DNS, a pre-receive
# hook, branch protection) is not worth retrying.
#
# Two wordings matter, because they differ between push modes:
#   plain  -> "! [rejected]  HEAD -> main (fetch first)"
#   atomic -> "cannot lock ref 'refs/heads/main': is at <a> but expected <b>"
#             "! [remote rejected] HEAD -> main (atomic transaction failed)"
# A bare "! [rejected]" is deliberately NOT matched: it also covers hook and
# branch-protection refusals, which retrying would only repeat.
_NON_FAST_FORWARD_MARKERS = (
    "non-fast-forward",
    "fetch first",
    "stale info",
)

# An atomic push reports contention as a failed compare-and-swap on the ref:
#   cannot lock ref 'refs/heads/main': is at <oid> but expected <oid>
# Both halves are required. "cannot lock ref" alone also covers a stale or
# held lock file —
#   cannot lock ref 'refs/heads/main': Unable to create '…main.lock': File exists
# — which is not contention: retrying cannot clear it, and treating it as
# retryable would discard a perfectly good release on exhaustion instead of
# keeping it for a manual push.
# Matched on a single line, with the object-id structure required. Testing
# the two phrases independently across the whole output would let a server
# emit them in unrelated `remote:` lines and be read as contention.
_CAS_FAILURE = re.compile(
    r"cannot lock ref.*\bis at\s+[0-9a-f]{7,64}\s+but expected\s+[0-9a-f]{7,64}",
    re.IGNORECASE,
)

# The rejection reason git appends to a status line: "... (fetch first)".
_REJECTION_REASON = re.compile(r"\(([^()]*)\)\s*$")

# The reason git gives every ref when the receiving side's ref transaction
# failed to commit — a compare-and-swap mismatch or a lock. A hook refusal
# is reported as "(pre-receive hook declined)" instead, whatever it printed.
_ATOMIC_TRANSACTION_FAILED = "atomic transaction failed"


def _status_reason(line: str, status: str) -> str | None:
    """The parenthesised reason ending one of git's push status lines.

    ``None`` unless ``line`` is a ``status`` line ("! [rejected]" or
    "! [remote rejected]") carrying a reason. Only the reason counts: the
    refspec is user-controlled text sitting on the same line, and a tag that
    happened to be named "non-fast-forward" would otherwise turn an "(already
    exists)" refusal into contention.
    """
    line = line.strip().lower()
    if not line.startswith(status):
        return None
    match = _REJECTION_REASON.search(line)
    return match.group(1) if match else None


def _is_non_fast_forward(git_output: str) -> bool:
    """Whether git's push output indicates the remote ref moved under us.

    Only git's own status lines decide. A server can print anything it likes
    through ``remote:`` lines, and a hook that advises "please fetch first"
    would otherwise be read as contention — deleting the tag, resetting, and
    discarding a valid release that the server had simply refused.

    The plain markers are read from the reason on a ``! [rejected]`` line.
    ``! [remote rejected]`` is the server saying no, not the branch moving,
    and counts only when its reason names the ref transaction:

    * as the compare-and-swap diagnostic itself, which is how hosted servers
      such as GitHub report it — ``(cannot lock ref '…': is at X but expected
      Y)``;
    * as ``(atomic transaction failed)``, which is how stock git reports it,
      with the diagnostic on a separate ``remote:`` line. That line arrives
      through the same channel as hook output, so a hook echoing the exact
      wording is indistinguishable from the real thing on its own — which is
      why the status line is required as well.
    """
    lines = git_output.splitlines()
    transaction_failed = False
    for line in lines:
        reason = _status_reason(line, "! [rejected]")
        if reason and any(marker in reason for marker in _NON_FAST_FORWARD_MARKERS):
            return True
        reason = _status_reason(line, "! [remote rejected]")
        if reason and _CAS_FAILURE.search(reason):
            return True
        if reason == _ATOMIC_TRANSACTION_FAILED:
            transaction_failed = True
    return transaction_failed and any(_CAS_FAILURE.search(line) for line in lines)


def _is_missing_tag(git_output: str) -> bool:
    """Whether ``git tag -d`` failed only because the tag was already absent.

    Deleting an absent tag is the one tolerable failure; every other cause
    must propagate, since the caller deletes a tag to stop a following reset
    from orphaning it.
    """
    return "not found" in git_output.lower()


class PyGit2Repository(GitRepository):
    """Real git repository implementation using pygit2."""

    def __init__(self, repo_path: Path | None = None) -> None:
        """Initialize with a repository path.

        Args:
            repo_path: Path to the git repository. If None, discovers from current directory.
        """
        if repo_path is None:
            repo_path = Path.cwd()

        # Discover the git repository
        discovered = pygit2.discover_repository(str(repo_path))
        if not discovered:
            raise ValueError(f"No git repository found at {repo_path}")

        self._repo = pygit2.Repository(discovered)

    def get_tags(self, pattern: str | None = None) -> list[str]:
        """Get all tags, optionally filtered by pattern."""
        from auto_version.models import Version

        tags = []
        for ref in self._repo.listall_references():
            if ref.startswith("refs/tags/"):
                tag_name = ref.replace("refs/tags/", "")
                if pattern is None or self._matches_pattern(tag_name, pattern):
                    tags.append(tag_name)

        # Sort by semantic version (newest first)
        # Extract version from tag name and use for sorting
        def extract_version(tag: str) -> tuple[int, int, int]:
            """Extract version numbers for sorting."""
            try:
                # Try to find version pattern like x.y.z in the tag
                import re

                match = re.search(r"(\d+)\.(\d+)\.(\d+)", tag)
                if match:
                    return (
                        int(match.group(1)),
                        int(match.group(2)),
                        int(match.group(3)),
                    )
            except (ValueError, AttributeError):
                pass
            # Fallback to (0, 0, 0) for non-semver tags
            return (0, 0, 0)

        return sorted(tags, key=extract_version, reverse=True)

    def get_commits_since(
        self, since_ref: str | None, path_filters: list[str] | None = None
    ) -> list[CommitInfo]:
        """Get commits since a reference."""
        # Get the HEAD commit
        try:
            head = self._repo.revparse_single("HEAD")
        except KeyError:
            return []  # Empty repository

        # Set up walker
        walker = self._repo.walk(head.id, pygit2.GIT_SORT_TOPOLOGICAL)

        # If we have a since_ref, hide commits before it
        if since_ref:
            try:
                since_obj = self._repo.revparse_single(since_ref)
                walker.hide(since_obj.id)
            except KeyError:
                raise ValueError(f"Reference not found: {since_ref}")

        # Walk commits and collect those matching filters
        commits = []
        for commit in walker:
            # Get changed files for this commit
            if commit.parents:
                # Get diff from first parent
                diff = self._repo.diff(commit.parents[0], commit)
                changed_files = [Path(delta.new_file.path) for delta in diff.deltas]
            else:
                # First commit - all files are new
                changed_files = []
                for entry in commit.tree:
                    changed_files.append(Path(entry.name))

            # Apply path filters
            if path_filters:
                matches_filter = any(
                    self._file_matches_filters(f, path_filters) for f in changed_files
                )
                if not matches_filter:
                    continue

            # Parse commit message
            message = commit.message.strip()
            commits.append(
                CommitInfo(
                    sha=str(commit.id),
                    short_sha=str(commit.id)[:7],
                    message=message,
                    commit_type="",  # Will be parsed later
                    scope=None,
                    description=message.split("\n")[0],
                    body="\n".join(message.split("\n")[1:]).strip(),
                    timestamp=datetime.fromtimestamp(
                        commit.commit_time, tz=timezone.utc
                    ),
                    affected_files=changed_files,
                )
            )

        # Return in chronological order (oldest first)
        return list(reversed(commits))

    def get_changed_files(self, commit_sha: str) -> list[Path]:
        """Get list of files changed in a commit."""
        try:
            commit = self._repo.revparse_single(commit_sha)
        except KeyError:
            return []

        if not commit.parents:
            return []

        diff = self._repo.diff(commit.parents[0], commit)
        return [Path(delta.new_file.path) for delta in diff.deltas]

    def create_tag(self, name: str, message: str, commit: str = "HEAD") -> None:
        """Create an annotated tag."""
        target = self._repo.revparse_single(commit)

        # Get tagger signature
        signature = self._repo.default_signature

        self._repo.create_tag(
            name,
            target.id,
            pygit2.GIT_OBJECT_COMMIT,
            signature,
            message,
        )

    def create_commit(self, message: str, files: list[Path]) -> str:
        """Create a commit with the specified files."""
        # Files should already be staged via stage_files()
        # Get tree from index
        tree = self._repo.index.write_tree()

        # Get parent commit
        try:
            parent = self._repo.revparse_single("HEAD")
            parents = [parent.id]
        except KeyError:
            parents = []

        # Get signature
        signature = self._repo.default_signature

        # Create commit
        commit_oid = self._repo.create_commit(
            "HEAD",
            signature,
            signature,
            message,
            tree,
            parents,
        )

        return str(commit_oid)

    def get_current_branch(self) -> str | None:
        """Get the name of the current branch, or None if HEAD is detached.

        Uses ``head_is_detached`` rather than comparing ``head.type`` against
        ``pygit2.GIT_REF_SYMBOLIC``: that module-level constant was moved into
        ``pygit2.enums`` and raises ``AttributeError`` on current pygit2, and
        the old comparison was inverted besides — it returned the branch name
        only when HEAD was symbolic-*resolved*, so a normal checkout reported
        "HEAD". ``--push`` is the first caller, so this went unnoticed.

        An unborn HEAD (a fresh repository with no commits) is not detached:
        HEAD is still a symbolic ref naming the branch the first commit will
        land on, so that name is returned. Reading ``head`` raises
        ``GitError`` there, so the symbolic target is read directly.

        Any other ``GitError`` — an unreadable HEAD, repository I/O —
        propagates. Returning None would report a broken repository as a
        detached HEAD and ask for ``--branch``, which cannot help.
        """
        if self._repo.head_is_detached:
            return None
        if self._repo.head_is_unborn:
            target = str(self._repo.lookup_reference("HEAD").target)
            return target.removeprefix("refs/heads/")
        return str(self._repo.head.shorthand)

    def get_repo_root(self) -> Path:
        """Get the root directory of the git repository."""
        return Path(self._repo.workdir)

    def stage_files(self, files: list[Path]) -> None:
        """Stage files for commit."""
        repo_root = self.get_repo_root()
        for file_path in files:
            # Make path relative to repo root
            if file_path.is_absolute():
                rel_path = file_path.relative_to(repo_root)
            else:
                rel_path = file_path
            self._repo.index.add(str(rel_path))
        self._repo.index.write()

    def fetch(self, remote: str, branch: str) -> str:
        """Fetch a branch from a remote and return the ref that names its tip.

        Returns ``FETCH_HEAD`` rather than ``<remote>/<branch>`` because the
        remote-tracking ref is not reliably updated by a command-line
        refspec. Git updates it *opportunistically*, only when the remote has
        a matching configured fetch refspec, so:

        * a named remote with the usual ``+refs/heads/*:refs/remotes/<name>/*``
          does get updated (the common case);
        * a remote with no configured fetch refspec does **not**, leaving the
          tracking ref on the pre-fetch tip;
        * a URL passed instead of a remote name has no tracking ref at all —
          ``refs/remotes/<url>/<branch>`` does not resolve.

        Resetting to a stale tracking ref would silently re-derive the release
        from the tip we just lost the race to, and repeat the same rejected
        push until the retries ran out. ``FETCH_HEAD`` is correct in all three
        cases: it names exactly what this fetch just retrieved.

        ``--tags`` is not optional. Naming a refspec on the command line
        turns off git's usual tag auto-following, so ``git fetch <remote>
        <branch>`` brings back **no tags at all** — not merely when
        ``remote.<name>.tagOpt=--no-tags`` is set. Since the version is
        derived from tags, a resync without them recomputes against a tag
        history that is missing the release which just won, produces the same
        version again, and gets rejected for a tag that already exists on the
        remote.
        """
        self._run_git("fetch", "--tags", remote, branch)
        return "FETCH_HEAD"

    def push(self, remote: str, refspecs: list[str]) -> None:
        """Push refspecs to a remote as a single all-or-nothing update.

        The remote operations here shell out to ``git`` rather than using
        pygit2, for three reasons. libgit2 exposes no atomic multi-ref push,
        and atomicity is the point: pushing the release commit and its tag in
        one ref transaction removes the window where the commit lands and the
        tag does not, which otherwise leaves the version files and the tag
        history disagreeing with nothing to repair it. ``git`` also inherits
        the ambient credential setup (CI checkout, ssh agent, credential
        helper) instead of needing pygit2 callbacks. And it keeps the four
        remote/reset operations on one mechanism.
        """
        completed = self._run_git("push", "--atomic", remote, *refspecs, check=False)
        if completed.returncode != 0:
            raise PushRejected(
                f"git push --atomic {redact_remote(remote)} "
                f"{' '.join(refspecs)} failed "
                f"(exit {completed.returncode}):\n"
                f"{scrub_credentials(completed.stderr.strip())}",
                non_fast_forward=_is_non_fast_forward(
                    f"{completed.stdout}\n{completed.stderr}"
                ),
            )

    def reset_keep(self, ref: str) -> None:
        """Move HEAD to ``ref``, refusing to overwrite local changes.

        ``--keep`` rather than ``--hard``: it rewrites only files that differ
        between HEAD and the target, and aborts if one of them is modified
        locally. The rollback paths depend on that — after ``release()`` the
        only differing files are the release's own assets, so a build command
        that edited some *other* tracked file is left exactly as it is.

        The index must be re-read afterwards. pygit2 caches it in memory, and
        the reset rewrote it on disk, so ``create_commit`` — which commits
        ``index.write_tree()``, the *whole* index — would otherwise write the
        pre-reset snapshot and silently revert whatever the reset brought in.
        """
        self._run_git("reset", "--keep", ref)
        self._repo.index.read(True)

    def delete_tag(self, name: str) -> None:
        """Delete a tag from the local repository only.

        An absent tag is tolerated; anything else raises. The caller deletes
        the tag so that the reset which follows cannot leave it pointing at a
        discarded commit, so swallowing a real failure (a lock, a corrupt
        ref) would defeat exactly the invariant this call exists to keep.
        """
        completed = self._run_git("tag", "-d", name, check=False)
        if completed.returncode == 0 or _is_missing_tag(completed.stderr):
            return
        raise RuntimeError(
            f"git tag -d {name} failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )

    def resolve(self, ref: str) -> str:
        """Resolve a ref to its commit SHA."""
        return self._run_git("rev-parse", ref).stdout.strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` is reachable from ``descendant``."""
        completed = self._run_git(
            "merge-base", "--is-ancestor", ancestor, descendant, check=False
        )
        # 0 = yes, 1 = no, anything else = git could not answer (bad ref,
        # damaged repository). Conflating the last with "no" would send the
        # caller down the divergence path — reset and "please rebase" — for
        # what is actually an operational failure. Surface it instead.
        if completed.returncode == 0:
            return True
        if completed.returncode == 1:
            return False
        raise RuntimeError(
            f"git merge-base --is-ancestor {ancestor} {descendant} failed "
            f"(exit {completed.returncode}): "
            f"{scrub_credentials(completed.stderr.strip())}"
        )

    def is_dirty(self) -> bool:
        """Whether the worktree has any local state, tracked or untracked.

        Untracked files count. An earlier version excluded them, on the
        reasoning that a reset leaves untracked files alone — which is only
        true while the path is *absent* from the tree being reset onto. If a
        concurrent release adds a tracked file at a path where an untracked
        one sits, ``git reset --keep`` aborts rather than overwrite it, and
        the retry fails midway.

        Ignored files do not count: ``git status --porcelain`` honours
        ``.gitignore``, so build output and virtualenvs do not block a
        release.
        """
        # --untracked-files=normal is passed explicitly: status honours the
        # user's status.showUntrackedFiles setting, so without it a config of
        # "no" would silently report a worktree clean and disable this guard.
        completed = self._run_git("status", "--porcelain", "--untracked-files=normal")
        return bool(completed.stdout.strip())

    def _run_git(
        self, *args: str, check: bool = True
    ) -> "subprocess.CompletedProcess[str]":
        """Run a git command in the repository working directory.

        A failure raises ``CalledProcessError``, whose message repeats the
        whole argument list — including a remote given as a credential-bearing
        URL. That exception propagates to the CLI's generic handler and gets
        printed, so the arguments are redacted here rather than at each call
        site: this is the one place every git invocation passes through.
        """
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(self.get_repo_root()),
                capture_output=True,
                text=True,
                check=check,
                # Several callers classify git's messages by their English
                # wording. Pin the locale so a translated git cannot turn a
                # recognised condition into an unrecognised one.
                env={**os.environ, "LC_ALL": "C"},
            )
        except subprocess.CalledProcessError as exc:
            exc.cmd = [scrub_credentials(str(arg)) for arg in exc.cmd]
            if isinstance(exc.output, str):
                exc.output = scrub_credentials(exc.output)
            if isinstance(exc.stderr, str):
                exc.stderr = scrub_credentials(exc.stderr)
            raise

    def _matches_pattern(self, tag_name: str, pattern: str) -> bool:
        """Check if a tag matches a glob pattern."""
        if pattern.endswith("*"):
            prefix = pattern.rstrip("*")
            return tag_name.startswith(prefix)
        return tag_name == pattern

    def _file_matches_filters(self, file_path: Path, filters: list[str]) -> bool:
        """Check if a file path matches any of the filter patterns."""
        for pattern in filters:
            if pattern == ".":
                return True

            pattern_path = Path(pattern)
            if pattern.endswith("**"):
                # Match directory prefix
                prefix = str(pattern_path.parent)
                if str(file_path).startswith(prefix):
                    return True
            elif str(file_path).startswith(str(pattern_path)):
                return True

        return False
