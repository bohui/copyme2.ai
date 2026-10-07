import test from "node:test";
import assert from "node:assert/strict";
import { formatDateExpression as webFormatDateExpression } from "../../apps/web/client/memoir/dates.mjs";
import {
  formatDateExpression,
  compareLifeStages,
  initialTurnState,
  reduceTurn,
  validateAuthCallback,
  resolveDeepLink,
} from "../../packages/memoir-domain/src/index.ts";

test("native date port retains web exact-date and uncertainty behavior in both locales", () => {
  for (const locale of ["en-AU", "zh-CN"] as const)
    for (const date of [
      "",
      null,
      "1976",
      "1976-02",
      "1976/2/3",
      "1976-02-29",
      "1976-02-30",
      "2000-01-01T09:30:00Z",
      "around 1976",
      "the late 1960s",
      "1970–1979",
    ])
      assert.equal(
        formatDateExpression(date, locale),
        webFormatDateExpression(date, locale),
      );
  assert.equal(compareLifeStages("baby", "childhood") < 0, true);
  assert.equal(compareLifeStages("later_life", "unplaced") < 0, true);
});
test("workspace updates at equal exact sequence merge; stale sequence cannot overwrite", () => {
  let state = initialTurnState({
    ownerId: "owner",
    projectId: "p",
    clientTurnId: "id",
    generation: 1,
  });
  const send = (sequence: string, fields: Record<string, unknown>) => {
    state = reduceTurn(state, {
      type: "event",
      context: state.context,
      event: {
        type: "workspace_update",
        data: { project_id: "p", source_sequence: sequence, ...fields },
      },
    });
  };
  send("1730000000000000002", { family_context: { revision: 2 } });
  send("1730000000000000002", { place_journey: { place: "Beijing" } });
  send("1730000000000000001", { family_context: { revision: 1 } });
  assert.deepEqual(state.workspace.family_context, { revision: 2 });
  assert.deepEqual(state.workspace.place_journey, { place: "Beijing" });
  assert.equal(state.committed, false);
});
test("auth callback state, expiry and one-time use require explicit native flow state", () => {
  const link = resolveDeepLink(
    "memoir://auth/callback?code=pkce-code&state=nonce",
    { httpsHosts: ["memoir.example"], scheme: "memoir" },
  );
  assert.equal(
    validateAuthCallback(
      link,
      { state: "nonce", expiresAt: 2000, consumed: false },
      1000,
    ),
    true,
  );
  assert.equal(
    validateAuthCallback(
      link,
      { state: "other", expiresAt: 2000, consumed: false },
      1000,
    ),
    false,
  );
  assert.equal(
    validateAuthCallback(
      link,
      { state: "nonce", expiresAt: 2000, consumed: true },
      1000,
    ),
    false,
  );
  assert.equal(
    validateAuthCallback(
      link,
      { state: "nonce", expiresAt: 1000, consumed: false },
      1000,
    ),
    false,
  );
});
