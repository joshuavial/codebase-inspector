# Planning brief

Working name: codebase-inspector. The product name is still open.

The inspector maps a git repository into a structured model and shows it as a layered viewer. Planning used five sample repositories, read-only:

- sample-desktop (~170 tracked files): a small Electron desktop app with a loopback service. The starter target.
- sample-apps: a TypeScript repo with several apps, a shared package and one submodule.
- sample-saas (~9.8k files): a mid-size Python and TypeScript service, with compose and a large data directory.
- sample-monorepo (~13.4k files): a large Python monorepo whose code sits in a submodule. A second checkout of the same repo (~12.2k files) checked that file ids stay stable when blobs differ.
- sample-dotnet: an ASP.NET Core and Vue app, added later to cover C# and Vue.

The plan covers the taxonomy (what levels and edges a map has), how deterministic parsing and agent judgement split, and how the viewer stays usable at monorepo scale. Decisions are in `docs/planning/decision-log.md`.
