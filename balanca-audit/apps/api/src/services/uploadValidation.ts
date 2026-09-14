import fs from "node:fs/promises";
import path from "node:path";
import { badRequest } from "../errors.js";

export type UploadExtension = ".pdf" | ".jpg" | ".jpeg" | ".png" | ".webp" | ".xlsx" | ".csv";

type UploadInspection = {
  extension: UploadExtension;
  mimeType: string;
};

const canonicalMimeTypes: Record<UploadExtension, string> = {
  ".pdf": "application/pdf",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".csv": "text/csv"
};

export async function assertUploadedFile(
  file: Express.Multer.File,
  allowedExtensions: UploadExtension[],
  message = "Formato de arquivo invalido."
): Promise<UploadInspection> {
  const extension = path.extname(file.originalname).toLowerCase() as UploadExtension;

  if (!allowedExtensions.includes(extension)) {
    throw badRequest(message);
  }

  if (file.size <= 0) {
    throw badRequest("O arquivo enviado esta vazio. Gere ou baixe o documento novamente antes de enviar.");
  }

  const header = await readHeader(file.path);

  if (!matchesContent(extension, header)) {
    throw badRequest(message);
  }

  if ([".jpg", ".jpeg", ".png", ".webp"].includes(extension)) {
    const inspectionBuffer = await readInspectionBuffer(file.path, Math.min(file.size, 1024 * 1024));
    const dimensions = readImageDimensionsFromBuffer(extension, inspectionBuffer);
    const maxPixels = readPositiveInteger("UPLOAD_MAX_IMAGE_PIXELS", 60_000_000, 1_000_000, 200_000_000);
    const maxSide = readPositiveInteger("UPLOAD_MAX_IMAGE_SIDE", 20_000, 1_000, 50_000);

    if (!dimensions) {
      throw badRequest("Nao foi possivel validar as dimensoes da imagem enviada.");
    }
    if (dimensions.width > maxSide || dimensions.height > maxSide || dimensions.width * dimensions.height > maxPixels) {
      throw badRequest(
        `Imagem muito grande para processamento (${dimensions.width}x${dimensions.height}). Reduza a resolucao antes de enviar.`
      );
    }
  }

  return {
    extension,
    mimeType: canonicalMimeTypes[extension]
  };
}

async function readHeader(filePath: string) {
  const handle = await fs.open(filePath, "r");

  try {
    const buffer = Buffer.alloc(32);
    const result = await handle.read(buffer, 0, buffer.length, 0);
    return buffer.subarray(0, result.bytesRead);
  } finally {
    await handle.close();
  }
}

async function readInspectionBuffer(filePath: string, length: number) {
  const handle = await fs.open(filePath, "r");

  try {
    const buffer = Buffer.alloc(length);
    const result = await handle.read(buffer, 0, buffer.length, 0);
    return buffer.subarray(0, result.bytesRead);
  } finally {
    await handle.close();
  }
}

export function readImageDimensionsFromBuffer(extension: UploadExtension, buffer: Buffer) {
  if (extension === ".png" && buffer.length >= 24) {
    return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
  }

  if ((extension === ".jpg" || extension === ".jpeg") && buffer.length >= 10) {
    return readJpegDimensions(buffer);
  }

  if (extension === ".webp" && buffer.length >= 30) {
    return readWebpDimensions(buffer);
  }

  return null;
}

function readJpegDimensions(buffer: Buffer) {
  let offset = 2;
  const startOfFrameMarkers = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

  while (offset + 9 < buffer.length) {
    if (buffer[offset] !== 0xff) {
      offset += 1;
      continue;
    }

    while (buffer[offset] === 0xff) {
      offset += 1;
    }
    const marker = buffer[offset];
    offset += 1;

    if (marker === 0xd8 || marker === 0xd9 || (marker >= 0xd0 && marker <= 0xd7)) {
      continue;
    }
    if (offset + 2 > buffer.length) {
      return null;
    }

    const segmentLength = buffer.readUInt16BE(offset);
    if (segmentLength < 2 || offset + segmentLength > buffer.length) {
      return null;
    }
    if (startOfFrameMarkers.has(marker) && segmentLength >= 7) {
      return { width: buffer.readUInt16BE(offset + 5), height: buffer.readUInt16BE(offset + 3) };
    }

    offset += segmentLength;
  }

  return null;
}

function readWebpDimensions(buffer: Buffer) {
  const chunk = buffer.subarray(12, 16).toString("ascii");

  if (chunk === "VP8X") {
    return {
      width: 1 + buffer.readUIntLE(24, 3),
      height: 1 + buffer.readUIntLE(27, 3)
    };
  }
  if (chunk === "VP8 " && buffer.length >= 30 && buffer.subarray(23, 26).equals(Buffer.from([0x9d, 0x01, 0x2a]))) {
    return {
      width: buffer.readUInt16LE(26) & 0x3fff,
      height: buffer.readUInt16LE(28) & 0x3fff
    };
  }
  if (chunk === "VP8L" && buffer[20] === 0x2f) {
    const b1 = buffer[21];
    const b2 = buffer[22];
    const b3 = buffer[23];
    const b4 = buffer[24];
    return {
      width: 1 + (b1 | ((b2 & 0x3f) << 8)),
      height: 1 + ((b2 >> 6) | (b3 << 2) | ((b4 & 0x0f) << 10))
    };
  }

  return null;
}

function readPositiveInteger(name: string, fallback: number, minimum: number, maximum: number) {
  const value = Number(process.env[name]);
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}

function matchesContent(extension: UploadExtension, header: Buffer) {
  switch (extension) {
    case ".pdf":
      return header.subarray(0, 5).toString("ascii") === "%PDF-";
    case ".jpg":
    case ".jpeg":
      return header.length >= 3 && header[0] === 0xff && header[1] === 0xd8 && header[2] === 0xff;
    case ".png":
      return header.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
    case ".webp":
      return header.subarray(0, 4).toString("ascii") === "RIFF" && header.subarray(8, 12).toString("ascii") === "WEBP";
    case ".xlsx":
      return header.length >= 4 && header[0] === 0x50 && header[1] === 0x4b && [0x03, 0x05, 0x07].includes(header[2]);
    case ".csv":
      return header.length > 0 && !header.includes(0x00) && !looksLikeKnownBinary(header);
  }

  return false;
}

function looksLikeKnownBinary(header: Buffer) {
  return (
    header.subarray(0, 5).toString("ascii") === "%PDF-" ||
    (header.length >= 3 && header[0] === 0xff && header[1] === 0xd8 && header[2] === 0xff) ||
    header.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) ||
    (header.subarray(0, 4).toString("ascii") === "RIFF" && header.subarray(8, 12).toString("ascii") === "WEBP")
  );
}
