"""Offline tests for the litigation substantive-entry classifier and helpers.

Pure functions only -- no network, no DB. Uses the real config term lists so the
test guards the actual promotion rule. Run:  pytest tests/test_litigation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import config  # noqa: E402
from collectors import litigation as lit  # noqa: E402


def _lists():
    l = config.load_sources()["litigation"]
    return l.get("substantive_entry_types", []), l.get("excluded_entry_phrases", [])


def test_substantive_promoted():
    types, ex = _lists()
    S = lambda d: lit.is_substantive(d, types, ex)
    assert S("COMPLAINT against All Defendants filed by COMMON CAUSE")
    assert S("MOTION to Dismiss, MOTION for Summary Judgment by TODD BLANCHE, U.S. DEPARTMENT OF JUSTICE.")
    assert S("Memorandum in opposition to re 32 MOTION to Dismiss filed by COMMON CAUSE")
    assert S("Joint MOTION for Order for Expedited Dispositive Motion Briefing Schedule")
    assert S("ORDER granting motion to dismiss")
    assert S("NOTICE OF APPEAL by COMMON CAUSE")


def test_noise_excluded():
    types, ex = _lists()
    S = lambda d: lit.is_substantive(d, types, ex)
    assert not S("NOTICE of Appearance by Jane Petersen Bentrott on behalf of COMMON CAUSE")
    assert not S("MOTION for Leave to Appear Pro Hac Vice :Attorney Name- Sara Chimene-Weiss")
    assert not S("LCvR 26.1 CERTIFICATE OF DISCLOSURE of Corporate Affiliations and Financial Interests")
    assert not S("SUMMONS (3) Issued Electronically as to All Defendants")
    assert not S("RETURN OF SERVICE/AFFIDAVIT of Summons and Complaint Executed")
    assert not S("ORDER granting 4 Motion for Leave to Appear Pro Hac Vice")  # order, but pro-hac noise
    assert not S("")


def test_helpers():
    assert lit.slugify("United States v. Weber") == "united-states-v-weber"
    assert lit.split_caption("Common Cause v. U.S. Department of Justice") == ("Common Cause", "U.S. Department of Justice")
    assert lit.split_caption("No versus here") == (None, None)


if __name__ == "__main__":
    test_substantive_promoted()
    test_noise_excluded()
    test_helpers()
    print("ok")
