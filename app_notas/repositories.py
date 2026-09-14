from __future__ import annotations

import json
import sqlite3
from typing import Any


class MasterDataRepository:
    """Acesso aos cadastros mestre locais consumidos pelo App Notas."""

    FARM_SYNC_COLUMNS = (
        "nome",
        "id_mestre",
        "codigo_mestre",
        "fonte_mestre",
        "sincronizado_em",
    )
    FIELD_SYNC_COLUMNS = (
        "id",
        "fazenda_id_mestre",
        "fazenda_codigo",
        "fazenda_codigo_mestre",
        "fazenda_nome",
        "codigo",
        "nome",
        "area_ha",
        "area_alq",
        "area_plantada_ha",
        "safra",
        "tipo_area",
        "ativo",
        "fonte",
        "sincronizado_em",
    )
    METADATA_COLUMNS = {"sincronizado_em"}

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def find_local_farm_code(self, candidate_codes: list[str]) -> str | None:
        for code in candidate_codes:
            row = self.conn.execute(
                "SELECT codigo FROM fazendas WHERE codigo = ?",
                (code,),
            ).fetchone()
            if row:
                return str(row["codigo"])
        return None

    def upsert_farm(self, local_code: str, values: dict[str, Any]) -> bool:
        current = self.conn.execute(
            """
            SELECT nome, id_mestre, codigo_mestre, fonte_mestre, sincronizado_em
            FROM fazendas
            WHERE codigo = ?
            """,
            (local_code,),
        ).fetchone()

        if not self._farm_needs_update(current, values):
            return False

        payload = tuple(values[column] for column in self.FARM_SYNC_COLUMNS)
        if current is None:
            self.conn.execute(
                """
                INSERT INTO fazendas (
                    codigo, nome, id_mestre, codigo_mestre,
                    fonte_mestre, sincronizado_em
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (local_code, *payload),
            )
        else:
            self.conn.execute(
                """
                UPDATE fazendas
                SET nome = ?,
                    id_mestre = ?,
                    codigo_mestre = ?,
                    fonte_mestre = ?,
                    sincronizado_em = ?
                WHERE codigo = ?
                """,
                (*payload, local_code),
            )
        return True

    def retire_stale_farms(
        self,
        *,
        source: str,
        active_codes: set[str],
        synced_at: str,
    ) -> int:
        if not active_codes:
            raise ValueError("Sincronizacao recusada: conjunto de fazendas ativas esta vazio")
        rows = self.conn.execute(
            "SELECT codigo FROM fazendas WHERE fonte_mestre = ?",
            (source,),
        ).fetchall()
        stale_codes = [str(row["codigo"]) for row in rows if str(row["codigo"]) not in active_codes]
        for code in stale_codes:
            self.conn.execute(
                """
                UPDATE fazendas
                SET fonte_mestre = ?, sincronizado_em = ?
                WHERE codigo = ? AND fonte_mestre = ?
                """,
                (f"historico_{source}", synced_at, code, source),
            )
        return len(stale_codes)

    def replace_fields(
        self,
        *,
        source: str,
        fields: list[dict[str, Any]],
        farm_id_to_local_code: dict[str, str],
        synced_at: str,
    ) -> dict[str, int]:
        processed = 0
        inserted = 0
        updated = 0
        removed = 0
        skipped = 0
        desired: list[tuple[tuple[str, str, str], dict[str, Any]]] = []
        desired_by_id: dict[str, dict[str, Any]] = {}

        for field in fields:
            local_farm_code = farm_id_to_local_code.get(str(field["farm_id"]))
            if not local_farm_code:
                skipped += 1
                continue

            values = {
                "id": str(field["id"]),
                "fazenda_id_mestre": str(field["farm_id"]),
                "fazenda_codigo": local_farm_code,
                "fazenda_codigo_mestre": str(field["farm_code"]).strip(),
                "fazenda_nome": str(field["farm_name"]).strip(),
                "codigo": str(field["code"]).strip(),
                "nome": field["name"],
                "area_ha": field["area_ha"],
                "area_alq": field["area_alq"],
                "area_plantada_ha": field["planted_area_ha"],
                "safra": field["crop_year"],
                "tipo_area": field["area_type"],
                "ativo": int(field["active"]),
                "fonte": source,
                "sincronizado_em": synced_at,
            }
            key = (values["fazenda_codigo"], values["codigo"], source)
            if values["id"] in desired_by_id:
                raise ValueError(f"Talhao mestre duplicado por id: {values['id']}")
            desired_by_id[values["id"]] = values
            desired.append((key, values))

        desired_keys = {key for key, _values in desired}
        if len(desired_keys) != len(desired):
            raise ValueError("Talhoes mestres duplicados por fazenda, codigo e fonte")
        current_rows = self.conn.execute(
            """
            SELECT *
            FROM talhoes
            WHERE fonte = ?
            """,
            (source,),
        ).fetchall()
        current_by_id = {str(row["id"]): row for row in current_rows}

        for row in current_rows:
            if str(row["id"]) not in desired_by_id:
                self.conn.execute("DELETE FROM talhoes WHERE id = ?", (row["id"],))
                removed += 1

        # O id da Balanca e a identidade canonica. Antes de aplicar mudancas de
        # codigo, move temporariamente as chaves naturais que mudaram para evitar
        # colisao durante trocas/reordenacoes (por exemplo, 124 -> 101 enquanto
        # outro talhao passa a ocupar 124).
        for field_id, current in current_by_id.items():
            values = desired_by_id.get(field_id)
            if values is None:
                continue
            current_key = (
                str(current["fazenda_codigo"]),
                str(current["codigo"]),
                str(current["fonte"]),
            )
            desired_key = (values["fazenda_codigo"], values["codigo"], source)
            if current_key != desired_key:
                self.conn.execute(
                    "UPDATE talhoes SET codigo = ? WHERE id = ?",
                    (f"__balanca_sync__{field_id}", field_id),
                )

        for _key, values in desired:
            processed += 1
            current = current_by_id.get(values["id"])

            payload = tuple(values[column] for column in self.FIELD_SYNC_COLUMNS)
            if current is None:
                collision = self.conn.execute(
                    "SELECT fonte FROM talhoes WHERE id = ?",
                    (values["id"],),
                ).fetchone()
                if collision is not None:
                    raise ValueError(
                        f"Id mestre de talhao colide com registro de outra fonte: {values['id']}"
                    )
                self.conn.execute(
                    """
                    INSERT INTO talhoes (
                        id, fazenda_id_mestre, fazenda_codigo, fazenda_codigo_mestre,
                        fazenda_nome, codigo, nome, area_ha, area_alq, area_plantada_ha,
                        safra, tipo_area, ativo, fonte, sincronizado_em
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                inserted += 1
                continue

            if not self._field_needs_update(current, values):
                continue

            self.conn.execute(
                """
                UPDATE talhoes
                SET fazenda_id_mestre = ?,
                    fazenda_codigo = ?,
                    fazenda_codigo_mestre = ?,
                    fazenda_nome = ?,
                    codigo = ?,
                    nome = ?,
                    area_ha = ?,
                    area_alq = ?,
                    area_plantada_ha = ?,
                    safra = ?,
                    tipo_area = ?,
                    ativo = ?,
                    fonte = ?,
                    sincronizado_em = ?
                WHERE id = ?
                """,
                (*payload[1:], values["id"]),
            )
            updated += 1

        return {
            "processed": processed,
            "changed": inserted + updated + removed,
            "inserted": inserted,
            "updated": updated,
            "removed": removed,
            "skipped": skipped,
        }

    def record_sync_status(
        self,
        *,
        source: str,
        synced_at: str,
        farms_read: int,
        farms_changed: int,
        fields_read: int,
        fields_changed: int,
        origin: str,
        details: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO sincronizacoes_cadastros (
                fonte, sincronizado_em, fazendas_lidas, fazendas_alteradas,
                talhoes_lidos, talhoes_alterados, origem, detalhes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fonte) DO UPDATE SET
                sincronizado_em = excluded.sincronizado_em,
                fazendas_lidas = excluded.fazendas_lidas,
                fazendas_alteradas = excluded.fazendas_alteradas,
                talhoes_lidos = excluded.talhoes_lidos,
                talhoes_alterados = excluded.talhoes_alterados,
                origem = excluded.origem,
                detalhes = excluded.detalhes
            """,
            (
                source,
                synced_at,
                farms_read,
                farms_changed,
                fields_read,
                fields_changed,
                origin,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
            ),
        )

    def _farm_needs_update(self, row: sqlite3.Row | None, values: dict[str, Any]) -> bool:
        if row is None:
            return True
        for key, value in values.items():
            if key in self.METADATA_COLUMNS:
                continue
            if row[key] != value:
                return True
        return False

    def _field_needs_update(self, row: sqlite3.Row | None, values: dict[str, Any]) -> bool:
        if row is None:
            return True
        for key, value in values.items():
            if key in self.METADATA_COLUMNS:
                continue
            if row[key] != value:
                return True
        return False
