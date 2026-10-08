"""Managed evaluator definitions, staged until the experiment callback exists.

The managed runtime has no application dependencies. It must not substitute a
weaker citation/date validator for the reviewed application evaluator.
"""
from __future__ import annotations

import json
from copy import deepcopy


def application_receipt(case_id, output, *, worker_completed, completed_sources):
    """Build server-owned metadata for a reviewed synthetic timeline case.

    A future callback must obtain completion and coverage from the application,
    never from a model response or an empty database table. This helper neither
    runs that callback nor proves that a worker completed.
    """
    from scripts.issue6_langfuse_publication import build_manifest
    from scripts.issue6_semantic_evaluation import score_events

    manifest = build_manifest()
    item = next(item for dataset in manifest["datasets"] for item in dataset["items"]
                if item["metadata"]["case_id"] == case_id)
    if item["input"].get("mode") != "timeline":
        raise ValueError("Application score receipts require a reviewed timeline case.")
    inputs = item["input"]
    originals = [*inputs.get("context_sources", []), *inputs["sources"]]
    complete = worker_completed is True and completed_sources == {s["id"]: s["version"] for s in originals}
    scores = score_events(inputs, output if complete else None, item["expectedOutput"])
    return deepcopy({"protocol_version": 1, "worker_completed": complete,
                     "completed_sources": completed_sources, "item_metadata": item["metadata"],
                     "input": inputs, "output": output, "expected_output": item["expectedOutput"],
                     "scores": scores})


def evaluator_definitions():
    from scripts.issue6_langfuse_publication import PREFIX, DATASET_SHA256, EVALUATOR_SHA256, VALIDATOR_SHA256, STAGES_SHA256

    result = []
    dimensions = {
        "event-grounding": ["schema_and_original_evidence", "event_count", "expected_placement", "factual_entailment"],
        "temporal-placement": ["schema_and_original_evidence", "event_count", "expected_placement", "factual_entailment"],
        "chapter-continuity": ["factual_entailment", "meaningful_chapter_transitions", "chronology", "adult_prose_and_locale"],
        "bilingual-consistency": ["cross_language_factual_equivalence", "natural_language_quality"],
    }
    for dimension, names in dimensions.items():
        source = "function evaluate(ctx) {\n"
        source += "  const names = " + json.dumps(names) + ";\n"
        source += "  const dimension = " + json.dumps(dimension) + ";\n"
        source += "  const datasetHash = " + json.dumps(DATASET_SHA256) + ";\n"
        source += "  const evaluatorHash = " + json.dumps(EVALUATOR_SHA256) + ";\n"
        source += "  const validatorHash = " + json.dumps(VALIDATOR_SHA256) + ";\n"
        source += "  const stagesHash = " + json.dumps(STAGES_SHA256) + ";\n"
        source += r'''
  const text = (name, value, comment) => ({name, value, dataType: 'TEXT', comment});
  const unavailable = () => ({scores: names.map(name => text(name, 'unavailable', 'Missing, incomplete or stale application receipt. No semantic acceptance.'))});
  const observation = ctx?.observation;
  const experiment = ctx?.experiment;
  const item = experiment?.itemMetadata;
  if (observation?.output == null || !item || item.synthetic !== true ||
      item.contains_customer_data !== false || item.dimension !== dimension ||
      item.dataset_content_hash !== datasetHash || item.application_evaluator_sha256 !== evaluatorHash ||
      item.application_validator_sha256 !== validatorHash || item.stage_vocabulary_sha256 !== stagesHash) {
    return unavailable();
  }
  if (dimension === 'chapter-continuity' || dimension === 'bilingual-consistency') {
    return {scores: names.map(name => text(name, 'human_review_required', 'Proposed rubric remains uncalibrated. No automatic semantic score.'))};
  }
  // Compare JSON values, ignoring object key order but preserving array order.
  const stable = value => {
    if (Array.isArray(value)) return value.map(stable);
    if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, stable(value[k])]));
    return value;
  };
  const equal = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
  const receipt = observation.metadata?.issue6_application_receipt;
  if (!receipt || receipt.protocol_version !== 1 || receipt.worker_completed !== true) return unavailable();
  const sources = observation.input?.sources;
  const contextSources = observation.input?.context_sources ?? [];
  if (!Array.isArray(sources) || !Array.isArray(contextSources)) return unavailable();
  const originals = [...contextSources, ...sources];
  if (originals.some(s => !s || typeof s !== 'object' || typeof s.id !== 'string' || !s.id ||
      !Number.isInteger(s.version) || s.version < 1)) return unavailable();
  const coverage = Object.fromEntries(originals.map(s => [s.id, s.version]));
  if (!equal(receipt.completed_sources, coverage) || !equal(receipt.item_metadata, item) ||
      !equal(receipt.input, observation.input) || !equal(receipt.output, observation.output) ||
      !equal(receipt.expected_output, experiment.itemExpectedOutput)) return unavailable();
  const scores = names.map(name => {
    const score = receipt.scores?.[name];
    if (name === 'factual_entailment') return text(name, 'human_review_required', 'Valid original citations do not prove factual entailment.');
    if (score?.value === null && score.status === 'not_applicable') return text(name, 'not_applicable', 'No expected event placement for this item.');
    if (!score || ![0, 1].includes(score.value) || !['pass', 'fail', 'scored'].includes(score.status)) return text(name, 'unavailable', 'Missing or malformed application score.');
    return {name, value: score.value, dataType: 'NUMERIC', comment: 'Reviewed application validator score; not semantic acceptance.'};
  });
  return {scores};
}
'''
        result.append({"name": PREFIX + "evaluators/" + dimension, "type": "code",
                       "sourceCode": source, "sourceCodeLanguage": "TYPESCRIPT"})
    return result
