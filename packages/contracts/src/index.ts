import { z } from "zod";

/** Runtime contracts for the reviewed API seam, not proposed future APIs. */
export const LocaleSchema = z.enum(["en-AU", "zh-CN"]);
export type Locale = z.infer<typeof LocaleSchema>;
export const LIFE_STAGES = [
  "baby",
  "toddler",
  "childhood",
  "adolescence",
  "young_adulthood",
  "midlife",
  "later_life",
] as const;
export const LifeStageSchema = z.enum(LIFE_STAGES);
export type LifeStage = z.infer<typeof LifeStageSchema>;
export const ProjectIdSchema = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/);
export const SafeIntegerSchema = z
  .number()
  .int()
  .min(0)
  .max(Number.MAX_SAFE_INTEGER);
export const DecimalSequenceSchema = z
  .union([z.string().regex(/^\d+$/), SafeIntegerSchema])
  .transform((value) => String(value).replace(/^0+(?=\d)/, ""));
export const RecordSchema = z.record(z.string(), z.unknown());
const optionalRecord = RecordSchema.nullish();
export const TurnInputSchema = z.object({
  text: z.string().min(1).max(100000),
  client_turn_id: z.uuid().nullish(),
  conversation_text: z.string().min(1).max(100000).nullish(),
  source_kind: z.enum(["narrator_chat", "narrator_transcript"]).optional(),
  project_id: ProjectIdSchema.nullish(),
  language: LocaleSchema.nullish(),
  first_reply_localization: z.boolean().optional(),
});
export type TurnInput = z.infer<typeof TurnInputSchema>;
export const GreetingInputSchema = z.object({
  action: z.enum(["begin", "continue"]),
  client_turn_id: z.uuid().nullish(),
  project_id: ProjectIdSchema.nullish(),
  language: LocaleSchema.nullish(),
  first_reply_localization: z.boolean().optional(),
});
export type GreetingInput = z.infer<typeof GreetingInputSchema>;
export const ProfileSettingsInputSchema = z.object({
  preferred_language: LocaleSchema.nullish(),
  name: z.string().max(120).nullish(),
  birth_year: z
    .number()
    .int()
    .min(1800)
    .refine(
      (value) => value <= new Date().getUTCFullYear(),
      "Birth year cannot be in the future",
    )
    .nullish(),
  birth_place: z.string().max(160).nullish(),
  childhood_place: z.string().max(160).nullish(),
});
export type ProfileSettingsInput = z.infer<typeof ProfileSettingsInputSchema>;
export const ProfileSettingsSchema = ProfileSettingsInputSchema.extend({
  preferred_language: z.string().nullish(),
  conversation_language: z.union([z.string(), RecordSchema]).nullish(),
}).passthrough();
export const RecallStatusSchema = z
  .object({
    rounds_completed: SafeIntegerSchema,
    free_rounds: SafeIntegerSchema,
    payment_required: z.boolean(),
    paid: z.boolean(),
  })
  .passthrough();
export type RecallStatus = z.infer<typeof RecallStatusSchema>;
export const AgentConfigSchema = z
  .object({
    enabled: z.boolean(),
    auth_mode: z.string(),
    supabase_url: z.string().nullish(),
    supabase_publishable_key: z.string().nullish(),
    show_thinking_steps: z.boolean().optional(),
    free_recall_rounds: SafeIntegerSchema.optional(),
    private_draft_cadence: SafeIntegerSchema.optional(),
  })
  .passthrough();
export type AgentConfig = z.infer<typeof AgentConfigSchema>;
export const ProgressStepSchema = z
  .object({
    id: z.string(),
    kind: z.string().optional(),
    label: z.string().optional(),
    detail: z.string().optional(),
    status: z.string(),
    skill: z.string().optional(),
  })
  .passthrough();
