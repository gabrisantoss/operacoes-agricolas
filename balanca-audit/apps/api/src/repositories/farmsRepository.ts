import { randomUUID } from "node:crypto";
import { formatFarmCode, normalizeFarmText } from "@balanca/shared";
import type { CreateFarmInput, UpdateFarmInput, UpdateFieldInput } from "@balanca/shared";
import type { FarmRecord, FieldRecord } from "../db.js";

type Statement = {
  all(...params: unknown[]): unknown[];
  get(...params: unknown[]): unknown;
  run(...params: unknown[]): unknown;
  runMany(paramsList: any[]): unknown;
};

type DatabaseAdapter = {
  prepare(sql: string): Statement;
  transaction<T>(fn: () => T): () => T;
};

type FarmRow = {
  id: string;
  code: string | null;
  name: string;
  property_number: string | null;
  sequence_number: string | null;
  area_ha: number | null;
  area_alq: number | null;
  street: string | null;
  city: string | null;
  postal_code: string | null;
  section_name: string | null;
  owner_name: string | null;
  municipality: string | null;
  crop_year: string | null;
  total_area_alq: number | null;
  total_area_ha: number | null;
  metadata_updated_at: string | null;
};

type FieldRow = {
  id: string;
  code: string;
  name: string | null;
  area_ha: number | null;
  area_alq: number | null;
  planted_area_ha: number | null;
  crop_year: string | null;
  area_type: string | null;
  active: number;
  farm_id: string;
};

export class FarmsRepository {
  constructor(private readonly db: DatabaseAdapter) {}

  listFarms(): FarmRecord[] {
    const farms = this.db
      .prepare(
        `
        SELECT
          id,
          code,
          name,
          property_number,
          sequence_number,
          area_ha,
          area_alq,
          street,
          city,
          postal_code,
          section_name,
          owner_name,
          municipality,
          crop_year,
          total_area_alq,
          total_area_ha,
          metadata_updated_at
        FROM farms
        ORDER BY code ASC, name ASC
        `
      )
      .all() as FarmRow[];
    const fields = this.db
      .prepare(
        `
        SELECT id, code, name, area_ha, area_alq, planted_area_ha, crop_year, area_type, active, farm_id
        FROM fields
        ORDER BY code ASC
        `
      )
      .all() as FieldRow[];
    const fieldsByFarmId = new Map<string, FieldRecord[]>();

    for (const field of fields) {
      const mappedField = mapField(field);
      const farmFields = fieldsByFarmId.get(field.farm_id);

      if (farmFields) {
        farmFields.push(mappedField);
      } else {
        fieldsByFarmId.set(field.farm_id, [mappedField]);
      }
    }

    for (const farmFields of fieldsByFarmId.values()) {
      farmFields.sort((left, right) => compareFieldCodes(left.code, right.code));
    }

    return farms.map((farm) => {
      const farmFields = fieldsByFarmId.get(farm.id) ?? [];

      return {
        id: farm.id,
        code: formatFarmCode(farm.code) || farm.code,
        name: farm.name,
        propertyNumber: farm.property_number,
        sequenceNumber: farm.sequence_number,
        areaHa: farm.area_ha,
        areaAlq: farm.area_alq,
        street: farm.street,
        city: farm.city,
        postalCode: farm.postal_code,
        sectionName: farm.section_name,
        ownerName: farm.owner_name,
        municipality: farm.municipality,
        cropYear: farm.crop_year,
        totalAreaAlq: farm.total_area_alq,
        totalAreaHa: farm.total_area_ha,
        metadataUpdatedAt: farm.metadata_updated_at,
        fields: farmFields
      };
    });
  }

