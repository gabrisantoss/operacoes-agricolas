import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { assertUploadedFile, readImageDimensionsFromBuffer } from "./uploadValidation.js";

test("assertUploadedFile reports an empty PDF explicitly", async () => {
  const filePath = path.join(os.tmpdir(), `empty-upload-${process.pid}.pdf`);
  await fs.writeFile(filePath, Buffer.alloc(0));

  try {
    await assert.rejects(
      () =>
        assertUploadedFile(
          {
            path: filePath,
            originalname: "relatorio.pdf",
            size: 0
          } as Express.Multer.File,
          [".pdf"]
        ),
      /arquivo enviado esta vazio/i
    );
  } finally {
    await fs.rm(filePath, { force: true });
  }
});

test("reads PNG dimensions without decoding the full image", () => {
  const buffer = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(buffer);
  buffer.writeUInt32BE(6_000, 16);
  buffer.writeUInt32BE(4_000, 20);

  assert.deepEqual(readImageDimensionsFromBuffer(".png", buffer), { width: 6_000, height: 4_000 });
});

test("rejects an image whose declared dimensions exceed the safe processing limit", async () => {
  const filePath = path.join(os.tmpdir(), `oversized-upload-${process.pid}.png`);
  const buffer = Buffer.alloc(32);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(buffer);
  buffer.writeUInt32BE(20_001, 16);
  buffer.writeUInt32BE(4_000, 20);
  await fs.writeFile(filePath, buffer);

  try {
    await assert.rejects(
      () =>
        assertUploadedFile(
          {
            path: filePath,
            originalname: "imagem-teste.png",
            size: buffer.length
          } as Express.Multer.File,
          [".png"]
        ),
      /imagem muito grande/i
    );
  } finally {
    await fs.rm(filePath, { force: true });
  }
});