export type ProgressStep = z.infer<typeof ProgressStepSchema>;
export const TurnResultSchema = z
  .object({
    project_id: z.string().nullish(),
    turn_id: z.string().optional(),
    thread_id: z.string().nullish(),
    reply: z.string().nullable(),
    conversation_saved: z.boolean().optional(),
    cached: z.boolean().optional(),
    accepted_source_id: z.string().nullish(),
    source_sequence: DecimalSequenceSchema.optional(),
    recall_status: RecallStatusSchema.nullish(),
    profile_updates: optionalRecord,
    family_context: optionalRecord,
    family_context_update: optionalRecord,
    family_features_enabled: z.boolean().optional(),
    place_journey: optionalRecord,
    place_journey_change: optionalRecord,
    place_journeys: z.array(RecordSchema).optional(),
    tasks: z.array(RecordSchema).optional(),
    task_errors: z.array(RecordSchema).optional(),
    trace: z.array(ProgressStepSchema).optional(),
  })
  .passthrough();
export type TurnResult = z.infer<typeof TurnResultSchema>;
const ContextDataSchema = z
  .object({
    turn_id: z.string().optional(),
    project_id: z.string().nullish(),
    source_sequence: DecimalSequenceSchema.optional(),
  })
  .passthrough();
const ReplyDataSchema = ContextDataSchema.extend({
  reply: z.string(),
  thread_id: z.string().nullish(),
});
const SavedDataSchema = ReplyDataSchema.extend({
  conversation_saved: z.literal(true),
  recall_status: RecallStatusSchema.nullish(),
  profile_updates: optionalRecord,
});
const WorkspaceDataSchema = ContextDataSchema.extend({
  workspace_status: z.string().optional(),
  stage_readiness: optionalRecord,
});
export const KnownTurnEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("started") }).passthrough(),
  z.object({ type: z.literal("heartbeat") }).passthrough(),
  z.object({ type: z.literal("text_delta"), text: z.string() }).passthrough(),
  z
    .object({
      type: z.literal("progress"),
      turn_id: z.string().optional(),
      project_id: z.string().nullish(),
      data: ProgressStepSchema,
    })
    .passthrough(),
  z
    .object({ type: z.literal("reply_complete"), data: ReplyDataSchema })
    .passthrough(),
  z
    .object({ type: z.literal("conversation_saved"), data: SavedDataSchema })
    .passthrough(),
  z
    .object({ type: z.literal("place_preview"), data: ContextDataSchema })
    .passthrough(),
  z
    .object({ type: z.literal("workspace_update"), data: WorkspaceDataSchema })
    .passthrough(),
  z
    .object({ type: z.literal("workspace_error"), data: ContextDataSchema })
    .passthrough(),
  z.object({ type: z.literal("result"), data: TurnResultSchema }).passthrough(),
  z
    .object({
      type: z.literal("error"),
      message: z.string(),
      code: z.string().optional(),
      retryable: z.boolean().optional(),
      request_id: z.string().optional(),
    })
    .passthrough(),
]);
export type KnownTurnEvent = z.infer<typeof KnownTurnEventSchema>;
export type TurnEvent =
  KnownTurnEvent | { type: "unknown"; event_type: string };
const knownTypes = new Set([
  "started",
  "heartbeat",
  "text_delta",
  "progress",
  "reply_complete",
  "conversation_saved",
  "place_preview",
  "workspace_update",
  "workspace_error",
  "result",
  "error",
]);
export function parseTurnEvent(value: unknown): TurnEvent {
  const header = z.object({ type: z.string().min(1) }).parse(value);
  return knownTypes.has(header.type)
    ? KnownTurnEventSchema.parse(value)
    : { type: "unknown", event_type: header.type };
}
export const ApiErrorEnvelopeSchema = z
  .object({
    error: z
      .object({
        code: z.string(),
        message: z.string(),
        retryable: z.boolean(),
        request_id: z.string().optional(),
        message_key: z.string().optional(),
        field_errors: z.array(z.unknown()).optional(),
      })
      .passthrough(),
    detail: z.unknown().optional(),
  })
  .passthrough();
