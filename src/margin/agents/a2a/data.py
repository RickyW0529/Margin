"""Structured-data helpers for the A2A 1.0 ``Part.data`` variant."""

from __future__ import annotations

import json
from typing import Any, TypeAlias

from a2a.helpers import get_data_parts, new_data_artifact, new_data_part
from a2a.types import Artifact, Message, Part

JSON_MEDIA_TYPE = "application/json"
LOSSLESS_JSON_EXTENSION_URI = "urn:margin:a2a:extension:lossless-json-v1"
_LOSSLESS_ENCODING = "margin-json-v1"
_ENCODING_KEY = "_margin_a2a_encoding"
_PAYLOAD_KEY = "payload_json"

# A2A 1.0 represents every content variant with Part. This alias names the
# data-bearing variant without introducing a second wire model.
DataPart: TypeAlias = Part


def make_data_part(payload: Any) -> DataPart:
    """Build an official A2A ``Part`` containing JSON-serializable data."""
    return new_data_part(_encode_payload(payload), media_type=JSON_MEDIA_TYPE)


def make_data_artifact(*, name: str, payload: Any) -> Artifact:
    """Build an A2A artifact without losing integer JSON values in protobuf Struct."""
    return new_data_artifact(
        name=name,
        data=_encode_payload(payload),
        media_type=JSON_MEDIA_TYPE,
    )


def read_data_part(part: Part) -> Any:
    """Decode one data-bearing A2A part into its Python representation."""
    if not part.HasField("data"):
        raise ValueError("A2A part does not contain structured data")
    return _decode_payload(get_data_parts([part])[0])


def read_message_data(message: Message) -> tuple[Any, ...]:
    """Decode all structured data parts from an A2A message."""
    return tuple(_decode_payload(payload) for payload in get_data_parts(message.parts))


def encode_data_payload(payload: Any) -> dict[str, str]:
    """Encode application JSON losslessly inside an official A2A DataPart map."""
    return _encode_payload(payload)


def _encode_payload(payload: Any) -> dict[str, str]:
    return {
        _ENCODING_KEY: _LOSSLESS_ENCODING,
        _PAYLOAD_KEY: json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ),
    }


def _decode_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if payload.get(_ENCODING_KEY) != _LOSSLESS_ENCODING:
        return payload
    encoded = payload.get(_PAYLOAD_KEY)
    if not isinstance(encoded, str):
        raise ValueError("invalid Margin A2A JSON envelope")
    return json.loads(encoded)
