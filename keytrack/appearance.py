"""Candidate-window palettes shared by native previews and Rime configuration."""
from __future__ import annotations

from copy import deepcopy


def _palette(back: str, text: str, candidate: str, comment: str, label: str,
             accent: str, selected: str, border: str) -> dict[str, str]:
    return {
        "back_color": back,
        "text_color": text,
        "candidate_text_color": candidate,
        "comment_text_color": comment,
        "label_color": label,
        "hilited_candidate_back_color": accent,
        "hilited_candidate_text_color": selected,
        "hilited_comment_text_color": selected,
        "hilited_label_color": selected,
        "border_color": border,
    }


def _original(accent: str, dark: bool) -> dict[str, str]:
    # Keep every color in the three previously shipped themes unchanged.
    return _palette(
        "#19232b" if dark else "#f9fbfa",
        "#dce6e5" if dark else "#334155",
        "#f1f5f9" if dark else "#172d2b",
        "#a5b5b8" if dark else "#667b7b",
        "#9badb3" if dark else "#728785",
        accent,
        "#102a2a" if dark else "#ffffff",
        "#334348" if dark else "#dce8e5",
    )


THEMES = {
    "green": {
        "name": "青绿", "description": "清爽青绿，熟悉的原有配色。",
        "light": _original("#0f766e", False), "dark": _original("#14b8a6", True),
    },
    "blue": {
        "name": "海蓝", "description": "明亮海蓝，让选中项更醒目。",
        "light": _original("#2563eb", False), "dark": _original("#60a5fa", True),
    },
    "slate": {
        "name": "石墨", "description": "沉稳灰蓝，适合简洁桌面。",
        "light": _original("#475569", False), "dark": _original("#94a3b8", True),
    },
    "forest": {
        "name": "松林", "description": "浅绿底色，配深松绿选中项。",
        "light": _palette("#f2f7f1", "#244332", "#183526", "#536b5a", "#566b5b",
                          "#2f6241", "#ffffff", "#cfddce"),
        "dark": _palette("#17251c", "#dceadb", "#edf5ea", "#aabead", "#a9bdac",
                         "#94bc8b", "#132718", "#354c39"),
    },
    "mint": {
        "name": "薄荷", "description": "轻盈薄荷绿，带一点清凉感。",
        "light": _palette("#effaf7", "#244b43", "#173d35", "#506f64", "#557064",
                          "#187a60", "#ffffff", "#c8e2d8"),
        "dark": _palette("#122923", "#d9eee5", "#eaf8f1", "#a1bdb2", "#a3beb3",
                         "#82d9b8", "#10352a", "#315247"),
    },
    "mist": {
        "name": "雾蓝", "description": "柔和灰蓝，安静又清楚。",
        "light": _palette("#f0f6fa", "#30465a", "#203e55", "#566f83", "#576f80",
                          "#427193", "#ffffff", "#cfdee8"),
        "dark": _palette("#1b2934", "#ddeaf3", "#edf4f9", "#a7becf", "#a7bdcc",
                         "#a0c3db", "#183344", "#3d5364"),
    },
    "navy": {
        "name": "深海", "description": "偏冷的深蓝，选中项轮廓鲜明。",
        "light": _palette("#eff3fa", "#263d61", "#1f3354", "#566987", "#536584",
                          "#234a7c", "#ffffff", "#ced9e9"),
        "dark": _palette("#141f32", "#dbe6f5", "#edf2fa", "#a6b9d3", "#a6b9d3",
                         "#88acd8", "#112c4d", "#354660"),
    },
    "sand": {
        "name": "暖砂", "description": "温暖米色，配低调的砂棕色。",
        "light": _palette("#fbf6ed", "#514432", "#463822", "#7c6a51", "#7c6a51",
                          "#896431", "#ffffff", "#e4d7c2"),
        "dark": _palette("#2b251d", "#eee3d2", "#f8f0e2", "#c3b299", "#c3b299",
                         "#d9b77c", "#382b13", "#514535"),
    },
    "paper": {
        "name": "纸白", "description": "接近纸张的暖白，简洁耐看。",
        "light": _palette("#faf9f6", "#414440", "#30332f", "#6c7069", "#6c7069",
                          "#4d6254", "#ffffff", "#dddfd6"),
        "dark": _palette("#242622", "#e2e4dc", "#f0f1e9", "#b4b9ae", "#b4b9ae",
                         "#c2c9b8", "#252e21", "#45493f"),
    },
}


def catalog() -> list[dict]:
    """Return RGB values with no mutable references to the rendering source."""
    return [{"id": identifier, **deepcopy(theme)} for identifier, theme in THEMES.items()]