export const TurnReceiptSchema = z
  .object({
    schema_version: z.literal(1),
    client_turn_id: z.uuid(),
    project_id: ProjectIdSchema,
    state: z.enum(["not_found", "source_accepted", "conversation_saved"]),
    conversation_saved: z.boolean(),
    server_turn_id: z.string().nullable(),
    source_id: z.string().nullable(),
    source_version: DecimalSequenceSchema.nullable(),
    source_sequence: DecimalSequenceSchema.nullable(),
    conversation_sequence: DecimalSequenceSchema.nullable(),
    project_ordinal: DecimalSequenceSchema.nullable(),
    narrator_text: z.string().nullable(),
    reply: z.string().nullable(),
    source_status: z.string().nullable(),
    source_processing_state: z.string().nullable(),
    enrichment_state: z.string(),
    recall_status: RecallStatusSchema,
  })
  .passthrough()
  .superRefine((value, ctx) => {
    if (value.conversation_saved !== (value.state === "conversation_saved"))
      ctx.addIssue({
        code: "custom",
        message: "Receipt commit state is inconsistent",
      });
    if (value.conversation_saved && !value.server_turn_id)
      ctx.addIssue({
        code: "custom",
        message: "Committed receipt requires a saved exchange ID",
      });
  });
export type TurnReceipt = z.infer<typeof TurnReceiptSchema>;
export const ConversationMessageSchema = z
  .object({ role: z.enum(["user", "assistant"]), text: z.string().max(100000) })
  .passthrough();
export const ConversationsSchema = z
  .object({
    items: z.array(
      z
        .object({
          id: z.string(),
          project_id: z.string(),
          messages: z.array(ConversationMessageSchema),
          workspace: RecordSchema,
          created_at: z.string().nullable(),
        })
        .passthrough(),
    ),
  })
  .passthrough();
export type Conversations = z.infer<typeof ConversationsSchema>;
export const StoryStateSchema = z
  .object({
    user_id: z.string(),
    is_anonymous: z.boolean(),
    rounds_required: SafeIntegerSchema,
    rounds_completed: SafeIntegerSchema,
    free_chapter_claimed: z.boolean(),
    free_chapter_id: z.string().nullable(),
    payment_status: z.string(),
    payment_plan: z.string().nullable(),
    book_count: SafeIntegerSchema,
    payment_features: z.array(z.string()),
    family_features_enabled: z.boolean(),
    free_chapter_available: z.boolean(),
    next_action: z.string(),
    recall_status: RecallStatusSchema.nullish(),
  })
  .passthrough();
export type StoryState = z.infer<typeof StoryStateSchema>;
export const StageReadinessSchema = z
  .object({
    word_equivalents: SafeIntegerSchema,
    percent: z.number().min(0).max(100),
    color: z.string(),
  })
  .passthrough();
export const ReadinessSchema = z
  .object({
    project_id: z.string(),
    stages: z.record(z.string(), StageReadinessSchema),
    heuristic: z.string(),
    maximum_percent: z.number(),
  })
  .passthrough();
export type Readiness = z.infer<typeof ReadinessSchema>;
export const PrivateDraftSchema = z
  .object({
    preview: z
      .object({ title: z.string(), text: z.string() })
      .passthrough()
      .nullable(),
    updating: z.boolean().optional(),
    error: z.unknown().optional(),
    revision: SafeIntegerSchema.optional(),
    milestone: SafeIntegerSchema.optional(),
    covered_round: SafeIntegerSchema.optional(),
    status: z.string().optional(),
  })
  .passthrough();
export type PrivateDraft = z.infer<typeof PrivateDraftSchema>;
export const PreviewInputSchema = z.object({
  project_id: ProjectIdSchema.refine((value) => value.length <= 100),
  language: LocaleSchema.nullish(),
});
export const PeriodCoverageSchema = z
  .object({
    status: z.enum(["recorded", "skipped", "not_applicable"]),
    memory_ids: z.array(z.string()).max(1000).default([]),
    note: z.string().max(500).default(""),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.status === "recorded" && !value.memory_ids.length)
      ctx.addIssue({
        code: "custom",
        message: "A recorded period requires saved memories",
      });
    if (value.status !== "recorded" && !value.note.trim())
      ctx.addIssue({
        code: "custom",
        message: "Explain a skipped or inapplicable period",
      });
  });
