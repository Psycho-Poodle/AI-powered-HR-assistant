"""Stable semantic identities for persisted read results."""

import hashlib
import json


def operation_key(step) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "tool": step.tool,
                "args": step.args.model_dump(mode="json"),
                "revision": step.revision,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
