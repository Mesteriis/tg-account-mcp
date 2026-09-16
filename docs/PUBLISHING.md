# Publishing and release guide

This repository is prepared for GitHub, PyPI, GitHub Container Registry (GHCR), and the official
MCP Registry. Its canonical source is <https://github.com/Mesteriis/tg-account-mcp>.

## 1. Create the public GitHub repository

From this directory, after reviewing the files that will become public:

```sh
git init
git add .
git commit -m "Initial open-source release"
gh repo create tg-account-mcp --public --source=. --remote=origin --push
```

Enable these repository settings:

- private vulnerability reporting;
- branch protection with the `test` CI job required;
- Dependabot alerts and secret scanning;
- Discussions if user support should be separate from bug reports.

Add the topics `mcp`, `telegram`, `telethon`, `ai-agents`, `self-hosted`, and `python`. The package
metadata already contains the canonical project URLs.

## 2. Configure PyPI Trusted Publishing

The distribution name is `tg-account-mcp`. At the time this guide was written, the PyPI JSON API
returned 404 for that name; availability is not reserved until the first successful publication.

Create a pending publisher at <https://pypi.org/manage/account/publishing/> with:

- PyPI project name: `tg-account-mcp`;
- the selected GitHub owner and repository;
- workflow: `release.yml`;
- environment: `pypi`.

Create the `pypi` environment in GitHub and require a maintainer approval. The release workflow
uses OIDC Trusted Publishing and does not require a long-lived PyPI token.

## 3. Publish a release

Update `pyproject.toml`, `src/tg_mcp/__init__.py`, and `CHANGELOG.md` to the same version. Run all
checks locally, commit the change, then create a matching tag:

```sh
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
```

The release workflow verifies that the tag matches `pyproject.toml`, runs lint and tests, builds
the Python distributions, publishes them to PyPI, pushes versioned and `latest` images to GHCR,
and creates a GitHub Release with the distributions attached.

After the first container publication, make the GHCR package public and connect it to the
repository if GitHub has not done so automatically.

## 4. Publish MCP discovery metadata

The official MCP Registry is a metadata registry; it does not host packages or the server. Wait
until the GitHub and PyPI publications are live, then install the official publisher and run:

```sh
mcp-publisher init
mcp-publisher login github
mcp-publisher publish
```

Use the verified name `io.github.mesteriis/tg-account-mcp`. The README and OCI image already carry
the matching ownership markers required by the registry.

This service needs persistent private state and user-specific Telegram credentials. Prefer a
package or OCI entry for self-hosting. Publish it as a remote MCP server only if a real HTTPS
deployment and its operating model are ready for third-party users.

The MCP Registry is currently in preview, so validate `server.json` against the current schema
and publisher before each release.

## 5. Secondary discovery

After the official entry is searchable, submit the same repository and documentation to
[Smithery](https://smithery.ai/). Describe it as a self-hosted, stateful server and make the
Telegram API credentials, session persistence, Bearer authentication, and single-replica
constraint explicit.

## Release checklist

- [ ] Public version and changelog agree.
- [ ] `uv run ruff check .`, formatting, tests, package build, Compose validation, and Docker build pass.
- [ ] Wheel and source distribution contain `LICENSE` and no local state or secrets.
- [ ] The tag is signed or annotated and matches the package version.
- [ ] The GitHub `pypi` environment approval is enabled.
- [ ] PyPI and GHCR artifacts install and start in a clean environment.
- [ ] MCP Registry metadata matches the published package and actual transport.
- [ ] Release notes call out migrations, breaking changes, and security fixes.
