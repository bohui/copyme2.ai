"""Sensitive UI copy stays explicitly pending bilingual human review."""

import json
from pathlib import Path

import pytest

from scripts.check_localization_catalog import leaves


MESSAGES = Path(__file__).resolve().parents[1] / "apps/web/messages"


@pytest.mark.parametrize("sensitive_keys", [
    {
        "Collection.confirm", "Collection.confirmFirst",
        "Memoir.story.attachmentRights", "Memoir.story.attachmentRightsRequired",
        "Memoir.story.sourceNote", "Memoir.story.voiceNote",
        "Memoir.storyFlow.reviewTranscript", "Memoir.storyFlow.anonymousLinked",
    },
    {
        "AuthReminder.loginMessage", "AuthReminder.message", "AuthReminder.choiceMessage",
        "AuthReminder.identityExists", "AuthReminder.mergeExisting",
        "AuthReminder.mergeSuccess", "AuthReminder.mergeError",
        "AuthReminder.returnGuest", "AuthReminder.restoreError",
        "AuthReminder.downloadContext", "Memoir.workspace.familyPhotoHint",
    },
    {
        "Errors.paymentRequired", "Errors.entitlementRequired", "Errors.alreadyPaid",
        "Errors.invalidCheckout", "Errors.stripeMismatch", "Memoir.recall.description",
        "Memoir.recall.signIn", "Memoir.landing.freeNotice",
        "Memoir.storyFlow.paidUnlocked", "Memoir.storyFlow.pricesNote",
        "Memoir.storyFlow.paymentConfirming", "Memoir.storyFlow.paymentCancelled",
        "Memoir.storyFlow.totalToday", "Memoir.storyFlow.continueCheckout",
    },
    {
        "Memoir.conversation.opening", "Memoir.conversation.resume",
        "Memoir.conversation.fallback", "Memoir.conversation.publicCueFollowUp",
        "Memoir.conversation.publicContext", "Memoir.landing.featureContextBody",
        "Memoir.workspace.familyReferenceNote",
    },
])
def test_current_consent_payment_privacy_and_mira_copy_is_flagged(sensitive_keys):
    manifest = json.loads((MESSAGES / "human-review.json").read_text())
    assert manifest["status"] == "requires-human-review"
    assert sensitive_keys <= set(manifest["keys"])
    for locale in ("en-AU", "zh-CN"):
        assert sensitive_keys <= leaves(json.loads((MESSAGES / f"{locale}.json").read_text())).keys()


def test_all_package_claims_are_flagged_and_manifest_has_no_duplicate_keys():
    manifest = json.loads((MESSAGES / "human-review.json").read_text())
    keys = manifest["keys"]
    assert len(keys) == len(set(keys))
    messages = leaves(json.loads((MESSAGES / "en-AU.json").read_text()))
    package_keys = {key for key in messages if key.startswith("Memoir.storyFlow.plans.")}
    assert package_keys and package_keys <= set(keys)
