# Publishing and release guide

This repository is prepared for GitHub, PyPI, GitHub Container Registry (GHCR), and the official
MCP Registry. Its canonical source is <https://github.com/Mesteriis/tg-account-mcp>.

## 1. Public repository and release channels

As verified on 2026-09-23, the repository is public at
<https://github.com/Mesteriis/tg-account-mcp>. Release `v0.6.0` is published through GitHub Releases,
PyPI, `ghcr.io/mesteriis/tg-account-mcp:0.6.0`, and the official MCP Registry under
`io.github.Mesteriis/tg-account-mcp`.

Keep these repository settings enabled:

- private vulnerability reporting;
- branch protection with the `test` CI job required;
- Dependabot alerts and secret scanning;
- Discussions if user support should be separate from bug reports.

The repository topics and package metadata already contain the canonical project URLs.

## 2. Configure PyPI Trusted Publishing

The distribution name is `tg-account-mcp`. PyPI Trusted Publishing is active, and the release
workflow publishes the package without a long-lived PyPI token.

If the publisher must be recreated, configure it at
<https://pypi.org/manage/account/publishing/> with:

- PyPI project name: `tg-account-mcp`;
- the selected GitHub owner and repository;
- workflow: `release.yml`;
- environment: `pypi`.

The GitHub `pypi` environment should continue to require maintainer approval. The release workflow
uses OIDC Trusted Publishing and does not require a long-lived PyPI token.

## 3. Publish a release

Update `pyproject.toml`, `src/tg_mcp/__init__.py`, plugin package pins, and `CHANGELOG.md` to the
same version where applicable. Run all checks locally, commit the change, then create a matching
tag. For example, with `VERSION=0.6.1`:

```sh
VERSION=0.6.1
git tag -a "v${VERSION}" -m "v${VERSION}"
git push origin "v${VERSION}"
```

The release workflow verifies that the tag matches `pyproject.toml`, runs lint and tests, builds
the Python distributions, publishes them to PyPI, pushes versioned and `latest` images to GHCR,
and creates a GitHub Release with the distributions attached.

After the first container publication, make the GHCR package public and connect it to the
repository if GitHub has not done so automatically.

## 4. Publish MCP discovery metadata

The official MCP Registry is a metadata registry; it does not host packages or the server. The
current package is searchable as `io.github.Mesteriis/tg-account-mcp`. After each release,
validate `server.json`, install the current official publisher, and publish updated metadata:

```sh
mcp-publisher init
mcp-publisher login github
mcp-publisher publish
```

Use the verified case-sensitive name `io.github.Mesteriis/tg-account-mcp`. The README and OCI
image carry the matching ownership markers required by the registry.

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