  findFarmById(id: string): FarmRecord | null {
    const farm = this.db
      .prepare(
        `
        SELECT
          id,
          code,
          name,
          property_number,
          sequence_number,
          area_ha,
          area_alq,
          street,
          city,
          postal_code,
          section_name,
          owner_name,
          municipality,
          crop_year,
          total_area_alq,
          total_area_ha,
          metadata_updated_at
        FROM farms
        WHERE id = ?
        `
      )
      .get(id) as FarmRow | undefined;

    if (!farm) return null;

    const fields = this.db
      .prepare(
        `
        SELECT id, code, name, area_ha, area_alq, planted_area_ha, crop_year, area_type, active, farm_id
        FROM fields
        WHERE farm_id = ?
        ORDER BY code ASC
        `
      )
      .all(id) as FieldRow[];

    return {
      id: farm.id,
      code: farm.code,
      name: farm.name,
      propertyNumber: farm.property_number ?? undefined,
      sequenceNumber: farm.sequence_number ?? undefined,
      areaHa: farm.area_ha ?? undefined,
      areaAlq: farm.area_alq ?? undefined,
      street: farm.street ?? undefined,
      city: farm.city ?? undefined,
      postalCode: farm.postal_code ?? undefined,
      sectionName: farm.section_name ?? undefined,
      ownerName: farm.owner_name ?? undefined,
      municipality: farm.municipality ?? undefined,
      cropYear: farm.crop_year ?? undefined,
      totalAreaAlq: farm.total_area_alq ?? undefined,
      totalAreaHa: farm.total_area_ha ?? undefined,
      metadataUpdatedAt: farm.metadata_updated_at ?? undefined,
      fields: fields.map((field) => ({
        id: field.id,
        code: field.code,
        name: field.name ?? undefined,
        areaHa: field.area_ha ?? undefined,
        areaAlq: field.area_alq ?? undefined,
        plantedAreaHa: field.planted_area_ha ?? undefined,
        cropYear: field.crop_year ?? undefined,
        areaType: field.area_type,
        active: Boolean(field.active),
        farmId: field.farm_id
      }))
    };
  }

  createFarm(input: CreateFarmInput) {
    const create = this.db.transaction(() => {
      const farmId = randomUUID();
      const farmCode = formatFarmCode(input.code);
      const farmName = normalizeFarmText(input.name);
      const insertField = this.db.prepare("INSERT INTO fields (id, code, farm_id, area_ha, area_alq) VALUES (?, ?, ?, ?, ?)");

      this.db
        .prepare(
          `
          INSERT INTO farms (
            id,
            code,
            name,
            section_name,
            owner_name,
            municipality
          ) VALUES (?, ?, ?, ?, ?, ?)
          `
        )
        .run(
          farmId,
          farmCode || null,
          farmName,
          normalizeFarmText(input.sectionName || farmName),
          normalizeFarmText(input.ownerName) || null,
          normalizeFarmText(input.municipality) || null
        );

      const fieldParamsList = parseFarmFieldInputs(input.fields).map(field => {
        const areaAlq = field.areaAlq ?? null;
        const areaHa = areaAlq === null ? null : roundArea(areaAlq * hectaresPerAlqueire);
        return [randomUUID(), field.code, farmId, areaHa, areaAlq];
      });
      if (fieldParamsList.length > 0) {
        insertField.runMany(fieldParamsList);
      }

      return farmId;
    });

    const farmId = create();
    return this.findFarmById(farmId);
  }

  updateFarm(farmId: string, input: UpdateFarmInput) {
    const current = this.findFarmById(farmId);

    if (!current) {
      return null;
    }

    const farmCode = formatFarmCode(input.code);
    const farmName = normalizeFarmText(input.name);

    this.db
      .prepare(
        `
        UPDATE farms
        SET
          code = ?,
          name = ?,
          section_name = ?,
          owner_name = ?,
          municipality = ?,
          updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        `
      )
      .run(
        farmCode || null,
        farmName,
        input.sectionName === undefined
          ? normalizeFarmText(current.sectionName ?? farmName)
          : normalizeFarmText(input.sectionName) || null,
        input.ownerName === undefined
          ? normalizeFarmText(current.ownerName) || null
          : normalizeFarmText(input.ownerName) || null,
        input.municipality === undefined
          ? normalizeFarmText(current.municipality) || null
          : normalizeFarmText(input.municipality) || null,
        farmId
      );

    return this.findFarmById(farmId) ?? null;
  }