export type PeriodCoverage = z.infer<typeof PeriodCoverageSchema>;
export const CollectionUpdateSchema = z
  .object({
    expected_revision: SafeIntegerSchema,
    periods: z.record(z.string(), PeriodCoverageSchema),
    confirm_ready: z.boolean().optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (
      Object.keys(value.periods).some(
        (key) => !LIFE_STAGES.includes(key as LifeStage),
      )
    )
      ctx.addIssue({ code: "custom", message: "Unknown life stage" });
    if (
      value.confirm_ready &&
      (LIFE_STAGES.some((key) => !value.periods[key]) ||
        !Object.values(value.periods).some(
          (period) => period.status === "recorded",
        ))
    )
      ctx.addIssue({
        code: "custom",
        message: "Review all stages and record at least one before confirming",
      });
  });
export type CollectionUpdate = z.infer<typeof CollectionUpdateSchema>;
export const TaskSchema = z
  .object({
    id: z.string(),
    kind: z.string(),
    status: z.string(),
    result: optionalRecord,
  })
  .passthrough();
export type MemoirTask = z.infer<typeof TaskSchema>;
export const CollectionSchema = z
  .object({
    revision: SafeIntegerSchema,
    periods: z.record(z.string(), PeriodCoverageSchema),
    ready: z.boolean(),
    sources: z
      .array(z.object({ id: z.string(), content: z.string() }).passthrough())
      .optional(),
    tasks: z.array(TaskSchema).optional(),
    source_fingerprint: z.string().optional(),
  })
  .passthrough();
export type Collection = z.infer<typeof CollectionSchema>;
export const OrganiseInputSchema = z.object({
  expected_revision: SafeIntegerSchema.refine((value) => value >= 1),
  language: LocaleSchema.optional(),
});
export const CollectionTaskInputSchema = z
  .object({
    kind: z.enum(["BuildFreePreview", "BuildSourceExport"]),
    memory_ids: z.array(z.string()).min(1).max(1000),
    title: z.string().min(1).max(200).optional(),
  })
  .strict();
export const TranscriptionInputSchema = z.object({
  audio_base64: z.string().min(1),
  filename: z.string().optional(),
  mime_type: z.string().optional(),
  language: z.string().nullish(),
  prompt: z.string().nullish(),
});
export type TranscriptionInput = z.infer<typeof TranscriptionInputSchema>;
export const TranscriptionSchema = z
  .object({
    text: z.string(),
    source: z
      .object({
        source_kind: z.literal("transcript"),
        transcription_method: z.string(),
        transcription_model: z.string().nullable(),
        language: z.string().nullable(),
        segments: z.array(z.unknown()),
      })
      .passthrough(),
  })
  .passthrough();
export type Transcription = z.infer<typeof TranscriptionSchema>;
export const SpeechInputSchema = z.object({
  text: z.string().min(1).max(4096),
  language: z.string().nullish(),
  voice: z.string().optional(),
  instructions: z.string().optional(),
  output_format: z.string().optional(),
});
export const SpeechSchema = z
  .object({
    audio_base64: z.string(),
    mime_type: z.string(),
    model: z.string().nullable(),
    voice: z.string(),
    ai_generated: z.literal(true),
    cached: z.boolean(),
  })
  .passthrough();
