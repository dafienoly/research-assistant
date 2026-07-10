# VNext 示例产物

本目录只保存“接口形状与 fail-visible 行为”示例，不会被生产代码读取，也不包含伪造市场数值。

- `missing_component.json`：真实输入或运行产物不存在时的标准响应。
- `paper_shadow_order_contract.json`：Paper/Shadow 订单文件的结构示例；所有字段显式标记为文档示例，不能当作交易输入。
- `real_run_manifest_2026-07-10.json`：指向真实 Tushare/本地数据运行产物的可审计清单；弱 OOS 模型和缺失旧 TopN 都保持 PARTIAL/WATCH。

真实每日产物由 CLI 写入 `data/vnext/`，并带数据源、更新时间、证据、缺失证据和状态。不要把本目录复制到 `data/vnext/`。
