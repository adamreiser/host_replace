# Releasing `host-replace`

This project publishes to PyPI via GitHub Actions using trusted publishing (OIDC), configured in `.github/workflows/publish.yml`.

## Release flow

1. Bump `project.version` in `pyproject.toml`.
2. Commit and merge the version bump.
3. Create and publish a GitHub release with tag `vX.Y.Z`.
4. The publish workflow validates tag/version match, builds artifacts, and publishes to PyPI.
