# Hermes VNext 许可证与依赖隔离审查

审查日期：2026-07-11。结论适用于当前工作区，不构成外部法律意见。

## 结论

Hermes Core 继续保持无 vn.py、OpenBB、FinRL、Qbot、vectorbt 依赖。唯一实际引入的上游框架是隔离环境中的 vectorbt 1.1.0，并限制为研究 Fast Lane。OpenBB、vn.py 和 FinRL 环境均为 comment-only lock，表示未安装而非“可运行”。

| 项目 | 官方许可证状态 | 当前集成 | 结论 |
|---|---|---|---|
| vectorbt 1.1.0 | Apache-2.0 + Commons Clause；上游明确限制销售主要依赖该软件功能的产品或服务 | `.venv_vectorbt` 隔离 Worker | 仅条件批准内部研究；商业分发/托管前重审 |
| vn.py / VeighNa | MIT | 未安装；Hermes 自有 Event/OMS/Gateway 适配 | 可兼容采用，但启用真实 adapter 前需独立安全验收 |
| OpenBB | AGPL-3.0-only | 未安装；只借鉴 Provider 协议，可选 HTTP Sidecar | 禁止进入 Core；启用 Sidecar 前进行 AGPL 法务审查 |
| FinRL classic | MIT，并有 FinRL 商标声明 | 未安装 | 仅研究参考；不输出生产买卖 |
| FinRL-X / Trading | Apache-2.0 | 未安装 | 权重中心架构参考，不复用 live broker 链 |
| Qbot | MIT | 未安装、未复制页面或自动交易代码 | 仅产品工作流参考 |

## 官方证据

- [vectorbt 官方仓库](https://github.com/polakowo/vectorbt)说明其为 Apache-2.0 with Commons Clause。
- [vn.py 官方仓库](https://github.com/vnpy/vnpy)标明 MIT。
- [OpenBB 官方仓库](https://github.com/OpenBB-finance/OpenBB)标明 AGPLv3，平台包元数据使用 AGPL-3.0-only。
- [FinRL 官方仓库](https://github.com/AI4Finance-Foundation/FinRL)当前标明 MIT 并附商标声明。
- [FinRL-X / Trading 官方仓库](https://github.com/AI4Finance-Foundation/FinRL-Trading)标明 Apache-2.0。
- [Qbot 官方仓库](https://github.com/UFund-Me/Qbot)标明 MIT。

## 环境边界

- `hermes-core`：核心 API、领域、ML 治理和 Event Truth；精确锁定于 `requirements/core.lock`。
- `hermes-research-vectorbt`：只读不可变快照，无网络下载、Broker 或订单输出。
- `hermes-execution-vnpy`：未安装，未来只能存在于 Execution Service/Event Validation。
- `hermes-openbb-sidecar`：未安装，未来只能以独立进程提供非 A 股主源数据。
- `hermes-finrl-lab`：未安装，未来只能离线研究并接受泄漏、成本和 walk-forward 对照。

批准状态与锁文件哈希由 `approved_dependencies.yaml` 固定；CI 对锁文件变更、未精确 pin、危险许可证状态和跨边界导入执行阻断。
