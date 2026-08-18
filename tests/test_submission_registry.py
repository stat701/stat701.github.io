from __future__ import annotations

import json
import unittest
from unittest import mock

from scripts.submission_registry import (
    AUTHORIZED_MAINTAINER_ID,
    FIXED_REPOSITORY,
    GITHUB_ACTIONS_BOT_ID,
    GITHUB_ACTIONS_BOT_LOGIN,
    GITHUB_ACTIONS_BOT_TYPE,
    REGISTRY_ISSUE_NUMBER,
    REGISTRY_ISSUE_TITLE,
    REGISTRY_MARKER_PREFIX,
    OwnershipError,
    RegisteredOwner,
    RegistrationError,
    RegistryConflictError,
    RegistryTrustError,
    StudentRegistry,
    _validated_registry,
    check_owner,
    format_registry_marker,
    is_authorized_maintainer,
    load_registry,
    parse_registry_marker,
    register_owner,
    resolve_owner,
)


def owner(
    record_id: str = "fall-2026-01",
    user_id: int = 90_001,
    login: str = "ada-student",
    *,
    source_pr: int = 11,
) -> RegisteredOwner:
    return RegisteredOwner(
        record_id=record_id,
        github_user_id=user_id,
        github_login=login,
        source_pr=source_pr,
        source_head_sha="a" * 40,
        authorized_by_user_id=AUTHORIZED_MAINTAINER_ID,
        authorized_by_login="volfovsky",
        workflow_run_id=777,
    )


def trusted_bot() -> dict[str, object]:
    return {
        "id": GITHUB_ACTIONS_BOT_ID,
        "login": GITHUB_ACTIONS_BOT_LOGIN,
        "type": GITHUB_ACTIONS_BOT_TYPE,
    }


def registry_issue(**changes: object) -> dict[str, object]:
    repository_url = f"https://api.github.com/repos/{FIXED_REPOSITORY}"
    result: dict[str, object] = {
        "number": REGISTRY_ISSUE_NUMBER,
        "repository_url": repository_url,
        "url": f"{repository_url}/issues/{REGISTRY_ISSUE_NUMBER}",
        "title": REGISTRY_ISSUE_TITLE,
        "state": "open",
        "locked": True,
    }
    result.update(changes)
    return result


def trusted_comment(value: RegisteredOwner) -> dict[str, object]:
    return {"id": 100, "user": trusted_bot(), "body": format_registry_marker(value)}


class MarkerTests(unittest.TestCase):
    def test_marker_is_hidden_single_line_canonical_json(self) -> None:
        value = owner()
        marker = format_registry_marker(value)

        self.assertTrue(marker.startswith(REGISTRY_MARKER_PREFIX))
        self.assertTrue(marker.endswith(" -->"))
        self.assertNotIn("\n", marker)
        self.assertEqual(parse_registry_marker(marker), value)
        encoded = marker[len(REGISTRY_MARKER_PREFIX) : -len(" -->")]
        self.assertEqual(encoded, json.dumps(json.loads(encoded), sort_keys=True, separators=(",", ":")))

    def test_noncanonical_json_and_unexpected_fields_fail_closed(self) -> None:
        marker = format_registry_marker(owner())
        encoded = marker[len(REGISTRY_MARKER_PREFIX) : -len(" -->")]
        payload = json.loads(encoded)

        noncanonical = f"{REGISTRY_MARKER_PREFIX}{json.dumps(payload)} -->"
        with self.assertRaisesRegex(RegistryTrustError, "canonical"):
            parse_registry_marker(noncanonical)

        payload["surprise"] = True
        extra = (
            f"{REGISTRY_MARKER_PREFIX}"
            f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))} -->"
        )
        with self.assertRaisesRegex(RegistryTrustError, "unexpected or missing"):
            parse_registry_marker(extra)

    def test_multiline_or_visible_wrapper_fails_closed(self) -> None:
        marker = format_registry_marker(owner())
        with self.assertRaisesRegex(RegistryTrustError, "one line"):
            parse_registry_marker(marker + "\n")
        with self.assertRaisesRegex(RegistryTrustError, "malformed"):
            parse_registry_marker("registered " + marker)


