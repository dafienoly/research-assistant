# Hermes VNext Third-Party Notice

This repository uses or evaluates the following upstream projects. Inclusion
here is not an assertion that every project is installed in the core runtime.

| Project | Use in Hermes VNext | Runtime state | Upstream license | Decision |
|---|---|---|---|---|
| vectorbt 1.1.0 | isolated Fast Lane research worker | installed only in `.venv_vectorbt` | Apache-2.0 with Commons Clause | conditional research-only |
| vn.py / VeighNa | Event/OMS/Gateway design reference | not installed | MIT | deferred adapter |
| OpenBB | Provider/Fetcher/Router design and optional proxy | not installed | AGPL-3.0-only | sidecar only; legal review required |
| FinRL (classic) | offline RL research reference | not installed | MIT plus trademark notice | deferred |
| FinRL-X / Trading | weight-centric architecture reference | not installed | Apache-2.0 | reference only |
| Qbot | UI/product workflow reference | not installed or copied | MIT | reference only |

Hermes does not copy Qbot pages, use OpenBB as a silent fallback, treat
vectorbt fills as execution truth, or expose vn.py/miniQMT from the UI/API.
Package-level notices for installed transitive dependencies are represented in
the CycloneDX SBOM and remain governed by their respective upstream terms.

Official source references and the dated review are recorded in
`docs/vnext/license_review.md` and `third_party/licenses/LICENSE_SOURCES.md`.
