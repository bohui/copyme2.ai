#!/usr/bin/env node

const url = process.argv[2] ?? "ws://127.0.0.1:8765";
const command = process.argv[3] ?? "printf 'memory-spark-harness-ready\\n'";
const defaultSmokeCommand = "printf 'memory-spark-harness-ready\\n'";
const timeoutMs = Number(process.env.CODEX_HARNESS_TIMEOUT_MS ?? 30_000);

const socket = new WebSocket(url);
let nextId = 1;
const pendingMessages = [];
const incomingMessages = [];
const waitingReaders = [];

socket.addEventListener("message", (event) => {
  let message;
  try {
    message = JSON.parse(event.data);
  } catch (error) {
    message = { parseError: new Error(`Codex harness returned invalid JSON: ${error.message}`) };
  }

  const reader = waitingReaders.shift();
  if (reader) {
    clearTimeout(reader.timer);
    if (message.parseError) {
      reader.reject(message.parseError);
    } else {
      reader.resolve(message);
    }
  } else {
    incomingMessages.push(message);
  }
});

function closeSocket() {
  if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
    socket.close();
  }
}

function readMessage() {
  if (incomingMessages.length > 0) {
    const message = incomingMessages.shift();
    if (message.parseError) {
      return Promise.reject(message.parseError);
    }
    return Promise.resolve(message);
  }

  return new Promise((resolve, reject) => {
    const reader = { resolve, reject, timer: null };
    reader.timer = setTimeout(() => {
      const index = waitingReaders.indexOf(reader);
      if (index >= 0) {
        waitingReaders.splice(index, 1);
      }
      reject(new Error(`timed out waiting for a message from ${url}`));
    }, timeoutMs);
    waitingReaders.push(reader);
  });
}

function nextMessage() {
  if (pendingMessages.length > 0) {
    return Promise.resolve(pendingMessages.shift());
  }
  return readMessage();
}

async function request(method, params) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));

  while (true) {
    const message = await readMessage();
    if (message.id === id) {
      if (message.error) {
        throw new Error(`${method} failed: ${JSON.stringify(message.error)}`);
      }
      return message.result;
    }
    pendingMessages.push(message);
  }
}

try {
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", () => reject(new Error(`could not connect to ${url}`)), { once: true });
  });

  const initialized = await request("initialize", { clientName: "memory-spark-container-smoke" });
  if (!initialized?.sessionId || !initialized?.environmentInfo?.cwd) {
    throw new Error(`initialize returned an incomplete result: ${JSON.stringify(initialized)}`);
  }

  socket.send(JSON.stringify({ method: "initialized", params: {} }));

  const processId = `memory-spark-smoke-${Date.now()}`;
  const started = await request("process/start", {
    processId,
    argv: ["sh", "-lc", command],
    cwd: "file:///workspace",
    env: { PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" },
    tty: true,
    pipeStdin: false,
    arg0: null,
  });
  if (started?.processId !== processId) {
    throw new Error(`process/start returned an unexpected process: ${JSON.stringify(started)}`);
  }

  let output = "";
  let exited = false;
  let closed = false;
  // The server may deliver process/closed before process/exited. Keep reading
  // until both lifecycle events have been observed so a valid command is not
  // reported as failed just because those notifications crossed in flight.
  while (!closed || !exited) {
    const message = await nextMessage();
    if (message.method === "process/output" && message.params?.processId === processId) {
      output += Buffer.from(message.params.chunk, "base64").toString("utf8");
      continue;
    }
    if (message.method === "process/exited" && message.params?.processId === processId) {
      exited = true;
      if (message.params.exitCode !== 0) {
        throw new Error(`harness process exited with ${message.params.exitCode}: ${output}`);
      }
    }
    if (message.method === "process/closed" && message.params?.processId === processId) {
      closed = true;
    }
  }

  const normalisedOutput = output.replaceAll("\r\n", "\n").replaceAll("\r", "\n");
  const smokeOutput = normalisedOutput.replace(/\u001b\[[0-9;?]*[ -\/]*[@-~]/g, "").trim();
  if (!exited || (command === defaultSmokeCommand && smokeOutput !== "memory-spark-harness-ready")) {
    throw new Error(`unexpected smoke output: ${JSON.stringify(output)}`);
  }

  if (command !== defaultSmokeCommand) {
    process.stdout.write(normalisedOutput);
  }
  console.log(`Codex exec-server: healthy (${initialized.environmentInfo.cwd})`);
} catch (error) {
  console.error(`Codex harness check failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  closeSocket();
}
