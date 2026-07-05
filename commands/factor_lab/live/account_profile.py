"""V1.9 账户配置 — 三流信号 + 执行路径分层"""
import json
from pathlib import Path

ACCOUNT_PROFILE = {
    "capital": 50000,
    "self_account": {
        "allow_main_board": True,
        "allow_chinext": False,
        "allow_star_market": False,
        "allow_beijing": False,
    },
    "research_scope": {
        "include_main_board": True,
        "include_chinext": True,
        "include_star_market": True,
        "include_beijing": False,
    },
    "alternative_execution": {
        "enable_etf_substitution": True,
        "enable_manual_review_bucket": True,
        "allow_borrowed_account_execution": False,
    },
}


def get_board(symbol: str) -> str:
    if symbol.startswith(("300", "301")): return "chinext"
    if symbol.startswith(("688", "689")): return "star"
    if symbol.startswith(("8", "4")): return "beijing"
    return "main"


def is_self_tradable(symbol: str) -> bool:
    board = get_board(symbol)
    cfg = ACCOUNT_PROFILE["self_account"]
    return {
        "main": cfg["allow_main_board"],
        "chinext": cfg["allow_chinext"],
        "star": cfg["allow_star_market"],
        "beijing": cfg["allow_beijing"],
    }.get(board, False)


def is_in_research_scope(board: str) -> bool:
    cfg = ACCOUNT_PROFILE["research_scope"]
    return {
        "main": cfg["include_main_board"],
        "chinext": cfg["include_chinext"],
        "star": cfg["include_star_market"],
        "beijing": cfg["include_beijing"],
    }.get(board, True)