class RegistryLoadTests(unittest.TestCase):
    def test_loads_only_exact_trusted_bot_comments(self) -> None:
        expected = owner()
        spoof = trusted_comment(owner("fall-2026-02", 90_002, "grace"))
        spoof["user"] = {"id": 222, "login": "student", "type": "User"}
        wrong_bot_login = trusted_comment(owner("fall-2026-03", 90_003, "fisher"))
        wrong_bot_login["user"] = {
            "id": GITHUB_ACTIONS_BOT_ID,
            "login": "github-actions-lookalike",
            "type": "Bot",
        }

        with mock.patch(
            "scripts.submission_registry._github_request",
            side_effect=[registry_issue(), [spoof, wrong_bot_login, trusted_comment(expected)]],
        ) as request:
            registry = load_registry(token="opaque", repository=FIXED_REPOSITORY)

        self.assertEqual(registry.owners, (expected,))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(resolve_owner(registry, expected.record_id), expected)

    def test_malformed_marker_from_trusted_bot_fails_closed(self) -> None:
        malformed = {
            "id": 100,
            "user": trusted_bot(),
            "body": "<!-- stat701-student-account-registry:v1:not-json -->",
        }
        with mock.patch(
            "scripts.submission_registry._github_request",
            side_effect=[registry_issue(), [malformed]],
        ):
            with self.assertRaisesRegex(RegistryTrustError, "invalid JSON"):
                load_registry(token="opaque", repository=FIXED_REPOSITORY)

    def test_unrelated_trusted_bot_comment_is_ignored(self) -> None:
        comment = {"id": 100, "user": trusted_bot(), "body": "ordinary automation note"}
        with mock.patch(
            "scripts.submission_registry._github_request",
            side_effect=[registry_issue(), [comment]],
        ):
            registry = load_registry(token="opaque", repository=FIXED_REPOSITORY)
        self.assertEqual(registry.owners, ())

    def test_fixed_issue_trust_properties_are_all_required(self) -> None:
        cases = {
            "number": {"number": 8},
            "repository": {"repository_url": "https://api.github.com/repos/attacker/repo"},
            "url": {"url": "https://api.github.com/repos/attacker/repo/issues/7"},
            "title": {"title": "similar title"},
            "state": {"state": "closed"},
            "locked": {"locked": False},
            "pull request": {"pull_request": {"url": "example"}},
        }
        for label, change in cases.items():
            with self.subTest(label=label), mock.patch(
                "scripts.submission_registry._github_request",
                return_value=registry_issue(**change),
            ):
                with self.assertRaises(RegistryTrustError):
                    load_registry(token="opaque", repository=FIXED_REPOSITORY)

    def test_wrong_repository_argument_fails_before_network(self) -> None:
        with mock.patch("scripts.submission_registry._github_request") as request:
            with self.assertRaisesRegex(RegistryTrustError, "fixed"):
                load_registry(token="opaque", repository="attacker/repo")
        request.assert_not_called()


class ConflictTests(unittest.TestCase):
    def test_duplicate_same_record_and_stable_id_is_idempotent(self) -> None:
        first = owner()
        renamed_duplicate = owner(login="ada-renamed", source_pr=12)
        registry = _validated_registry([first, renamed_duplicate])
        self.assertEqual(registry.owners, (first,))

    def test_different_users_cannot_own_same_record(self) -> None:
        with self.assertRaisesRegex(RegistryConflictError, "conflicting owners"):
            _validated_registry([owner(), owner(user_id=90_002, login="grace")])

    def test_one_user_cannot_own_two_records(self) -> None:
        with self.assertRaisesRegex(RegistryConflictError, "more than one"):
            _validated_registry([owner(), owner("fall-2026-02")])


class OwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registered = owner()
        self.registry = StudentRegistry((self.registered,))

    def test_stable_id_matches_even_after_login_rename(self) -> None:
        decision = check_owner(
            self.registry,
            record_id=self.registered.record_id,
            submission_type="metadata",
            author_user_id=self.registered.github_user_id,
            author_login="new-login",
            author_type="User",
            same_repository=False,
        )
        self.assertEqual(decision.status, "owner_match")
        self.assertEqual(decision.owner, self.registered)

    def test_matching_login_cannot_substitute_for_wrong_stable_id(self) -> None:
        with self.assertRaisesRegex(OwnershipError, "does not own"):
            check_owner(
                self.registry,
                record_id=self.registered.record_id,
                submission_type="slides",
                author_user_id=90_999,
                author_login=self.registered.github_login,
                author_type="User",
                same_repository=False,
            )

    def test_unbound_metadata_requires_registration_but_is_allowed(self) -> None:
        decision = check_owner(
            StudentRegistry(()),
            record_id="fall-2026-02",
            submission_type="metadata",
            author_user_id=90_002,
            author_login="new-student",
            author_type="User",
            same_repository=False,
        )
        self.assertEqual(decision.status, "registration_required")
        self.assertTrue(decision.registration_required)

    def test_unbound_slides_fail(self) -> None:
        with self.assertRaisesRegex(OwnershipError, "no registered"):
            check_owner(
                StudentRegistry(()),
                record_id="fall-2026-02",
                submission_type="slides",
                author_user_id=90_002,
                author_login="new-student",
                author_type="User",
                same_repository=False,
            )

    def test_maintainer_override_requires_same_repository(self) -> None:
        kwargs = {
            "record_id": self.registered.record_id,
            "submission_type": "metadata",
            "author_user_id": AUTHORIZED_MAINTAINER_ID,
            "author_login": "volfovsky-renamed",
            "author_type": "User",
        }
        decision = check_owner(self.registry, same_repository=True, **kwargs)
        self.assertEqual(decision.status, "maintainer_override")
        self.assertTrue(decision.maintainer_override)
        with self.assertRaises(OwnershipError):
            check_owner(self.registry, same_repository=False, **kwargs)

    def test_maintainer_authority_uses_id_and_type_not_login(self) -> None:
        self.assertTrue(
            is_authorized_maintainer(
                user_id=AUTHORIZED_MAINTAINER_ID,
                login="renamed-maintainer",
                user_type="User",
            )
        )
        self.assertFalse(
            is_authorized_maintainer(
                user_id=AUTHORIZED_MAINTAINER_ID + 1,
                login="volfovsky",
                user_type="User",
            )
        )
        self.assertFalse(
            is_authorized_maintainer(
                user_id=AUTHORIZED_MAINTAINER_ID,
                login="volfovsky",
                user_type="Bot",
            )
        )


