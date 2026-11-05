"""Repository locators must not change the intended HTTPS API path."""

from __future__ import annotations

import unittest

from completion_verifier.remote.github import GitHubPullRequestContract


class GithubRepositoryLocatorSecurityTests(unittest.TestCase):
    def contract(self, repository: str) -> GitHubPullRequestContract:
        return GitHubPullRequestContract(
            repository=repository,
            repository_id=12345,
            pull_number=12,
            expected_head_oid="a" * 40,
            expected_base_ref="main",
            expected_state="open",
        )

    def test_dot_segments_cannot_be_used_as_owner_or_repository(self) -> None:
        for repository in ("./repository", "../repository", "owner/.", "owner/.."):
            with self.subTest(repository=repository):
                with self.assertRaises(ValueError):
                    self.contract(repository)

    def test_normal_locator_is_accepted(self) -> None:
        self.assertEqual(self.contract("valid-owner/valid.repo").repository, "valid-owner/valid.repo")


if __name__ == "__main__":
    unittest.main()
