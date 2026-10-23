// Generates TypeScript types from the JSON Schemas exported by the Python contracts.
// Python (backend/regista/contracts) is the single source of truth.
import { compileFromFile } from "json-schema-to-typescript";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const schemaDir = resolve(root, "contracts", "schema");
const outDir = resolve(root, "frontend", "src", "contracts");

const schemas = ["match-file", "ground-truth", "overlay-payload", "fan-profile", "stream"];
const banner = "/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */";

await mkdir(outDir, { recursive: true });
for (const name of schemas) {
  const ts = await compileFromFile(resolve(schemaDir, `${name}.schema.json`), {
    bannerComment: banner,
    additionalProperties: false,
    style: { singleQuote: false, semi: true, printWidth: 110 },
  });
  await writeFile(resolve(outDir, `${name}.ts`), ts);
  console.log(`generated src/contracts/${name}.ts`);
}
