"""字体配置模块 — 统一管理 matplotlib 中文字体"""
import matplotlib as mpl
from matplotlib import font_manager as fm
from pathlib import Path
import warnings


CANDIDATE_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def setup_chinese_matplotlib_font():
    """在任何 matplotlib 绘图前调用，设置中文字体"""
    found = None
    for font_path in CANDIDATE_FONTS:
        p = Path(font_path)
        if p.exists():
            try:
                fm.fontManager.addfont(str(p))
                font_name = fm.FontProperties(fname=str(p)).get_name()
                found = font_name
                break
            except Exception:
                continue
    
    if found is None:
        # 回退到系统字体搜索
        try:
            import subprocess
            result = subprocess.run(["fc-list", ":lang=zh", "-f", "%{file}\n"],
                                    capture_output=True, text=True, timeout=5)
            fonts = [l.strip() for l in result.stdout.split("\n") if l.strip()]
            for f in fonts:
                p = Path(f)
                if p.exists() and p.suffix in (".ttf", ".ttc", ".otf"):
                    try:
                        fm.fontManager.addfont(str(p))
                        font_name = fm.FontProperties(fname=str(p)).get_name()
                        found = font_name
                        break
                    except Exception:
                        continue
        except Exception:
            pass
    
    if found:
        mpl.rcParams["font.family"] = "sans-serif"
        mpl.rcParams["font.sans-serif"] = [
            found, "Noto Sans CJK SC", "Microsoft YaHei",
            "SimHei", "WenQuanYi Zen Hei", "DejaVu Sans",
        ]
        mpl.rcParams["axes.unicode_minus"] = False
        mpl.rcParams["svg.fonttype"] = "path"  # SVG 转路径避免字体依赖
        mpl.rcParams["pdf.fonttype"] = 42
        mpl.rcParams["ps.fonttype"] = 42
        return found
    
    raise RuntimeError(
        "No Chinese font found. Install with: sudo apt install fonts-noto-cjk fonts-wqy-zenhei"
    )