import type { FetchTransport } from "@memoir/api-client";
const recall = {
  rounds_completed: 5,
  free_rounds: 20,
  payment_required: false,
  paid: false,
};
export const fixtureOwner = "fixture-storyteller";
export const fixtureProject = "fixture-hobart";
export const fixtureMemories = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    content:
      "My grandmother’s kitchen in Hobart always smelled of warm bread. I think it was the late 1960s.",
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    content:
      "We walked down to the harbour on Sunday mornings. My brother counted the fishing boats.",
  },
];
const draft = {
  preview: {
    title: "The kitchen by the harbour",
    text: "My grandmother’s kitchen in Hobart always smelled of warm bread. In my memory, it is the late 1960s.\n\nOn Sunday mornings, we walked down to the harbour. My brother counted the fishing boats.",
    source_ids: [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ],
  },
  revision: 1,
  updating: false,
  milestone: 5,
  status: "saved",
};
let turns = 0;
/** Only synthetic data; deliberately distinct from acceptance against a real provider. */
export const fixtureFetch: FetchTransport = async (url, init) => {
  const u = new URL(url);
  const p = u.pathname.replace("/api/v1/memoir", "");
  let data: unknown = {};
  if (p === "/agent/config")
    data = {
      enabled: true,
      auth_mode: "fixture",
      supabase_url: null,
      supabase_publishable_key: null,
    };
  else if (p === "/agent/profile")
    data = { name: "Alex", preferred_language: "en-AU" };
  else if (p === "/user/profile")
    data = {
      name: "Alex",
      memory_places: [
        {
          place: "Hobart",
          period: "Late 1960s",
          life_stage: "childhood",
          latitude: -42.88,
          longitude: 147.32,
        },
      ],
      preferred_language: "en-AU",
    };
  else if (p === "/user/projects")
    data = {
      schema_version: 1,
      items: [
        {
          project_id: fixtureProject,
          source_sequence: "12345678901234567890",
          event_sequence: "0",
          policy_epoch: "1",
        },
      ],
      next_after_project_id: null,
    };
  else if (p.includes("/sources/"))
    data = {
      schema_version: 1,
      id: p.split("/").pop(),
      project_id: fixtureProject,
      version: "1",
      sequence: "1",
      text: fixtureMemories[0]!.content,
      source_kind: "narrator_chat",
      status: "active",
      language: "en-AU",
      created_at: "2026-10-01T00:00:00Z",
    };
  else if (p.endsWith("/history"))
    data = {
      schema_version: 1,
      policy_epoch: "1",
      project_id: fixtureProject,
      items: [
        {
          server_turn_id: "memory-1",
          kind: "agent",
          source_version: "1",
          source_status: "active",
          client_turn_id: "11111111-1111-4111-8111-111111111111",
          source_id: "11111111-1111-4111-8111-111111111111",
          source_sequence: "1",
          conversation_sequence: "2",
          created_at: "2026-10-01T00:00:00Z",
          narrator_text: fixtureMemories[0]!.content,
          reply: "What do you remember about being in that kitchen with her?",
        },
      ],
      next_cursor: null,
    };
  else if (p === "/story/state")
    data = {
      user_id: fixtureOwner,
      is_anonymous: true,
      rounds_required: 5,
      rounds_completed: 5,
      free_chapter_claimed: false,
      free_chapter_id: null,
      payment_status: "unpaid",
      payment_plan: null,
      book_count: 0,
      payment_features: [],
      family_features_enabled: false,
      free_chapter_available: true,
      next_action: "continue",
      recall_status: recall,
    };
  else if (p === "/story/private-draft" || p === "/story/private-draft/retry")
    data = draft;
  else if (p === "/story/readiness")
    data = {
      project_id: fixtureProject,
      stages: {
        childhood: { word_equivalents: 120, percent: 30, color: "green" },
      },
      heuristic: "narrator_context_volume_v1",
      maximum_percent: 50,
    };
  else if (p.startsWith("/agent/collection/"))
    data =
      init.method === "PUT"
        ? { revision: 2, ...JSON.parse(init.body ?? "{}"), ready: false }
        : {
            revision: 1,
            periods: {},
            ready: false,
            sources: fixtureMemories,
            tasks: [],
          };
  else if (p === "/agent/family-context")
    data = {
      family_features_enabled: true,
      family_context: {
        people: [
          {
            id: "person-1",
            name: "Grandmother",
            relationship: "Grandmother",
            description: "Remembered through the kitchen in Hobart.",
          },
        ],
        revision: 1,
      },
    };
  else if (p === "/story/events")
    data = {
      events: [
        {
          id: "event-1",
          revision: 1,
          date_expression: "Late 1960s",
          title: "Sunday walks in Hobart",
          summary: fixtureMemories[1]!.content,
          source_ids: ["22222222-2222-4222-8222-222222222222"],
        },
      ],
    };
  else if (p === "/agent/turn") {
    const command = JSON.parse(init.body ?? "{}");
    turns++;
    const response = {
      reply:
        "That sounds like a vivid memory. What is one small detail you can still picture?",
      project_id: command.project_id,
      turn_id: command.client_turn_id,
      conversation_saved: true,
      recall_status: { ...recall, rounds_completed: 5 + turns },
    };
    const rows = [
      { type: "started" },
      { type: "text_delta", text: response.reply },
      { type: "reply_complete", data: response },
      { type: "conversation_saved", data: response },
      { type: "result", data: response },
    ];
    return new Response(rows.map((x) => JSON.stringify(x) + "\n").join(""), {
      headers: { "Content-Type": "application/x-ndjson" },
    });
  } else if (p.includes("/photos"))
    data = {
      items: [],
      status: "NO_MATCH",
      searching: false,
      next_cursor: null,
    };
  else
    return new Response(
      JSON.stringify({ detail: "Fixture has no response for this capability" }),
      { status: 501, headers: { "Content-Type": "application/json" } },
    );
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
};
