"""The auto-close guard: the nine keywords, the four reference forms, and the colon.

Written against a real event. `8e374d3`'s body carried `the close: #4` inside a sentence
asserting that issue #4 must stay OPEN, and the push closed it. See
tools/issue_ref_guard.py. The baseline test comes first: a guard that fires on
everything would pass every mutation below while being useless, so what this file pins
first is that ordinary prose about an issue does NOT fire.
"""
from __future__ import annotations

import pytest

from tools.issue_ref_guard import hits

# The exact string, from the commit body that closed #4 on 2026-09-18.
REAL = (
    "**#4 stays open until Corey closes it against this run.** What is owed is the "
    "first scheduled run, read for exit 0, and the close: #4 is Corey's to make."
)


def test_the_real_body_fires():
    assert hits(REAL) == ["close: #4"]


def test_the_convention_does_not_fire():
    """`issue N` is the prescribed form, and it must be writable beside the verbs."""
    body = (
        "docs(status): the register on the scheduled lane\n\n"
        "issue 4 stays open until a person closes it. The close is Corey's to make, "
        "and nothing here closes issue 4 or resolves issue 3."
    )
    assert hits(body) == []


def test_a_bare_reference_without_a_keyword_does_not_fire():
    """GitHub closes on keyword-plus-reference. A mention alone is how this project
    discusses an issue in prose, and a guard that fired on it would be passed by
    reflex."""
    assert hits("See #4 and CSU-J3/psephos#1 for the standing issues.") == []


@pytest.mark.parametrize(
    "verb",
    ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"],
)
def test_every_keyword_github_honours(verb):
    assert hits(f"This {verb} #4 on push.") == [f"{verb} #4"]


def test_keywords_are_case_insensitive():
    assert hits("Closes #4") == ["Closes #4"]
    assert hits("FIXES #4") == ["FIXES #4"]


@pytest.mark.parametrize(
    "ref",
    ["#4", "GH-4", "CSU-J3/psephos#4", "https://github.com/CSU-J3/psephos/issues/4"],
)
def test_every_reference_form(ref):
    assert hits(f"closes {ref}") == [f"closes {ref}"]


def test_the_colon_separator_is_covered():
    """Not in GitHub's documented syntax, and it is what actually fired."""
    assert hits("the close: #4") == ["close: #4"]


def test_the_separator_tolerates_a_newline():
    assert hits("nothing here is a close\n\n#4 stays open") == ["close\n\n#4"]


def test_a_verb_inside_a_longer_word_does_not_fire():
    """`\b` on the keyword, so `disclosed` and `prefixes` are prose, not keywords."""
    assert hits("disclosed #4") == []
    assert hits("prefixes #4") == []


def test_the_conventional_commit_footer_fires_too():
    """Deliberate: the intentional-close footer is the same syntax, so the rule is
    `never in this project` rather than `avoid the verbs`. A guard with an exemption
    for the intentional form has no edge left to sit on."""
    assert hits("feat(audit): the register\n\nCloses #4") == ["Closes #4"]


def test_several_in_one_body_are_all_reported():
    assert hits("closes #4 and fixes GH-3") == ["closes #4", "fixes GH-3"]
