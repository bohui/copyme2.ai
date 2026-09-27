#!/usr/bin/env node
/** Full ICU parsing; fail closed when the target project's parser is missing.
 * Usage: node check_icu.mjs <project-root> <base.json> <other.json> [...]
 * Run check_catalogs.py first for duplicate keys and shape checks.
 */
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const [project, ...files] = process.argv.slice(2);
if (!project || files.length < 2) {
  console.error('Usage: check_icu.mjs PROJECT BASE.json TRANSLATION.json [...]');
  process.exit(2);
}
let parse;
try {
  const require = createRequire(path.resolve(project, 'package.json'));
  const location = require.resolve('@formatjs/icu-messageformat-parser');
  const module = await import(pathToFileURL(location).href);
  parse = module.parse ?? module.default?.parse;
  if (typeof parse !== 'function') throw new Error('Parser export not found');
} catch {
  console.error('ICU validation NOT RUN: install @formatjs/icu-messageformat-parser in the target project.');
  process.exit(2);
}
const flatten = (node, prefix = '', result = {}) => {
  for (const [key, value] of Object.entries(node)) {
    const full = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') result[full] = value;
    else if (value && typeof value === 'object' && !Array.isArray(value)) flatten(value, full, result);
    else throw new Error(`Invalid leaf ${full}`);
  }
  return result;
};
// Keep argument names and broad types, not language-specific plural categories.
function signature(ast) {
  const slots = new Map();
  const add = (name, kind) => {
    if (!slots.has(name)) slots.set(name, new Set());
    slots.get(name).add(kind);
  };
  const visit = (items) => {
    for (const item of items) {
      if (item.type === 1) add(item.value, 'value');
      if (item.type === 2 || item.type === 6) add(item.value, 'number');
      if (item.type === 3 || item.type === 4) add(item.value, 'date');
      if (item.type === 5) add(item.value, 'select');
      if (item.type === 8) {add(item.value, 'tag'); visit(item.children);}
      if (item.options) for (const option of Object.values(item.options)) visit(option.value);
    }
  };
  visit(ast);
  return Object.fromEntries([...slots.entries()].sort().map(([name, kinds]) => [name, [...kinds].sort()]));
}
let errors = [];
let base;
for (const file of files) {
  try {
    const flat = flatten(JSON.parse(fs.readFileSync(file, 'utf8')));
    const current = {};
    for (const [key, message] of Object.entries(flat)) {
      try {current[key] = signature(parse(message, {requiresOtherClause: true}));}
      catch (error) {errors.push({file, key, kind: 'invalid_icu', detail: error.message});}
    }
    if (!base) base = current;
    else {
      for (const key of new Set([...Object.keys(base), ...Object.keys(current)])) {
        if (!base[key] || !current[key]) errors.push({file, key, kind: 'missing_or_extra_key'});
        else if (JSON.stringify(base[key]) !== JSON.stringify(current[key]))
          errors.push({file, key, kind: 'argument_or_tag_signature_mismatch'});
      }
    }
  } catch (error) {errors.push({file, kind: 'invalid_catalogue', detail: error.message});}
}
console.log(JSON.stringify({icu_ok: errors.length === 0, errors}, null, 2));
process.exitCode = errors.length ? 1 : 0;