class RegistrationTests(unittest.TestCase):
    def registration_kwargs(self, **changes: object) -> dict[str, object]:
        result: dict[str, object] = {
            "token": "opaque",
            "repository": FIXED_REPOSITORY,
            "record_id": "fall-2026-01",
            "github_user_id": 90_001,
            "github_login": "ada-student",
            "github_user_type": "User",
            "source_pr": 11,
            "source_head_sha": "a" * 40,
            "authorized_by_user_id": AUTHORIZED_MAINTAINER_ID,
            "authorized_by_login": "volfovsky",
            "authorized_by_type": "User",
            "workflow_run_id": 777,
        }
        result.update(changes)
        return result

    def test_idempotent_registration_does_not_post_again(self) -> None:
        existing = owner()
        with mock.patch(
            "scripts.submission_registry.load_registry",
            return_value=StudentRegistry((existing,)),
        ), mock.patch("scripts.submission_registry._github_request") as request:
            result = register_owner(**self.registration_kwargs())  # type: ignore[arg-type]

        self.assertFalse(result.created)
        self.assertEqual(result.owner, existing)
        request.assert_not_called()

    def test_success_appends_exact_event_and_verifies_bot_response(self) -> None:
        def post_response(**kwargs: object) -> dict[str, object]:
            body = kwargs["payload"]["body"]  # type: ignore[index]
            return {"id": 123, "user": trusted_bot(), "body": body}

        with mock.patch(
            "scripts.submission_registry.load_registry",
            return_value=StudentRegistry(()),
        ), mock.patch(
            "scripts.submission_registry._github_request", side_effect=post_response
        ) as request:
            result = register_owner(**self.registration_kwargs())  # type: ignore[arg-type]

        self.assertTrue(result.created)
        call = request.call_args.kwargs
        self.assertEqual(call["method"], "POST")
        self.assertEqual(
            call["endpoint"],
            f"/repos/{FIXED_REPOSITORY}/issues/{REGISTRY_ISSUE_NUMBER}/comments",
        )
        self.assertEqual(parse_registry_marker(call["payload"]["body"]), result.owner)

    def test_conflicting_record_or_duplicate_user_fails_without_post(self) -> None:
        scenarios = (
            (StudentRegistry((owner(user_id=90_002, login="other"),)), "already bound"),
            (
                StudentRegistry((owner("fall-2026-02", 90_001, "ada-student"),)),
                "already owns",
            ),
        )
        for registry, message in scenarios:
            with self.subTest(message=message), mock.patch(
                "scripts.submission_registry.load_registry", return_value=registry
            ), mock.patch("scripts.submission_registry._github_request") as request:
                with self.assertRaisesRegex(RegistryConflictError, message):
                    register_owner(**self.registration_kwargs())  # type: ignore[arg-type]
                request.assert_not_called()

    def test_unauthorized_registrar_is_rejected_before_registry_read(self) -> None:
        cases = (
            {"authorized_by_user_id": 999},
            {"authorized_by_type": "Bot"},
        )
        for changes in cases:
            with self.subTest(changes=changes), mock.patch(
                "scripts.submission_registry.load_registry"
            ) as load:
                with self.assertRaisesRegex(RegistrationError, "authorized registrar"):
                    register_owner(**self.registration_kwargs(**changes))  # type: ignore[arg-type]
                load.assert_not_called()

    def test_registrar_rename_is_allowed_and_recorded_for_audit(self) -> None:
        def post_response(**kwargs: object) -> dict[str, object]:
            return {"user": trusted_bot(), "body": kwargs["payload"]["body"]}  # type: ignore[index]

        with mock.patch(
            "scripts.submission_registry.load_registry",
            return_value=StudentRegistry(()),
        ), mock.patch(
            "scripts.submission_registry._github_request", side_effect=post_response
        ):
            result = register_owner(
                **self.registration_kwargs(authorized_by_login="new-maintainer-login")  # type: ignore[arg-type]
            )
        self.assertEqual(result.owner.authorized_by_login, "new-maintainer-login")

    def test_maintainer_account_cannot_be_bound_as_student(self) -> None:
        with mock.patch("scripts.submission_registry.load_registry") as load:
            with self.assertRaisesRegex(RegistrationError, "cannot be a student"):
                register_owner(
                    **self.registration_kwargs(  # type: ignore[arg-type]
                        github_user_id=AUTHORIZED_MAINTAINER_ID,
                        github_login="volfovsky",
                    )
                )
            load.assert_not_called()

    def test_instructor_demo_record_can_bind_the_registrar_account(self) -> None:
        def post_response(**kwargs: object) -> dict[str, object]:
            body = kwargs["payload"]["body"]  # type: ignore[index]
            return {"id": 124, "user": trusted_bot(), "body": body}

        with mock.patch(
            "scripts.submission_registry.load_registry",
            return_value=StudentRegistry(()),
        ), mock.patch(
            "scripts.submission_registry._github_request", side_effect=post_response
        ):
            result = register_owner(
                **self.registration_kwargs(
                    record_id="fall-2026-17",
                    github_user_id=AUTHORIZED_MAINTAINER_ID,
                    github_login="volfovsky",
                )
            )  # type: ignore[arg-type]

        self.assertTrue(result.created)
        self.assertEqual(result.owner.record_id, "fall-2026-17")
        self.assertEqual(result.owner.github_user_id, AUTHORIZED_MAINTAINER_ID)


if __name__ == "__main__":
    unittest.main()
