import { parseTurnEvent, type TurnEvent } from "@memoir/contracts";

/** Keep oversized integer lexemes exact before native JSON.parse can round them.
 * Strings, escaped quotes, decimals and scientific notation are not rewritten.
 * Contract schemas decide which integer fields accept decimal-string values.
 */
export function parseWireJson(text: string): unknown {
  let output = "",
    inside = false,
    escaped = false;
  for (let i = 0; i < text.length;) {
    const char = text[i]!;
    if (inside) {
      output += char;
      i++;
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inside = false;
      continue;
    }
    if (char === '"') {
      inside = true;
      output += char;
      i++;
      continue;
    }
    if (char === "-" || /\d/.test(char)) {
      const match = text
        .slice(i)
        .match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
      if (match) {
        const token = match[0];
        output +=
          /^-?\d+$/.test(token) && !Number.isSafeInteger(Number(token))
            ? JSON.stringify(token)
            : token;
        i += token.length;
        continue;
      }
    }
    output += char;
    i++;
  }
  return JSON.parse(output);
}

function decodeUtf8(bytes: readonly number[]): string {
  let output = "";
  for (let i = 0; i < bytes.length;) {
    const first = bytes[i++]!;
    let code = first,
      count = 0,
      minimum = 0;
    if (first <= 0x7f) {
      output += String.fromCharCode(first);
      continue;
    }
    if (first >= 0xc2 && first <= 0xdf) {
      code = first & 31;
      count = 1;
      minimum = 0x80;
    } else if (first >= 0xe0 && first <= 0xef) {
      code = first & 15;
      count = 2;
      minimum = 0x800;
    } else if (first >= 0xf0 && first <= 0xf4) {
      code = first & 7;
      count = 3;
      minimum = 0x10000;
    } else throw new Error("Invalid UTF-8 stream");
    if (i + count > bytes.length) throw new Error("Incomplete UTF-8 stream");
    for (let n = 0; n < count; n++) {
      const next = bytes[i++]!;
      if ((next & 0xc0) !== 0x80) throw new Error("Invalid UTF-8 stream");
      code = (code << 6) | (next & 63);
    }
    if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff))
      throw new Error("Invalid UTF-8 stream");
    output += String.fromCodePoint(code);
  }
  return output;
}
export interface DecoderLimits {
  maxLineBytes?: number;
  maxTotalBytes?: number;
  maxEvents?: number;
}
/** A bounded byte-line accumulator tolerates any network split, including UTF-8.
 * It does not infer commit or completion from EOF. No browser/Node APIs required.
 */
export class NdjsonDecoder {
  private line: number[] = [];
  private total = 0;
  private events = 0;
  private closed = false;
  private readonly maxLineBytes: number;
  private readonly maxTotalBytes: number;
  private readonly maxEvents: number;
  constructor(limits: DecoderLimits = {}) {
    this.maxLineBytes = limits.maxLineBytes ?? 1024 * 1024;
    this.maxTotalBytes = limits.maxTotalBytes ?? 32 * 1024 * 1024;
    this.maxEvents = limits.maxEvents ?? 20000;
    for (const limit of [this.maxLineBytes, this.maxTotalBytes, this.maxEvents])
      if (!Number.isSafeInteger(limit) || limit <= 0)
        throw new Error("Invalid stream limit");
  }
  push(chunk: Uint8Array): TurnEvent[] {
    if (this.closed) throw new Error("Stream decoder is closed");
    this.total += chunk.byteLength;
    if (this.total > this.maxTotalBytes)
      throw new Error("Stream byte limit exceeded");
    const result: TurnEvent[] = [];
    for (const byte of chunk) {
      if (byte === 10) {
        const event = this.readLine();
        if (event) result.push(event);
      } else {
        this.line.push(byte);
        if (this.line.length > this.maxLineBytes)
          throw new Error("Stream line limit exceeded");
      }
    }
    return result;
  }
  finish(): TurnEvent[] {
    if (this.closed) return [];
    this.closed = true;
    const event = this.readLine();
    return event ? [event] : [];
  }
  private readLine(): TurnEvent | null {
    if (this.line.at(-1) === 13) this.line.pop();
    const text = decodeUtf8(this.line);
    this.line = [];
    if (!text.trim()) return null;
    if (++this.events > this.maxEvents)
      throw new Error("Stream event limit exceeded");
    let value: unknown;
    try {
      value = parseWireJson(text);
    } catch {
      throw new Error("Invalid JSON in turn stream");
    }
    return parseTurnEvent(value);
  }
}
