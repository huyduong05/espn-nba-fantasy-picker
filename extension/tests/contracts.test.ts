import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

import type { AnySchema } from "ajv";
import { Ajv2020 } from "ajv/dist/2020.js";
import type { FormatsPlugin } from "ajv-formats";
import { describe, expect, it } from "vitest";

import {
  SCHEMA_VERSION,
  type DraftState,
  type RecommendationResponse,
} from "../src/index.js";

const extensionDirectory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const addFormats = require("ajv-formats") as FormatsPlugin;
const repositoryRoot = path.resolve(extensionDirectory, "../..");
const fixturesDirectory = path.join(repositoryRoot, "tests", "fixtures");
const schemasDirectory = path.join(repositoryRoot, "schemas", "v1");

function readJson(filePath: string): unknown {
  return JSON.parse(readFileSync(filePath, "utf8")) as unknown;
}

const contractMap = readJson(
  path.join(fixturesDirectory, "contract-map.json"),
) as Record<string, string>;

describe("shared contracts", () => {
  it.each(Object.entries(contractMap))(
    "validates %s against %s",
    (fixtureName, schemaName) => {
      const ajv = new Ajv2020({ allErrors: true, strict: true });
      addFormats(ajv);
      const schema = readJson(
        path.join(schemasDirectory, `${schemaName}.schema.json`),
      ) as AnySchema;
      const fixture = readJson(path.join(fixturesDirectory, fixtureName));
      const validator = ajv.compile(schema);

      expect(validator(fixture), JSON.stringify(validator.errors)).toBe(true);
    },
  );

  it("keeps TypeScript request and response versions aligned", () => {
    const request = readJson(
      path.join(fixturesDirectory, "draft-state.valid.json"),
    ) as DraftState;
    const response = readJson(
      path.join(fixturesDirectory, "recommendation.valid.json"),
    ) as RecommendationResponse;

    expect(request.schema_version).toBe(SCHEMA_VERSION);
    expect(response.schema_version).toBe(SCHEMA_VERSION);
  });

  it("rejects an out-of-range recommendation score", () => {
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    const schema = readJson(
      path.join(schemasDirectory, "recommendation.schema.json"),
    ) as AnySchema;
    const fixture = readJson(
      path.join(fixturesDirectory, "recommendation.valid.json"),
    ) as RecommendationResponse;
    fixture.recommendations[0]!.score = 10.1;

    expect(ajv.compile(schema)(fixture)).toBe(false);
  });
});
