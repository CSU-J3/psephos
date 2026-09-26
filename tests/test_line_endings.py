"""Every tracked text file is stored LF: the line-endings gate (ruled 2026-09-26).

`.gitattributes` (`* text=auto eol=lf`) makes `git add` store a text file as LF whatever
the working copy holds. This test is the check that it did: it reads `git ls-files --eol`
over the tracked files and fails on any whose index form is not `i/lf` or `i/none` (a file
with no line ending). It runs in CI's python job, and so in `python -m tools.ci_local`,
which is what retired the manual after-`git add` read from the pre-commit ritual.

`i/crlf` or `i/mixed` means the attribute did not apply: a `-text` override, the attribute
edited away, or a path stored with CR and never renormalized. **`i/-text` fails too.** Git
decides "binary" from content, not from the attribute: one lone CR, a NUL, or UTF-16 text
makes it treat a file as binary and store its CRLF untouched, so a gate that let `-text`
through let exactly the de86aca shape through with a stray CR beside it (adversarial
review, 2026-09-26). A real binary file is named in BINARY with its reason, and the test
holds each entry to a path that exists and is stored binary. Entries with an empty `i/`
column -- symlinks and submodules, which git gives no line-ending column -- are skipped:
neither can hold a text file's CRLF.

Why the gate exists: de86aca shipped web/components/StateBillRow.tsx with all 102 lines
flipped to CRLF by a Windows write, and a diff read with CR ignored passed it as a small
change. docs/status.md, *Line endings are enforced*.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {"lf", "none"}

# Tracked binary files -> why each is binary. Empty on 2026-09-26: the tree held none.
BINARY: dict[str, str] = {}


def _entries(eol_listing: str) -> list[tuple[str, str]]:
    """(index column, path) for each line of `git ls-files --eol` output.

    Each line is `i/<index> w/<worktree> attr/<attrs>\\t<path>`; the path follows the one
    tab, whatever it contains. Only the index column is what a commit stores.
    """
    out = []
    for line in eol_listing.splitlines():
        if not line.strip():
            continue
        info, _, path = line.partition("\t")
        index = info.split()[0]
        assert index.startswith("i/"), line
        out.append((index[2:], path))
    return out


def stored_non_lf(eol_listing: str, binary: dict[str, str] = BINARY) -> list[str]:
    """Paths stored with anything but LF (or no line ending), less the declared binaries."""
    bad = []
    for index, path in _entries(eol_listing):
        if index == "":
            continue  # a symlink or submodule: git prints no line-ending column
        if index == "-text" and path in binary:
            continue
        if index not in ALLOWED:
            bad.append(f"i/{index} {path}")
    return bad


def _eol(repo: Path, env: dict | None = None) -> str:
    # check=True, never a skip: a checkout without git would otherwise pass the gate by
    # not running it. CI's actions/checkout keeps .git.
    return subprocess.run(
        ["git", "ls-files", "--eol"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
        check=True, env=env,
    ).stdout


def test_every_tracked_text_file_is_stored_lf():
    listing = _eol(ROOT)
    assert listing.strip(), "git ls-files returned nothing: not the repo"
    assert stored_non_lf(listing) == []


def test_every_declared_binary_exists_and_is_stored_binary():
    stored = dict((path, index) for index, path in _entries(_eol(ROOT)))
    for path, reason in BINARY.items():
        assert reason.strip(), path
        assert stored.get(path) == "-text", (path, stored.get(path))


def test_the_parser_reads_the_index_column_only():
    listing = (
        "i/lf    w/crlf  attr/text=auto eol=lf \tweb/lib/a.ts\n"
        "i/crlf  w/crlf  attr/                 \tweb/lib/feed.ts\n"
        "i/mixed w/mixed attr/                 \ttests/test_litigation.py\n"
        "i/none  w/none  attr/text=auto eol=lf \tdata/.gitkeep\n"
        "i/-text w/-text attr/text=auto eol=lf \tscript with a lone CR.ps1\n"
        "i/-text w/-text attr/text=auto eol=lf \timg/logo.png\n"
        "i/      w/      attr/text=auto eol=lf \tvendor/sub\n"
    )
    assert stored_non_lf(listing, binary={"img/logo.png": "a PNG"}) == [
        "i/crlf web/lib/feed.ts",
        "i/mixed tests/test_litigation.py",
        "i/-text script with a lone CR.ps1",
    ]


def _isolated_env(tmp_path: Path) -> dict:
    """git with no system, global or user-level config or attributes, and no inherited
    repository: the scratch repo's own .gitattributes is the only variable."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(home / "no-such-gitconfig"),
    })
    return env


def _scratch_repo(tmp_path: Path, attributes: str | None, content: bytes) -> tuple[Path, dict]:
    env = _isolated_env(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false"]
    subprocess.run(git + ["init", "-q", "."], cwd=repo, check=True, env=env)
    if attributes is not None:
        (repo / ".gitattributes").write_bytes(attributes.encode())
    (repo / "f.txt").write_bytes(content)
    subprocess.run(git + ["add", "-A"], cwd=repo, check=True, capture_output=True, env=env)
    return repo, env


def test_a_crlf_file_with_the_attribute_removed_reds_the_gate(tmp_path):
    repo, env = _scratch_repo(tmp_path, None, b"one\r\ntwo\r\n")
    assert stored_non_lf(_eol(repo, env)) == ["i/crlf f.txt"]


def test_the_same_crlf_write_is_stored_lf_under_the_attribute(tmp_path):
    repo, env = _scratch_repo(tmp_path, "* text=auto eol=lf\n", b"one\r\ntwo\r\n")
    assert stored_non_lf(_eol(repo, env)) == []


# The shape the attribute cannot normalize: a lone CR makes git call the file binary and
# store its CRLF as written. The gate reds on it rather than read -text as "not text".
def test_a_crlf_file_with_a_lone_cr_reds_even_under_the_attribute(tmp_path):
    repo, env = _scratch_repo(tmp_path, "* text=auto eol=lf\n", b"one\r\ntwo\r\nprogress\rdone\r\n")
    assert stored_non_lf(_eol(repo, env)) == ["i/-text f.txt"]
