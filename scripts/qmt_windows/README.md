# QMT 桥接 Windows 脚本

这些脚本运行在 Windows 上，与 QMT 客户端和 Python `xtquant` 环境配合使用。

## 首次安装

双击运行：

```text
setup_qmt_bridge.cmd
```

然后编辑：

```text
qmt_bridge.env
```

至少设置以下项：

```text
QMT_USERDATA_PATH=D:\YourBrokerQMT\userdata
QMT_ACCOUNT_ID=your_account_id
```

大 QMT / 投研端通常使用安装目录下的 `userdata`；miniQMT / 极简模式使用 `userdata_mini`。

在准备好真实交易前，请保持此项禁用：

```text
QMT_LIVE_TRADING_ENABLED=0
```

## 启动 / 停止

```text
start_qmt_bridge.cmd
status_qmt_bridge.cmd
stop_qmt_bridge.cmd
restart_qmt_bridge.cmd
diagnose_qmt_bridge.cmd
```

如果 `status` 里出现 `No module named 'xtquant'`，请在同一个 Python 环境安装依赖：

```text
install_qmt_dependencies.cmd
```

`xtquant` 不支持 Python 3.14；脚本会优先自动选择本机 Python 3.13/3.12/3.11，并更新 `qmt_bridge.env` 里的 `QMT_PYTHON_PATH`。

如果 `status` 里出现：

```text
无法连接xtquant服务，请检查QMT-投研版或QMT-极简版是否开启
```

说明 bridge 已启动且 `xtquant` 已安装，但 QMT 数据服务未连接。

如果你使用的是大 QMT / 投研端，请先执行：

```text
use_big_qmt.cmd
```

它会把 `QMT_USERDATA_PATH` 从 `userdata_mini` 切到同目录下的 `userdata`。然后确认 QMT 内的投研/量化/Python 数据服务已开启，再执行：

```text
restart_qmt_bridge.cmd
status_qmt_bridge.cmd
diagnose_qmt_bridge.cmd
```

桥接服务监听端口：

```text
http://127.0.0.1:8765
```

Hermes/WSL 侧应设置：

```bash
export QMT_BRIDGE_BASE_URL=http://127.0.0.1:8765
```

## 日志

运行时文件写入：

```text
runtime\qmt_bridge.pid
runtime\qmt_bridge.out.log
runtime\qmt_bridge.err.log
runtime\qmt_bridge_audit.jsonl
```

## 一键配置安装

在 PowerShell 中：

```powershell
.\qmt_bridge_control.ps1 -Action setup `
  -UserdataPath "D:\YourBrokerQMT\userdata" `
  -AccountId "your_account_id"
```

要在环境文件中显式启用实时交易：

```powershell
.\qmt_bridge_control.ps1 -Action setup `
  -UserdataPath "D:\YourBrokerQMT\userdata" `
  -AccountId "your_account_id" `
  -EnableLiveTrading
```
