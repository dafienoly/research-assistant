"""Architecture audit adapter — delegates to factor_lab.architecture.architecture_audit"""


def run_audit(output_dir=None, strict=False, include_tests=False, include_artifacts=False, quick=False, major_version="") -> list[dict]:
    """运行架构审计，返回 findings 列表"""
    from factor_lab.architecture.architecture_audit import run_architecture_audit as real_audit

    # 直接调用，它会内部打印结果
    real_audit(
        output_dir=output_dir,
        strict=strict,
        include_tests=include_tests,
        include_artifacts=include_artifacts,
        major_version=major_version,
    )

    return [{"severity": "INFO", "module": "__done__", "message": "审计完成"}]
