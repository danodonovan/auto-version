"""Tests for classifying git push failures as retryable or not.

The strings below are **real** git output, captured from concurrent
``auto-version release --push`` runs against a bare repository — not
paraphrases. Getting this classification wrong is silent: a contended push
misread as fatal skips the retry and fails the release, which is exactly the
bug these cases were written to pin.

Note that the atomic and non-atomic wordings differ. ``--atomic`` reports
contention as "cannot lock ref … but expected …" plus "(atomic transaction
failed)", never the "non-fast-forward" / "fetch first" phrasing a plain push
uses.
"""

from auto_version.git.pygit2_impl import _is_missing_tag, _is_non_fast_forward

# --- real captured output: the remote moved under us (retryable) ---

ATOMIC_CONTENTION = """\
remote: error: cannot lock ref 'refs/heads/main': is at eda8436ec6797c6e6e95cb8baf524502c87e3f5d but expected 5959469fc1fd5e95f33a6b4456b62c7a62af7024
To /tmp/e3/origin.git
 ! [remote rejected] HEAD -> main (atomic transaction failed)
 ! [remote rejected] kg-1.0.1 -> kg-1.0.1 (atomic transaction failed)
error: failed to push some refs to '/tmp/e3/origin.git'
"""

PLAIN_NON_FAST_FORWARD = """\
To /tmp/racetest/origin.git
 ! [rejected]        HEAD -> main (fetch first)
error: failed to push some refs to '/tmp/racetest/origin.git'
hint: Updates were rejected because the remote contains work that you do not
hint: have locally. This is usually caused by another repository pushing to
hint: the same ref.
"""

FORCE_WITH_LEASE = """\
To github.com:healx/healnet.git
 ! [rejected]        main -> main (stale info)
error: failed to push some refs to 'github.com:healx/healnet.git'
"""


def test_atomic_contention_is_retryable():
    """--atomic reports a moved ref as a lock failure, not a non-fast-forward."""
    assert _is_non_fast_forward(ATOMIC_CONTENTION) is True


def test_plain_non_fast_forward_is_retryable():
    assert _is_non_fast_forward(PLAIN_NON_FAST_FORWARD) is True


def test_stale_info_is_retryable():
    assert _is_non_fast_forward(FORCE_WITH_LEASE) is True


# --- not retryable: retrying would only repeat the failure ---


def test_auth_failure_is_not_retryable():
    output = """\
remote: Invalid username or token. Password authentication is not supported.
fatal: Authentication failed for 'https://github.com/healx/healnet/'
"""
    assert _is_non_fast_forward(output) is False


def test_unknown_remote_is_not_retryable():
    output = "fatal: 'upstram' does not appear to be a git repository\n"
    assert _is_non_fast_forward(output) is False


def test_hook_rejection_is_not_retryable():
    """A pre-receive hook refusal prints "! [remote rejected]" too.

    This is why a bare "! [rejected]" is not treated as a retry signal: the
    branch is not moving, the server is saying no, and three more attempts
    would just say no three more times.
    """
    output = """\
remote: error: GH006: Protected branch update failed for refs/heads/main.
remote: error: Required status check "ci" is expected.
To github.com:healx/healnet.git
 ! [remote rejected] HEAD -> main (protected branch hook declined)
"""
    assert _is_non_fast_forward(output) is False


def test_classification_is_case_insensitive():
    assert _is_non_fast_forward("REMOTE: ERROR: CANNOT LOCK REF 'X'") is True


# --- real captured output: `git tag -d` on a tag that is not there ---


def test_missing_tag_is_tolerated():
    """Captured verbatim from `git tag -d nope-1.2.3` (exit 1)."""
    assert _is_missing_tag("error: tag 'nope-1.2.3' not found.\n") is True


def test_other_tag_deletion_failures_propagate():
    """A lock or ref error must not be mistaken for an absent tag.

    Tolerating it would let the caller proceed to reset the worktree, leaving
    the tag pointing at the commit that reset just discarded.
    """
    output = "error: cannot lock ref 'refs/tags/kg-1.0.1': Unable to create lock file\n"
    assert _is_missing_tag(output) is False
