import type {
  DashboardFilterInput,
  EntryStatus,
  FleetEquipmentType,
  FleetMovementStatus,
  FleetMovementType,
  ImportMappingInput,
  UserRole
} from "@balanca/shared";

export type User = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
};

export type Field = {
  id: string;
  code: string;
  name?: string | null;
  areaHa?: number | null;
  areaAlq?: number | null;
  plantedAreaHa?: number | null;
  cropYear?: string | null;
  areaType?: string | null;
  active?: boolean;
  farmId: string;
};

export type Farm = {
  id: string;
  code?: string | null;
  name: string;
  propertyNumber?: string | null;
  sequenceNumber?: string | null;
  areaHa?: number | null;
  areaAlq?: number | null;
  street?: string | null;
  city?: string | null;
  postalCode?: string | null;
  sectionName?: string | null;
  ownerName?: string | null;
  municipality?: string | null;
  cropYear?: string | null;
  totalAreaAlq?: number | null;
  totalAreaHa?: number | null;
  metadataUpdatedAt?: string | null;
  fields: Field[];
};

export type PropertyImportPreview = {
  fileName: string;
  backupPath?: string;
  summary: {
    rowCount: number;
    insertCount: number;
    updateCount: number;
    mergeCount: number;
    duplicateNameCount: number;
    missingAreaCount: number;
    missingAddressCount: number;
  };
  rows: Array<{
    code: string;
    name: string;
    propertyNumber: string;
    sequenceNumber: string;
    areaHa?: number | null;
    areaAlq?: number | null;
    street?: string | null;
    city?: string | null;
    postalCode?: string | null;
    action: "INSERT" | "UPDATE" | "MERGE";
    existingCode?: string | null;
    warnings: string[];
  }>;
};

export type HarvestOrder = {
  id: string;
  number: string;
  frontNumber?: number | null;
  frontNumbers: number[];
  farmId: string;
  farmIds: string[];
  status: "ACTIVE" | "CLOSED";
  startDate?: string | null;
  endDate?: string | null;
  farm: Farm;
  farms: Farm[];
  fields: Array<{
    id: string;
    fieldId: string;
    field: Field;
  }>;
};

export type HarvestOrderHistoryEventType = "STARTED" | "RELEASED" | "FRONTS_CHANGED" | "CLOSED" | "REOPENED";

export type HarvestOrderHistory = {
  id: string;
  orderId?: string | null;
  orderNumber: string;
  eventType: HarvestOrderHistoryEventType;
  frontNumbersBefore: number[];
  frontNumbersAfter: number[];
  occurredAt: string;
};

export type BulkCloseOrderResult = {
  number: string;
  status: "CLOSED" | "ALREADY_CLOSED" | "NOT_FOUND";
  orderIds?: string[];
  fronts?: number[];
  farms?: string[];
  closedCount?: number;
  integrationEventCount?: number;
  message: string;
};

export type PostHarvestIntegrationStatus = "PENDING" | "PROCESSING" | "SENT" | "ERROR" | "DEAD";

