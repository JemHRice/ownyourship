# Contributing to OwnYourShip

Thanks for taking a look. This project is developed test-first; the notes below
describe the workflow so changes stay reviewable and the history stays honest.

## Local setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e ".[test]"
pytest
```

`pytest` needs no Anthropic API key and makes no network calls: the quiz code
takes an injected client and the tests pass a fake (see `tests/conftest.py`).

## Test-driven development (red → green)

Every behavioural change goes through a red/green loop, and the git history
reflects it:

1. **Red.** Write a test that captures the desired behaviour and watch it fail.
   Commit it on its own: `test: add failing tests for <behaviour>`.
2. **Green.** Write the minimum code to make it pass: `feat: <behaviour>` (or
   `fix:`). The CI run on the pull request shows the test going from red to green.
3. **Refactor.** Clean up with the tests still green: `refactor: ...`.

Keeping the red commit and the green commit separate on the branch is what makes
the discipline visible to a reviewer. The pull request is squash- or merge-ed so
`master` stays green on every commit while the branch preserves the story.

## Branches and pull requests

- Never commit directly to `master`. Branch per change:
  - `feat/<slug>` - new behaviour
  - `fix/<slug>` - bug fix
  - `refactor/<slug>`, `docs/<slug>`, `ci/<slug>`, `test/<slug>` - everything else
- Open a pull request into `master`. Fill in the template (summary + test plan).
- CI (`.github/workflows/ci.yml`) must be green before merge. It runs the full
  suite on Python 3.10 and 3.13.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org): a `type:` prefix and
an imperative subject (`add`, not `added`). Common types: `feat`, `fix`,
`test`, `refactor`, `docs`, `ci`, `chore`. Explain the *why* in the body when the
change isn't obvious.
