import fs from "node:fs";
import path from "node:path";
import { parse } from "@formatjs/icu-messageformat-parser";

const locales = ["en-AU", "zh-CN"];
const root = path.resolve(new URL("..", import.meta.url).pathname, "messages");
const failures = [];

function leaves(value, prefix = "") {
  if (typeof value === "string") return [[prefix, value]];
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Message ${prefix || "<root>"} must be a string or object`);
  }
  return Object.entries(value).flatMap(([key, child]) => leaves(child, prefix ? `${prefix}.${key}` : key));
}

for (const locale of locales) {
  const file = path.join(root, `${locale}.json`);
  const messages = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const [key, message] of leaves(messages)) {
    try {
      parse(message, { requiresOtherClause: false });
    } catch (error) {
      failures.push(`${locale}: invalid ICU message at ${key}: ${error.message}`);
    }
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`ICU messages valid: ${locales.join(", ")}`);
}
