"""Keep release PR CI automatic without changing bot-owned publication."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_only_the_named_organization_secret_is_forwarded():
    caller = workflow("release.yml")["jobs"]["release-please"]
    assert caller["secrets"] == {"PERSONAL_ACCESS_TOKEN": "${{ secrets.PERSONAL_ACCESS_TOKEN }}"}
    declaration = workflow("release-please.yml")["on"]["workflow_call"]["secrets"]
    assert set(declaration) == {"PERSONAL_ACCESS_TOKEN"}
    assert declaration["PERSONAL_ACCESS_TOKEN"]["required"] == "true"


def test_pr_and_release_credentials_have_separate_roles():
    job = workflow("release-please.yml")["jobs"]["release-please"]
    steps = {step.get("id"): step for step in job["steps"]}
    assert steps["release"]["with"] == {
        "token": "${{ secrets.GITHUB_TOKEN }}",
        "skip-github-pull-request": "true",
    }
    assert steps["release-pr"]["with"] == {
        "token": "${{ secrets.PERSONAL_ACCESS_TOKEN }}",
        "skip-github-release": "true",
    }
    assert steps["release"]["uses"] == steps["release-pr"]["uses"]
    assert all("steps.release.outputs." in value for value in job["outputs"].values())
    assert all("continue-on-error" not in step for step in job["steps"])


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is unavailable")
@pytest.mark.parametrize("token,expected", [("", 1), ("offline-fixture-only", 0)])
def test_missing_token_fails_before_release_without_disclosing_value(token, expected):
    preflight = workflow("release-please.yml")["jobs"]["release-please"]["steps"][0]
    assert preflight["env"] == {"RELEASE_PR_TOKEN": "${{ secrets.PERSONAL_ACCESS_TOKEN }}"}
    result = subprocess.run(
        ["bash", "-eu", "-c", preflight["run"]],
        env={**os.environ, "RELEASE_PR_TOKEN": token},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected
    assert "offline-fixture-only" not in result.stdout + result.stderr


def test_pr_refresh_failure_does_not_strand_a_created_release():
    jobs = workflow("release.yml")["jobs"]
    assert jobs["artifacts"]["needs"] == "release-please"
    assert jobs["artifacts"]["if"] == (
        "${{ !cancelled() && needs.release-please.outputs.release_created == 'true' }}"
    )
    assert jobs["publish-pypi"]["needs"] == ["release-please", "artifacts"]
    assert jobs["publish-pypi"]["if"] == (
        "${{ !cancelled() && needs.artifacts.result == 'success' "
        "&& needs.release-please.outputs.release_created == 'true' }}"
    )
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"
    validation = jobs["artifacts"]["steps"][0]
    assert 'test "$tag_commit" = "$RELEASE_SHA"' in validation["run"]
    assert 'test "$GITHUB_REPOSITORY" = "dcc-mcp/dcc-mcp-capcut"' in validation["run"]


@pytest.mark.parametrize(
    "cancelled,created,artifact_result,build_expected,publish_expected",
    [
        (False, "true", "success", True, True),
        (False, "true", "failure", True, False),
        (False, "true", "skipped", True, False),
        (False, "", "success", False, False),
        (False, "false", "success", False, False),
        (True, "true", "success", False, False),
    ],
)
def test_publication_conditions_fail_closed(
    cancelled, created, artifact_result, build_expected, publish_expected
):
    jobs = workflow("release.yml")["jobs"]

    def evaluate(expression):
        # Evaluate only this pinned, boolean-only condition vocabulary, offline.
        expression = expression.removeprefix("${{").removesuffix("}}")
        expression = expression.replace("!cancelled()", repr(not cancelled))
        expression = expression.replace(
            "needs.release-please.outputs.release_created", repr(created)
        )
        expression = expression.replace("needs.artifacts.result", repr(artifact_result))
        return eval(expression.replace("&&", " and "), {"__builtins__": {}})

    assert evaluate(jobs["artifacts"]["if"]) is build_expected
    assert evaluate(jobs["publish-pypi"]["if"]) is publish_expected