  createField(farmId: string, code: string, name?: string | null, areaAlq?: number | null) {
    const id = randomUUID();
    const areaHa = areaAlq === null || areaAlq === undefined ? null : roundArea(areaAlq * hectaresPerAlqueire);

    this.db
      .prepare("INSERT INTO fields (id, code, name, farm_id, area_ha, area_alq) VALUES (?, ?, ?, ?, ?, ?)")
      .run(id, code, name ?? null, farmId, areaHa, areaAlq ?? null);

    return this.findFieldById(id);
  }

  updateField(fieldId: string, input: UpdateFieldInput) {
    const current = this.findFieldById(fieldId);

    if (!current) {
      return null;
    }

    const areaAlq = hasAreaAlq(input) ? input.areaAlq ?? null : current.areaAlq ?? null;
    const areaHa = hasAreaAlq(input) ? (areaAlq === null ? null : roundArea(areaAlq * hectaresPerAlqueire)) : current.areaHa ?? null;

    this.db
      .prepare("UPDATE fields SET code = ?, name = ?, area_ha = ?, area_alq = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?")
      .run(input.code, input.name || null, areaHa, areaAlq, fieldId);

    return this.findFieldById(fieldId);
  }

  private findFieldById(id: string) {
    const row = this.db
      .prepare(
        `
        SELECT id, code, name, area_ha, area_alq, planted_area_ha, crop_year, area_type, active, farm_id
        FROM fields
        WHERE id = ?
        `
      )
      .get(id) as FieldRow | undefined;
    return row ? mapField(row) : null;
  }
}

function mapField(row: FieldRow): FieldRecord {
  return {
    id: row.id,
    code: row.code,
    name: row.name,
    areaHa: row.area_ha,
    areaAlq: row.area_alq,
    plantedAreaHa: row.planted_area_ha,
    cropYear: row.crop_year,
    areaType: row.area_type,
    active: Boolean(row.active),
    farmId: row.farm_id
  };
}

const fieldCodeCollator = new Intl.Collator("pt-BR", {
  numeric: true,
  sensitivity: "base"
});

function compareFieldCodes(left: string, right: string) {
  const leftNumber = parseNumericFieldCode(left);
  const rightNumber = parseNumericFieldCode(right);

  if (leftNumber !== null && rightNumber !== null && leftNumber !== rightNumber) {
    return leftNumber - rightNumber;
  }

  return fieldCodeCollator.compare(left, right);
}

function parseNumericFieldCode(value: string) {
  const trimmed = value.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
}

const hectaresPerAlqueire = 2.42;

function hasAreaAlq(input: UpdateFieldInput) {
  return Object.prototype.hasOwnProperty.call(input, "areaAlq");
}

function roundArea(value: number) {
  return Math.round(value * 1000) / 1000;
}

function parseFieldCodes(values: string[]) {
  return Array.from(
    new Set(
      values.flatMap((value) =>
        value
          .split(/[\s,;]+/)
          .map((item) => item.trim())
          .filter(Boolean)
      )
    )
  );
}

function parseFarmFieldInputs(values: CreateFarmInput["fields"]) {
  const byCode = new Map<string, { code: string; areaAlq?: number | null }>();

  for (const value of values) {
    if (typeof value === "string") {
      for (const code of parseFieldCodes([value])) {
        if (!byCode.has(code)) {
          byCode.set(code, { code });
        }
      }
      continue;
    }

    for (const code of parseFieldCodes([value.code])) {
      byCode.set(code, { code, areaAlq: value.areaAlq ?? null });
    }
  }

  return [...byCode.values()];
}
