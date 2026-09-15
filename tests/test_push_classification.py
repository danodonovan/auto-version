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

from auto_version.git.interface import redact_remote
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
    assert (
        _is_non_fast_forward(
            "REMOTE: ERROR: CANNOT LOCK REF 'X': IS AT EDA8436EC6797C6E "
            "BUT EXPECTED 5959469FC1FD5E95"
        )
        is True
    )


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


# --- real captured output: a lock that is held or stale (NOT contention) ---

STALE_LOCK = """\
remote: error: cannot lock ref 'refs/heads/main': Unable to create '/tmp/t2/origin.git/./refs/heads/main.lock': File exists.
 ! [remote rejected] HEAD -> main (atomic transaction failed)
error: failed to push some refs to '/tmp/t2/origin.git'
"""


def test_stale_lock_is_not_retryable():
    """ "cannot lock ref" alone is not contention.

    A held or stale lock file produces the same opening phrase as a failed
    compare-and-swap but without the "is at X but expected Y" detail.
    Retrying cannot clear it, and classifying it as contention would discard
    a perfectly good release on exhaustion rather than keeping it to push by
    hand.
    """
    assert _is_non_fast_forward(STALE_LOCK) is False


def test_cas_failure_needs_the_whole_form_on_one_line():
    """Contention is the complete compare-and-swap form, on a single line.

    Testing the phrases independently across the whole output would let a
    server emit them in unrelated `remote:` lines and be read as contention,
    which enters the destructive retry-and-discard path.
    """
    oids = "is at eda8436ec6797c6e but expected 5959469fc1fd5e95"
    assert _is_non_fast_forward("cannot lock ref 'refs/heads/main'") is False
    assert _is_non_fast_forward(oids) is False
    # both phrases present, but on separate lines: not a CAS rejection
    assert _is_non_fast_forward(f"remote: cannot lock ref 'x'\nremote: {oids}") is False
    assert _is_non_fast_forward(f"cannot lock ref 'refs/heads/main': {oids}") is True
    # a plausible-looking pair without object ids is not the CAS form either
    assert (
        _is_non_fast_forward("cannot lock ref 'x': is at HEAD but expected main")
        is False
    )


def test_cas_failure_accepts_sha256_object_ids():
    """SHA-256 repositories report 64-hex object ids in CAS failures."""
    current = "a" * 64
    expected = "b" * 64
    output = (
        "remote: error: cannot lock ref 'refs/heads/main': "
        f"is at {current} but expected {expected}"
    )
    assert _is_non_fast_forward(output) is True


# --- credentials must not reach logs ---


def test_redacts_credentials_in_url_remotes():
    """A URL remote can carry a token, and these strings reach CI logs."""
    assert (
        redact_remote("https://ghp_secret123@github.com/healx/healnet.git")
        == "https://***@github.com/healx/healnet.git"
    )
    assert (
        redact_remote("https://user:pa55w0rd@example.com/repo.git")
        == "https://***@example.com/repo.git"
    )


def test_leaves_ordinary_remotes_alone():
    """Names and scp-style remotes carry no secret and must stay readable."""
    assert redact_remote("origin") == "origin"
    assert redact_remote("git@github.com:healx/healnet.git") == (
        "git@github.com:healx/healnet.git"
    )
    assert redact_remote("https://github.com/healx/healnet.git") == (
        "https://github.com/healx/healnet.git"
    )


# --- real captured output: a hook whose advice happens to contain a marker ---

HOOK_ADVISING_FETCH = """\
remote: error: policy: your branch is behind, please fetch first and rebase
 ! [remote rejected] HEAD -> main (pre-receive hook declined)
error: failed to push some refs to '/tmp/t6/origin.git'
"""


def test_hook_advice_containing_a_marker_is_not_retryable():
    """A server can print anything; only git's own status line counts.

    Captured from a pre-receive hook that prints "please fetch first". Read
    across the whole output, that phrase looks like contention — and treating
    it as such would delete the tag, reset, and discard a valid release the
    server had simply refused.
    """
    assert _is_non_fast_forward(HOOK_ADVISING_FETCH) is False


def test_markers_are_read_from_the_rejected_status_line_only():
    """ "! [rejected]" is git rejecting; "! [remote rejected]" is the server."""
    assert _is_non_fast_forward(" ! [rejected]  HEAD -> main (fetch first)") is True
    assert (
        _is_non_fast_forward(" ! [remote rejected]  HEAD -> main (fetch first)")
        is False
    )
