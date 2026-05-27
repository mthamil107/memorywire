# Release runbook

This runbook covers how `agent-memory-protocol` is cut to PyPI. Releases are
automated by `release-please` and published via **PyPI Trusted Publisher**
(OIDC) — there are no long-lived API tokens stored in the repo or in GitHub
Actions secrets.

## 1. One-time setup (~5 minutes, done once per project)

### 1a. Configure the PyPI Trusted Publisher

1. Sign in to <https://pypi.org/> as the project owner.
2. Open **"Your projects" → Trusted Publisher Management**
   (or visit <https://pypi.org/manage/account/publishing/>).
3. Click **"Add a new publisher" → GitHub** and paste:

   | Field                       | Value                          |
   | --------------------------- | ------------------------------ |
   | PyPI Project Name           | `agent-memory-protocol`        |
   | Owner                       | `mthamil107`                   |
   | Repository name             | `agent-memory-protocol`        |
   | Workflow filename           | `release.yml`                  |
   | Environment name            | `pypi`                         |

4. Click **Add**. PyPI now trusts that workflow + environment combination to
   upload releases without an API token.

### 1b. Repeat for TestPyPI (for `-rc` / pre-release dry runs)

1. Sign in to <https://test.pypi.org/>.
2. Go to **Trusted Publisher Management** and add a new GitHub publisher with
   the same fields as above, **except** set **Environment name** to `testpypi`.

### 1c. Configure GitHub Environments

In **GitHub repo → Settings → Environments**, create two environments:

- **`pypi`** — for production releases. Optionally add `mthamil107` as a
  required reviewer so every production publish needs a final click.
- **`testpypi`** — for pre-release dry runs; no reviewers required.

No GitHub Actions *secrets* need to be created. OIDC handles authentication.

### 1d. (Optional) Wire Zenodo for DOIs

1. Sign in to <https://zenodo.org> with your GitHub account.
2. Toggle ON the `agent-memory-protocol` repo in Zenodo's GitHub panel.
3. Update `CITATION.cff`'s `doi:` field with the concept DOI Zenodo returns.

## 2. Cutting a release (every time)

The full happy-path flow:

1. **Verify CI is green** on `main`.
2. **Find the open release-PR**. `release-please` keeps a single open PR titled
   `chore: release X.Y.Z` that contains the version bump and CHANGELOG diff
   derived from Conventional Commits since the last release.
3. **Review and merge** that PR. The merge:
   - Updates `.github/.release-please-manifest.json` to `X.Y.Z`.
   - Updates `CITATION.cff` and `src/amp/__init__.py`.
   - Rewrites `CHANGELOG.md`.
   - Creates a GitHub release with tag `vX.Y.Z`.
4. **The GitHub release publication** triggers `release.yml`, which:
   - Builds the AMP wheel + sdist with `uv build`.
   - Builds the UI wheel (FSL-licensed; attached as an artifact, **not**
     published to PyPI).
   - Publishes the AMP wheel + sdist to PyPI via Trusted Publisher (OIDC).
   - Attaches all wheels + the sdist to the GitHub release.

   The workflow fires on **`release: published`** (emitted by
   release-please when it cuts the GitHub release) **and** on `push`
   of any `v*` tag. Both trigger the same build + publish chain. The
   dual trigger exists because the `vX.Y.Z` tag is created with the
   default `GITHUB_TOKEN`, and GitHub's anti-recursion rule prevents
   that tag-push event from firing downstream workflows — so we listen
   for the release event as well to guarantee the first publish runs.
5. **Verify install**:

   ```bash
   python -m venv /tmp/amp-verify && source /tmp/amp-verify/bin/activate
   pip install agent-memory-protocol==X.Y.Z
   amp --version
   ```

   The release usually shows up on the public index within **~5 minutes** of
   the publish job finishing.

## 3. Manual fallback (if release-please breaks)

If the release-please action is down or you need to ship an out-of-band patch:

```bash
# 1. Bump CHANGELOG.md + CITATION.cff + src/amp/__init__.py by hand.
git commit -am "chore: release X.Y.Z"

# 2. Tag and push.
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

The tag push alone is enough to trigger the build + publish jobs in
`release.yml`. (release-please only owns the PR-on-`main` flow; the publish
flow is tag-driven.)

## 4. TestPyPI dry runs

To dry-run a release without touching production PyPI:

```bash
git tag v0.2.0-rc1
git push origin v0.2.0-rc1
```

Any tag that contains a `-` (rc, alpha, beta, dev) is routed to TestPyPI only.
Verify with:

```bash
pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  agent-memory-protocol==0.2.0rc1
```

You can also trigger TestPyPI manually via **Actions → Release → Run workflow →
testpypi: true** from a feature branch.

## 5. Yanking a release

If a published release has a critical bug:

1. Open <https://pypi.org/manage/project/agent-memory-protocol/releases/> and
   click **Yank** on the affected version. Yanking hides the release from
   resolvers without deleting it (existing pinned installs keep working).
2. Cut a follow-up release with the fix.

If a release contains a security-sensitive leak (credential, etc.), use the
PyPI **Delete** action on that specific version and rotate the secret.

## 6. Sanity check script

```bash
.venv/Scripts/python.exe scripts/bump_version.py
```

`scripts/bump_version.py` (idempotent, read-only by default) prints the current
version derived from `src/amp/__init__.py`, validates monotonic increase, and
lists what release-please will rewrite on the next merge. It does not modify
any files unless `--write` is passed.
