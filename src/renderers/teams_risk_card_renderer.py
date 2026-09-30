"""Render flexible risk documents as Microsoft Teams Adaptive Cards."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)


class TeamsRiskCardRenderer:
    """Render notification view blocks without hardcoding business fields."""

    _SEVERITY_COLORS = {
        "critical": "Attention",
        "high": "Attention",
        "medium": "Warning",
        "low": "Good",
    }

    def render_notification(self, risk: Mapping[str, Any]) -> dict[str, Any]:
        """Render the notification view from the supplied risk mapping."""
        content = self._new_content()
        body: list[dict[str, Any]] = content["body"]

        severity = self._display(risk.get("severity_label")) or self._display(risk.get("severity"))
        if severity:
            body.append({
                "type": "TextBlock",
                "text": severity.upper(),
                "weight": "Bolder",
                "color": self._severity_color(severity),
                "wrap": True,
            })
        self._append_text(body, risk.get("title"), weight="Bolder", size="Medium")
        self._append_text(body, risk.get("subtitle"), is_subtitle=True)
        self._append_text(body, risk.get("summary"), wrap=True)

        views = self._mapping(risk.get("views"))
        notification = self._mapping(views.get("notification"))
        risk_id = self._display(risk.get("risk_id")) or ""
        self._render_blocks(body, notification, risk_id)
        self._append_view_actions(content, views, risk_id)

        return self._card(content)

    def render_view(self, risk: Mapping[str, Any], view_name: str) -> dict[str, Any]:
        """Render one server-selected risk view using the same generic blocks."""
        content = self._new_content()
        body: list[dict[str, Any]] = content["body"]
        views = self._mapping(risk.get("views"))
        view = self._mapping(views.get(view_name))
        self._append_text(body, view.get("title"), weight="Bolder", size="Medium")
        self._append_text(body, view.get("subtitle"), is_subtitle=True)
        self._render_blocks(body, view, self._display(risk.get("risk_id")) or "")
        return self._card(content)

    def _render_blocks(
        self,
        body: list[dict[str, Any]],
        view: Mapping[str, Any],
        risk_id: str,
    ) -> None:
        blocks = view.get("blocks")
        if not isinstance(blocks, list):
            return
        for index, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                self._warn_unknown_block(risk_id, block, index)
                continue
            self._render_block(body, block, risk_id, index)

    @staticmethod
    def _new_content() -> dict[str, Any]:
        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [],
        }

    @staticmethod
    def _card(content: dict[str, Any]) -> dict[str, Any]:
        return {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": content,
        }

    def _append_view_actions(
        self,
        content: dict[str, Any],
        views: Mapping[str, Any],
        risk_id: str,
    ) -> None:
        if not risk_id:
            return
        actions = []
        for view_name, fallback_label in (
            ("details", "View Details"),
            ("mitigation", "Mitigation Plan"),
        ):
            view = views.get(view_name)
            if not isinstance(view, Mapping):
                continue
            label = self._display(view.get("action_label")) or fallback_label
            actions.append({
                "type": "Action.Execute",
                "title": label,
                "verb": "show_risk_view",
                "data": {
                    "action": "show_risk_view",
                    "risk_id": risk_id,
                    "view": view_name,
                },
            })
        if actions:
            content["actions"] = actions

    def _render_block(
        self,
        body: list[dict[str, Any]],
        block: Mapping[str, Any],
        risk_id: str,
        index: int,
    ) -> None:
        block_type = self._display(block.get("type"))
        if block_type == "key_value":
            self._render_key_value(body, block)
        elif block_type == "metrics":
            self._render_metrics(body, block)
        elif block_type == "text":
            self._render_text(body, block)
        elif block_type == "table":
            self._render_table(body, block)
        elif block_type == "action_list":
            self._render_action_list(body, block)
        else:
            self._warn_unknown_block(risk_id, block_type, index)

    def _render_key_value(self, body: list[dict[str, Any]], block: Mapping[str, Any]) -> None:
        self._append_text(body, block.get("title"), weight="Bolder")
        facts: list[dict[str, str]] = []
        items = block.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                label = self._display(item.get("label"))
                value = self._display(item.get("value"))
                if value is not None:
                    facts.append({"title": label or "", "value": value})
        if facts:
            body.append({"type": "FactSet", "facts": facts})

    def _render_metrics(self, body: list[dict[str, Any]], block: Mapping[str, Any]) -> None:
        self._append_text(body, block.get("title"), weight="Bolder")
        items = block.get("items")
        if not isinstance(items, list):
            return
        columns = [
            (key, label)
            for key, label in self._column_specs(block.get("columns"))
            if key.strip().lower() != "status" and label.strip().lower() != "status"
        ]
        if columns:
            body.append(self._column_set([label for _, label in columns], weight="Bolder"))
            for item in items:
                if isinstance(item, Mapping):
                    body.append(self._column_set([
                        self._display(item.get(key)) or "" for key, _ in columns
                    ]))
            return
        for item in items:
            if not isinstance(item, Mapping):
                continue
            values = []
            for key in ("label", "value"):
                value = self._display(item.get(key))
                if value is not None:
                    values.append(value)
            if values:
                body.append(self._column_set(values))

    def _render_text(self, body: list[dict[str, Any]], block: Mapping[str, Any]) -> None:
        self._append_text(body, block.get("title"), weight="Bolder")
        text = self._display(block.get("text"))
        if text is not None:
            item: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
            if block.get("bold") is True:
                item["weight"] = "Bolder"
            if self._display(block.get("status")):
                item["color"] = self._status_color(block.get("status"))
            body.append(item)

    def _render_table(self, body: list[dict[str, Any]], block: Mapping[str, Any]) -> None:
        self._append_text(body, block.get("title"), weight="Bolder")
        columns = self._column_specs(block.get("columns"))
        rows = block.get("rows")
        if not columns or not isinstance(rows, list):
            return
        body.append(self._column_set([label for _, label in columns], weight="Bolder"))
        for row in rows:
            if isinstance(row, Mapping):
                body.append(self._column_set([
                    self._display(row.get(key)) or "" for key, _ in columns
                ]))

    def _render_action_list(self, body: list[dict[str, Any]], block: Mapping[str, Any]) -> None:
        self._append_text(body, block.get("title"), weight="Bolder")
        items = block.get("items")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, Mapping):
                continue
            title = self._display(item.get("title"))
            if title is None:
                continue
            order = self._display(item.get("order"))
            text = f"{order}. {title}" if order is not None else title
            body.append({"type": "TextBlock", "text": text, "wrap": True})

    @staticmethod
    def _column_specs(columns: Any) -> list[tuple[str, str]]:
        if not isinstance(columns, list):
            return []
        result = []
        for column in columns:
            if isinstance(column, Mapping):
                key = TeamsRiskCardRenderer._display(column.get("key"))
                label = TeamsRiskCardRenderer._display(column.get("label"))
                if key:
                    result.append((key, label or key))
            elif isinstance(column, str) and column.strip():
                result.append((column.strip(), column.strip()))
        return result

    @staticmethod
    def _column_set(values: list[str], *, weight: str | None = None) -> dict[str, Any]:
        columns = []
        for value in values:
            text_block: dict[str, Any] = {"type": "TextBlock", "text": value, "wrap": True}
            if weight:
                text_block["weight"] = weight
            columns.append({"type": "Column", "width": "stretch", "items": [text_block]})
        return {"type": "ColumnSet", "columns": columns}

    @staticmethod
    def _append_text(
        body: list[dict[str, Any]],
        value: Any,
        *,
        weight: str | None = None,
        size: str | None = None,
        wrap: bool = True,
        is_subtitle: bool = False,
    ) -> None:
        text = TeamsRiskCardRenderer._display(value)
        if text is None:
            return
        item: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": wrap}
        if weight:
            item["weight"] = weight
        if size:
            item["size"] = size
        if is_subtitle:
            item["isSubtle"] = True
        body.append(item)

    @classmethod
    def _severity_color(cls, value: str) -> str:
        return cls._SEVERITY_COLORS.get(value.strip().lower(), "Default")

    @classmethod
    def _status_color(cls, value: Any) -> str:
        return cls._SEVERITY_COLORS.get(str(value).strip().lower(), "Default")

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _display(value: Any) -> str | None:
        if value is None or isinstance(value, (Mapping, list, tuple, set)):
            return None
        if isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
            return text or None
        return None

    @staticmethod
    def _warn_unknown_block(risk_id: str, block_type: Any, block_index: int) -> None:
        logger.warning(
            "unsupported_risk_card_block",
            extra={
                "risk_id": risk_id,
                "block_type": TeamsRiskCardRenderer._display(block_type) or "unknown",
                "block_index": block_index,
            },
        )
