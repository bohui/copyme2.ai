import type { PrivateDraft } from "@memoir/contracts";
export interface DraftReference {
  id: string;
  version?: string;
  quote?: string;
}
export interface DraftSection {
  id: string;
  title: string;
  text: string;
  references: DraftReference[];
}
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown) => (typeof value === "string" ? value : "");
/** Never manufacture paragraph citations when the server hasn't supplied them. */
export function draftSections(draft: PrivateDraft): DraftSection[] {
  if (!draft.preview) return [];
  const sections = Array.isArray(draft.sections) ? draft.sections : [];
  return sections
    .map((raw, index) => {
      const section = object(raw);
      const references = (
        Array.isArray(section.source_refs) ? section.source_refs : []
      )
        .map((raw) => {
          const ref = object(raw);
          return {
            id: text(ref.source_id),
            version:
              typeof ref.version === "string" || typeof ref.version === "number"
                ? String(ref.version)
                : undefined,
            quote: text(ref.quote) || undefined,
          };
        })
        .filter((ref) => !!ref.id);
      return {
        id: text(section.id) || String(index),
        title: text(section.title),
        text: text(section.text ?? section.content),
        references,
      };
    })
    .filter((section) => !!section.text);
}
