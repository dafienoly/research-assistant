# V5.0 Data Source Registry

- **Version:** V5.0
- **Objective:** 数据源注册表 — centralized catalog of all available data sources

## Motivation

The existing system (`provider_matrix.py`, `baostock_data.py`, `market_fetcher.py`, `eastmoney_direct.py`, `rsscast_mcp.py`) has multiple data providers hard-wired into code with no centralized registry. Each client decides which source to use ad-hoc. This design builds the registry layer — a catalog that knows what data sources exist, what capabilities each provides, what priority they have, and whether they're healthy.

## DataSourceSpec Schema

Each registered data source carries:

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | str | Unique name (e.g. `rsscast_mcp`, `akshare_spot`) |
| `name` | str | Human-readable label |
| `category` | str | `market` / `fundamental` / `event` / `tag` / `macro` / `announcement` |
| `capabilities` | list[str] | What data it offers: `realtime_quote`, `kline_daily`, `kline_minute`, `snapshot`, `overview`, `index`, `announcement`, `fundamental` |
| `priority` | int | Ordering within category (lower = preferred) |
| `status` | str | `active` / `degraded` / `inactive` / `unchecked` |
| `config` | dict | Provider-specific config (paths, API keys, rate limits) |
| `health` | dict | Last check timestamp, success_rate (0-100), total_calls, error_count |

## Registry File Structure

Follows the Alpha Registry pattern from `factor_lab/alpha/registry.py`:

```
/mnt/d/HermesData/data_source_registry/
├── registry_index.json          # list of {source_id, name, category, status, priority, capabilities}
├── rsscast_mcp/
│   ├── data_source_spec.json    # full DataSourceSpec
│   └── health_history.jsonl     # append-only health records
├── akshare_spot/
│   ├── data_source_spec.json
│   └── health_history.jsonl
├── tencent_qt/
│   ├── data_source_spec.json
│   └── health_history.jsonl
├── sina/
│   ├── data_source_spec.json
│   └── health_history.jsonl
├── eastmoney_direct/
│   ├── data_source_spec.json
│   └── health_history.jsonl
├── baostock/
│   ├── data_source_spec.json
│   └── health_history.jsonl
├── announcement/
│   ├── data_source_spec.json
│   └── health_history.jsonl
└── config.json                   # registry-level config (default_priority_map, etc.)
```

## Modules

### `factor_lab/data_source/__init__.py`
Package init, exports key classes.

### `factor_lab/data_source/spec.py`
- `DataSourceSpec` dataclass with validation
- `DataSourceCategory`, `DataSourceCapability`, `DataSourceStatus` enums
- `validate_spec()` — ensure required fields, valid capability names

### `factor_lab/data_source/registry.py`
- `DataRegistry` class with file-based persistence
- `register(spec)` — add or update a source
- `list_sources(category=None, capability=None, status=None)` — filtered listing
- `get_source(source_id)` — fetch full spec
- `get_preferred(capability, category=None)` — highest-priority active source for a capability
- `update_status(source_id, status)` — transition status
- `delete_source(source_id)` — remove from registry
- `seed_defaults()` — populate known sources from existing system

### `factor_lab/data_source/health.py`
- `HealthTracker` class
- `record_call(source_id, success, latency_ms, error=None)` — append health record
- `check_health(source_id)` — compute health from rolling window (last 100 calls)
- `auto_update_status(source_id)` — based on health thresholds (>80% active, 50-80% degraded, <50% inactive)

### `factor_lab/data_source/discovery.py`
- `resolve_source(capability, category=None, preferred=None)` — find best source
- `list_capable(capability)` — all sources with a given capability
- `get_fallback_chain(capability)` — ordered list of sources by priority

## Health Tracking Rules

Each `record_call()` appends to `health_history.jsonl`. `check_health()` reads the last 100 entries:

| Success Rate | Status |
|---|---|
| >= 80% | `active` |
| 50-80% | `degraded` |
| < 50% | `inactive` |
| No calls yet | `unchecked` |

## Seed Data

On first run, `seed_defaults()` registers these known sources from the existing system:

| source_id | category | capabilities | priority |
|---|---|---|---|
| rsscast_mcp | market | realtime_quote, kline_daily, kline_minute, snapshot, overview, index | 1 |
| eastmoney_direct | market | realtime_quote, kline_daily | 2 |
| tencent_qt | market | realtime_quote, kline_daily | 3 |
| sina | market | realtime_quote | 4 |
| akshare_spot | market | snapshot | 1 |
| baostock | fundamental, market | fundamental, kline_daily, kline_minute | 1 |
| announcement | announcement | announcement | 1 |

## Non-goals (deferred to V5.1+)
- Pluggable provider base class → V5.1
- Real data fetching through registry → V5.1
- Data quality gates → V5.4
- No-fallback enforcement → V5.5
- Data lineage → V5.6

## Test Plan

File: `tests/test_data_source_registry.py`

| Test | Description |
|------|-------------|
| `test_spec_creation` | DataSourceSpec created with all fields |
| `test_spec_validation` | Invalid specs rejected |
| `test_register_and_list` | Register sources, list returns them |
| `test_get_source` | Fetch by source_id |
| `test_get_preferred` | Highest-priority active source returned for capability |
| `test_status_transitions` | Update status, verify correct |
| `test_delete_source` | Remove from registry |
| `test_seed_defaults` | Known sources registered correctly |
| `test_health_recording` | Record calls, check computed status |
| `test_health_thresholds` | Active/degraded/inactive transitions |
| `test_discovery_fallback` | Fallback chain by priority |
| `test_persistence` | Registry survives reload |
| `test_edge_cases` | Empty registry, unknown source, no matching capability |
