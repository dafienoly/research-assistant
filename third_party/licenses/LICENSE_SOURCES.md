# License source register

Reviewed on 2026-07-11 against official upstream repositories:

- vectorbt: <https://github.com/polakowo/vectorbt/blob/main/LICENSE.md>
- vn.py / VeighNa: <https://github.com/vnpy/vnpy/blob/master/LICENSE>
- OpenBB: <https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE>
- FinRL classic: <https://github.com/AI4Finance-Foundation/FinRL/blob/master/LICENSE>
- FinRL-X / Trading: <https://github.com/AI4Finance-Foundation/FinRL-Trading/blob/main/LICENSE>
- Qbot: <https://github.com/UFund-Me/Qbot/blob/main/LICENSE>

This register avoids vendoring inactive frameworks' source or license payloads
into the core runtime. The installed vectorbt distribution carries its own
`LICENSE.md` in the isolated environment and is reflected in the SBOM.