export const TransferInputSchema = z.object({
  token: z.string().regex(/^[a-f0-9]{64}$/),
  project_id: z.string().min(1).max(128),
  messages: z.array(ConversationMessageSchema).max(1000),
  workspace_profile: RecordSchema.optional(),
  ui_locale: LocaleSchema.nullish(),
});
export type TransferInput = z.infer<typeof TransferInputSchema>;
export const TransferAttachInputSchema = z.object({
  token: z.string().regex(/^[a-f0-9]{64}$/),
  guest_wins: z.boolean().optional(),
});
export const EventCorrectionSchema = z.object({
  expected_revision: SafeIntegerSchema.refine((value) => value >= 1),
  patch: RecordSchema,
  statement: z.string().min(1).max(2000),
});
export const ProjectSchema = z
  .object({
    project_id: ProjectIdSchema,
    source_sequence: DecimalSequenceSchema,
    event_sequence: DecimalSequenceSchema,
    policy_epoch: DecimalSequenceSchema,
  })
  .passthrough();
export type MemoirProject = z.infer<typeof ProjectSchema>;
export const ProjectsSchema = z
  .object({
    schema_version: z.literal(1),
    items: z.array(ProjectSchema),
    next_after_project_id: z.string().nullable(),
  })
  .passthrough();
export type Projects = z.infer<typeof ProjectsSchema>;
export const HistoryItemSchema = z
  .object({
    server_turn_id: z.string(),
    client_turn_id: z.string().nullable(),
    kind: z.string(),
    created_at: z.string(),
    source_sequence: DecimalSequenceSchema.nullable(),
    conversation_sequence: DecimalSequenceSchema.nullable(),
    source_id: z.string().nullable(),
    source_version: DecimalSequenceSchema.nullable(),
    source_status: z.string().nullable(),
    narrator_text: z.string().nullable(),
    reply: z.string().nullable(),
  })
  .passthrough();
export type HistoryItem = z.infer<typeof HistoryItemSchema>;
export const HistorySchema = z
  .object({
    schema_version: z.literal(1),
    project_id: ProjectIdSchema,
    policy_epoch: DecimalSequenceSchema,
    items: z.array(HistoryItemSchema),
    next_cursor: z.string().nullable(),
  })
  .passthrough();
export type ProjectHistory = z.infer<typeof HistorySchema>;
/** Photo provenance is server-owned. Preserve v8 fallback and rights metadata. */
export const PlacePhotoSchema = z
  .object({
    id: z.string().optional(),
    asset_id: z.string().optional(),
    title: z.string().optional(),
    url: z.string().optional(),
    image_url: z.string().optional(),
    thumbnail_url: z.string().optional(),
    source_url: z.string().optional(),
    search_fallback: z.string().optional(),
    requested_period: z.string().optional(),
    search_place: z.string().optional(),
    location_evidence: z.string().optional(),
    date_expression: z.string().optional(),
    date_basis: z.string().optional(),
    latitude: z.number().nullable().optional(),
    longitude: z.number().nullable().optional(),
    license: z.string().optional(),
    attribution: z.string().optional(),
  })
  .passthrough();
export type PlacePhoto = z.infer<typeof PlacePhotoSchema>;
export const PhotoPageSchema = z
  .object({
    items: z.array(PlacePhotoSchema),
    status: z.string(),
    searching: z.boolean(),
    count: SafeIntegerSchema.optional(),
    target_count: SafeIntegerSchema.optional(),
    shortfall: SafeIntegerSchema.optional(),
    next_cursor: z.string().nullable().optional(),
    search_center: RecordSchema.nullable().optional(),
    failures: z.array(z.unknown()).optional(),
  })
  .passthrough();
export type PhotoPage = z.infer<typeof PhotoPageSchema>;
export const NarratorSourceDetailSchema = z
  .object({
    schema_version: z.literal(1),
    id: z.uuid(),
    project_id: ProjectIdSchema,
    version: DecimalSequenceSchema,
    sequence: DecimalSequenceSchema,
    text: z.string(),
    source_kind: z.string(),
    status: z.literal("active"),
    language: z.string(),
    created_at: z.string(),
  })
  .passthrough();
export type NarratorSourceDetail = z.infer<typeof NarratorSourceDetailSchema>;
