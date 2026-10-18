import type { ImportMappingInput } from "@balanca/shared";

export const columnAliases: Record<keyof ImportMappingInput, string[]> = {
  ticketNumber: ["nota", "ticket", "romaneio", "numero", "número", "nf", "nfe"],
  entryDate: ["data", "entrada", "data entrada", "dt entrada"],
  farm: ["fazenda", "propriedade", "fornecedor", "origem"],
  field: ["talhao", "talhão", "quadra", "gleba"],
  order: ["os", "o.s", "ordem", "ordem servico", "ordem serviço", "ordem de servico", "ordem de serviço", "colheita"],
  vehiclePlate: ["placa", "caminhao", "caminhão", "veiculo", "veículo"],
  grossWeight: ["peso bruto", "bruto", "pb"],
  netWeight: ["peso liquido", "peso líquido", "liquido", "líquido", "pl"]
};

// Short aliases such as "pl" or "os" only match whole words; "placa" must not become net weight.
const minimumSubstringAliasLength = 4;

export function detectMapping(columns: string[], customMapping?: ImportMappingInput): ImportMappingInput {
  const mapping: ImportMappingInput = {};

  for (const key of Object.keys(columnAliases) as Array<keyof ImportMappingInput>) {
    mapping[key] = customMapping?.[key] || findColumn(columns, columnAliases[key]);
  }

  return mapping;
}

export function findColumn(columns: string[], aliases: string[]) {
  const normalizedAliases = aliases.map(normalizeColumnWords).filter(Boolean);
  let best: { column: string; rank: number } | undefined;

  for (const column of columns) {
    const rank = matchRank(normalizeColumnWords(column), normalizedAliases);

    if (rank > 0 && (!best || rank > best.rank)) {
      best = { column, rank };
    }
  }

  return best?.column;
}

function matchRank(column: string, aliases: string[]) {
  if (!column) {
    return 0;
  }

  if (aliases.includes(column)) {
    return 3;
  }

  const paddedColumn = ` ${column} `;
  if (aliases.some((alias) => paddedColumn.includes(` ${alias} `))) {
    return 2;
  }

  const compactColumn = column.replace(/ /g, "");
  if (aliases.some((alias) => alias.length >= minimumSubstringAliasLength && compactColumn.includes(alias.replace(/ /g, "")))) {
    return 1;
  }

  return 0;
}

export function normalizeColumnWords(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}