export type PostHarvestIntegrationEvent = {
  id: string;
  eventId: string;
  eventType: string;
  orderId?: string | null;
  orderNumber: string;
  farmId?: string | null;
  farmCode?: string | null;
  farmName: string;
  fieldId?: string | null;
  fieldCode: string;
  frontNumbers: number[];
  payload: unknown;
  status: PostHarvestIntegrationStatus;
  attemptCount: number;
  maxAttempts?: number;
  availableAt?: string;
  leaseOwner?: string | null;
  leaseExpiresAt?: string | null;
  lastHttpStatus?: number | null;
  lastResponseBody?: string | null;
  lastError?: string | null;
  sentAt?: string | null;
  deadAt?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type PostHarvestIntegrationConnection = {
  mode: "OUTGOING_WEBHOOK";
  configured: boolean;
  targetUrlConfigured: boolean;
  tokenConfigured: boolean;
  timeoutMs: number;
  requiredReceiver: {
    method: string;
    contentType: string;
    idempotencyHeader: string;
    authorizationHeader: string;
  };
  env: {
    url: string;
    token: string;
    timeoutMs: string;
  };
};

export type PostHarvestExportIssue = {
  orderId: string;
  orderNumber: string;
  farmCode?: string | null;
  fieldCode?: string | null;
  message: string;
};

export type PostHarvestExportSummary = {
  closedOrders: number;
  rowCount: number;
  invalidCount: number;
  issues: PostHarvestExportIssue[];
};

export type CaneEntry = {
  id: string;
  ticketNumber?: string | null;
  entryDate?: string | null;
  farmNameRaw?: string | null;
  fieldCodeRaw?: string | null;
  orderNumberRaw?: string | null;
  vehiclePlate?: string | null;
  grossWeight?: number | null;
  netWeight?: number | null;
  status: EntryStatus;
  notes?: string | null;
  batch: {
    fileName: string;
    importedAt: string;
  };
};

export type ImportBatch = {
  id: string;
  fileName: string;
  storedFileName?: string | null;
  mimeType?: string | null;
  fileSize?: number | null;
  fileHash?: string | null;
  sourceType?: string | null;
  reportDate?: string | null;
  periodStart?: string | null;
  periodEnd?: string | null;
  totalNetWeight?: number | null;
  totalTrips?: number | null;
  importedAt: string;
  rowCount: number;
  okCount: number;
  errorCount: number;
  entryDateFrom?: string | null;
  entryDateTo?: string | null;
};

export type ImportBatchEntry = Omit<CaneEntry, "batch">;

export type Summary = {
  totalEntries: number;
  okEntries: number;
  divergentEntries: number;
  areaHa: number;
  areaAlq: number;
  byStatus: Array<{ status: EntryStatus; count: number }>;
  areaByDate: Array<{
    date: string;
    fieldCount: number;
    areaHa: number;
    areaAlq: number;
    divergentFieldCount: number;
    divergentAreaHa: number;
    divergentAreaAlq: number;
    cumulativeAreaHa: number;
    cumulativeAreaAlq: number;
  }>;
  recentDivergences: CaneEntry[];
  recentBatches: ImportBatch[];
};

export type FieldProductionRow = {
  farmId?: string | null;
  farmCode?: string | null;
  farmName: string;
  fieldId?: string | null;
  fieldCode: string;
  fieldName?: string | null;
  areaHa?: number | null;
  areaAlq?: number | null;
  entryCount: number;
  okCount: number;
  divergentCount: number;
  totalNetWeight: number;
  okNetWeight: number;
  divergentNetWeight: number;
  firstReportDate?: string | null;
  lastReportDate?: string | null;
  lastImportedAt?: string | null;
};

export type ProductionPeriodRow = {
  periodStart?: string | null;
  periodEnd?: string | null;
  entryCount: number;
  farmCount: number;
  fieldCount: number;
  totalNetWeight: number;
  divergentNetWeight: number;
};

export type ProductionDashboard = {
  totals: {
    farms: number;
    fields: number;
    entries: number;
    totalNetWeight: number;
    divergentNetWeight: number;
  };
  periods: ProductionPeriodRow[];
  rows: FieldProductionRow[];
};

export type HarvestOwnershipType = "OWN" | "SUPPLIER" | "UNKNOWN";

export type HarvestOwnershipRow = {
  type: HarvestOwnershipType;
  label: string;
  farmCount: number;
  fieldCount: number;
  entryCount: number;
  totalNetWeight: number;
  areaHa: number;
  areaAlq: number;
  percentage: number;
  tch?: number | null;
  tca?: number | null;
};

export type HarvestRankingRow = {
  farmId?: string | null;
  farmCode?: string | null;
  farmName: string;
  ownershipType: HarvestOwnershipType;
  fieldCount: number;
  entryCount: number;
  totalNetWeight: number;
  areaHa: number;
  areaAlq: number;
  tch?: number | null;
  percentage: number;
};

export type HarvestFieldRankingRow = {
  farmCode?: string | null;
  farmName: string;
  fieldCode: string;
  ownershipType: HarvestOwnershipType;
  entryCount: number;
  totalNetWeight: number;
  areaHa?: number | null;
  areaAlq?: number | null;
  tch?: number | null;
};

export type HarvestExecutiveDashboard = {
  generatedAt: string;
  rule: string;
  totals: {
    farms: number;
    fields: number;
    entries: number;
    totalNetWeight: number;
    divergentNetWeight: number;
    netWeightWithArea: number;
    netWeightWithoutArea: number;
    areaCoveragePercentage: number;
    entriesWithoutArea: number;
    fieldsWithoutArea: number;
    areaHa: number;
    areaAlq: number;
    tch?: number | null;
    tca?: number | null;
    ownNetWeight: number;
    supplierNetWeight: number;
    unknownNetWeight: number;
    ownPercentage: number;
    supplierPercentage: number;
  };
  periodStart?: string | null;
  periodEnd?: string | null;
  ownership: HarvestOwnershipRow[];
  topFarms: HarvestRankingRow[];
  topFields: HarvestFieldRankingRow[];
  periods: ProductionPeriodRow[];
};

export type PreviewImport = {
  sourceType: "SPREADSHEET" | "SCS0110P_PDF";
  fileHash: string;
  columns: string[];
  mapping: ImportMappingInput;
  summary: {
    rowCount: number;
    okCount: number;
    errorCount: number;
    byStatus: Array<{ status: EntryStatus; count: number }>;
    areaHa: number;
    areaAlq: number;
    areaByDate: Array<{
      date: string;
      fieldCount: number;
      areaHa: number;
      areaAlq: number;
    }>;
    reconciliation?: {
      status: "MATCH" | "MISMATCH" | "NOT_AVAILABLE";
      expectedNetWeight?: number;
      parsedNetWeight: number;
      netWeightDifference?: number;
      expectedTrips?: number;
      parsedTrips: number;
      tripDifference?: number;
      extractionSource: "local" | "google-vision" | "gemini";
      assisted: boolean;
    };
  };
  rows: Array<{
    ticketNumber?: string;
    entryDate?: string;
    farmCodeRaw?: string;
    farmRaw?: string;
    fieldRaw?: string;
    orderRaw?: string;
    vehiclePlate?: string;
    grossWeight?: number;
    netWeight?: number;
    tripCount?: number;
    fieldId?: string;
    areaHa?: number | null;
    areaAlq?: number | null;
    status: EntryStatus;
    notes?: string;
  }>;
};















export type DashboardFilters = DashboardFilterInput;

export type FleetReportSummary = {
  total: number;
  operating: number;
  moved: number;
  outOfOperation: number;
  efficiency: number;
};

export type FleetReportPreview = {
  fileName: string;
  generatedAt: string;
  frontCount: number;
  busCount: number;
  productive: FleetReportSummary;
  support: FleetReportSummary;
  supportByType: Array<
    FleetReportSummary & {
      type: string;
      label: string;
    }
  >;
  fronts: Array<{
    name: string;
    productive: FleetReportSummary & {
      harvesters: string;
      transbordos: string;
    };
    support: FleetReportSummary;
  }>;
  equipment: Array<{
    code: string;
    type: string;
    typeLabel: string;
    frontName: string;
    frontNumber: number | null;
    status: "VERDE" | "VERMELHO" | "AZUL" | "";
    statusLabel: string;
    source: "BASE" | "MOVEMENT";
    movementId?: string;
    note?: string;
    coveredBy?: string;
    loanedToFrontName?: string;
  }>;
  substitutions: Array<{
    movementId: string;
    frontName: string;
    frontNumber: number | null;
    replacedCode: string;
    replacementCode: string;
    equipmentType: string;
    typeLabel: string;
    sourceFrontName?: string;
    occurredAt: string;
    reason?: string | null;
  }>;
  movementSummary: {
    applied: number;
    warnings: string[];
  };
  observations: string[];
};

export type FleetMovement = {
  id: string;
  movementType: FleetMovementType;
  equipmentCode: string;
  equipmentType: FleetEquipmentType;
  frontNumber?: number | null;
  reserveCode?: string | null;
  replacesCode?: string | null;
  reason?: string | null;
  status: FleetMovementStatus;
  occurredAt: string;
  createdAt: string;
  updatedAt: string;
};
