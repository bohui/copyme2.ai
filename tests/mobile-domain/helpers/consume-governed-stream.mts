/** Consume captured real backend events through the shipped native stack. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createMemoirApi } from "../../../packages/api-client/src/index.ts";
import { initialTurnState, reduceTurn } from "../../../packages/memoir-domain/src/index.ts";

const captures = JSON.parse(readFileSync(0, "utf8"));
for (const capture of captures) {
  const context = { ownerId: "synthetic-owner", projectId: capture.projectId,
    clientTurnId: capture.clientTurnId, generation: 1 };
  let state = initialTurnState(context);
  let completions = 0, saves = 0;
  const api = createMemoirApi({
    baseUrl: "https://controlled.invalid/api/v1/memoir", getToken: async () => "synthetic",
    fetch: async () => new Response(new ReadableStream({ start(controller) {
      for (const event of capture.events)
        controller.enqueue(new TextEncoder().encode(JSON.stringify(event) + "\n"));
      controller.close();
    } }), { headers: { "Content-Type": "application/x-ndjson" } }),
  });
  const outcome = await api.streamTurn({ text: "synthetic", client_turn_id: capture.clientTurnId }, {
    onEvent(event) {
      const accumulated = state.reply;
      state = reduceTurn(state, { type: "event", context, event });
      if (event.type === "reply_complete") {
        completions++;
        assert.equal(typeof event.data.reply, "string");
        assert.equal(state.reply, accumulated, "Completion must preserve received public text");
        assert.equal(state.committed, false, "Completion cannot substitute for the save receipt");
      }
      if (event.type === "conversation_saved") {
        saves++;
        assert.equal(state.committed, true);
      }
    },
  });
  assert.equal(outcome.terminal, "result");
  assert.equal(state.reply, capture.reply);
  assert.equal(state.committed, true);
  assert.equal(completions, capture.cached ? 0 : 1);
  assert.equal(saves, capture.cached ? 0 : 1);
}
console.log(`Consumed ${captures.length} captured native streams without interruption.`);
