// Loaded only by the isolated sdk-minimal profile in the benchmark.
export const name = "memoir-benchmark";
export const inject = ["llm", "tools"];

export function apply(ctx, config) {
  const { origin, token, specs, effort } = config;
  if (!/^http:\/\/127\.0\.0\.1:\d+\/[a-f0-9]+$/.test(origin)) {
    throw new Error("Benchmark bridge must be on loopback");
  }

  const post = async (path, body, signal) => {
    const response = await fetch(origin + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify(body),
      redirect: "error",
      signal,
    });
    if (!response.ok) throw new Error("Benchmark bridge returned HTTP " + response.status);
    return response;
  };

  const resolveModel = async (provider, id) => ({
    provider,
    id,
    name: id,
    context: { contextWindow: 131072 },
    reasoning: { efforts: [{ id: effort, name: effort }] },
  });

  ctx.llm.registerAdapter(["memoir-benchmark"], {
    providerInfo: (id) => ({ id, name: id }),
    providerRetryPolicy: () => undefined,
    imageRequestPricing: () => undefined,
    resolveModel,
    async prepareCall(provider, id) {
      return {
        model: await resolveModel(provider, id),
        async *stream(options) {
          const { signal, model, reasoningEffort, messages, tools, sessionId } = options;
          const response = await post("/step", { model, reasoningEffort, messages, tools }, signal);
          let pending = "";
          for await (const data of response.body.pipeThrough(new TextDecoderStream())) {
            pending += data;
            let boundary;
            while ((boundary = pending.indexOf("\n")) >= 0) {
              const chunk = JSON.parse(pending.slice(0, boundary));
              pending = pending.slice(boundary + 1);
              if (chunk.type === "text-delta") {
                // The SDK publishes assistant/message after the step. Time the
                // adapter's text separately and let Memoir's public gate filter it.
                process.stdout.write(JSON.stringify({
                  jsonrpc: "2.0",
                  method: "memoir.delta",
                  params: { sessionId, text: chunk.text },
                }) + "\n");
              }
              yield chunk;
            }
          }
          if (pending) throw new Error("Incomplete benchmark stream");
        },
      };
    },
  });

  for (const { name, description, inputSchema } of specs) {
    ctx.tools.register({
      name,
      description,
      parameters: inputSchema,
      output: {
        schema: { type: "string" },
        render: (_args, value) => [{ type: "text", text: value }],
      },
      async execute(args, { signal, callId }) {
        const response = await post("/tool", { tool: name, arguments: args, callId }, signal);
        return (await response.json()).text;
      },
    });
  }
}
