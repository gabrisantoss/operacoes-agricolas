from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_SYSTEM_FIELDS = {
    "id",
    "name",
    "public_path",
    "internal_host",
    "internal_port",
    "stack",
    "enabled",
    "requires_auth",
}


class SystemRegistryError(ValueError):
    pass


def normalize_public_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise SystemRegistryError("public_path vazio.")
    return text if text.startswith("/") else f"/{text}"


def load_systems(config_path: Path) -> list[dict]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemRegistryError(f"Cadastro de sistemas nao encontrado: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemRegistryError(f"Cadastro de sistemas invalido: {exc}") from exc

    if not isinstance(raw, list):
        raise SystemRegistryError("systems.json deve conter uma lista de sistemas.")

    systems: list[dict] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemRegistryError(f"Sistema na posicao {index} nao e um objeto.")
        missing = sorted(REQUIRED_SYSTEM_FIELDS - set(item))
        if missing:
            raise SystemRegistryError(f"Sistema {item.get('id', index)} sem campos: {', '.join(missing)}")

        system = dict(item)
        system["id"] = str(system["id"]).strip()
        system["name"] = str(system["name"]).strip()
        system["public_path"] = normalize_public_path(system["public_path"])
        if "api_path" in system and system["api_path"]:
            system["api_path"] = normalize_public_path(system["api_path"])

        if not system["id"] or not system["name"]:
            raise SystemRegistryError(f"Sistema na posicao {index} tem id/name vazio.")
        if system["id"] in seen_ids:
            raise SystemRegistryError(f"ID de sistema duplicado: {system['id']}")
        if system["public_path"] != "/" and system["public_path"] in seen_paths:
            raise SystemRegistryError(f"Rota publica duplicada: {system['public_path']}")

        seen_ids.add(system["id"])
        seen_paths.add(system["public_path"])
        systems.append(system)

    return systems


def systems_by_id(systems: list[dict]) -> dict[str, dict]:
    return {system["id"]: system for system in systems}


def enabled_systems(systems: list[dict]) -> list[dict]:
    return [system for system in systems if bool(system.get("enabled", True))]
