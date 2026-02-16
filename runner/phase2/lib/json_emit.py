from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


def _order_by_schema(obj: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ordered: "OrderedDict[str, Any]" = OrderedDict()
    props = schema.get("properties", {})

    for key in props.keys():
        if key in obj:
            value = obj[key]
            prop_schema = props[key]
            if isinstance(value, dict) and isinstance(prop_schema, dict) and "properties" in prop_schema:
                ordered[key] = _order_by_schema(value, prop_schema)
            elif isinstance(value, list) and isinstance(prop_schema, dict) and "items" in prop_schema:
                item_schema = prop_schema["items"]
                ordered[key] = [
                    _order_by_schema(item, item_schema) if isinstance(item, dict) and isinstance(item_schema, dict) else item
                    for item in value
                ]
            else:
                ordered[key] = value

    # Preserve any remaining keys deterministically (rare, mostly for nested defs not used in result body).
    for key in obj.keys():
        if key not in ordered:
            ordered[key] = obj[key]

    return dict(ordered)


def write_json(path: Path, obj: dict[str, Any], schema: dict[str, Any]) -> None:
    ordered_obj = _order_by_schema(obj, schema)
    with path.open("w", encoding="utf-8") as f:
        json.dump(ordered_obj, f, indent=2)
        f.write("\n")
