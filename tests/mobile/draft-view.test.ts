import test from "node:test";
import assert from "node:assert/strict";
import { draftSections } from "../../apps/mobile/src/draft-view";
test("draft keeps exact source version and does not invent unsupported citations", () => {
  const sections = draftSections({
    preview: { title: "A life", text: "one" },
    sections: [
      {
        text: "one",
        source_refs: [{ source_id: "id", version: "9007199254740993" }],
      },
      { text: "two" },
    ],
  });
  assert.equal(sections[0]?.references[0]?.version, "9007199254740993");
  assert.deepEqual(sections[1]?.references, []);
  assert.deepEqual(
    draftSections({ preview: null, sections: [{ text: "withdrawn" }] }),
    [],
  );
});
