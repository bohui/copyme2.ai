const timeout = setTimeout(() => process.exit(1), 2500);
const socket = new WebSocket("ws://127.0.0.1:8765");

socket.addEventListener("open", () => {
  clearTimeout(timeout);
  socket.close();
  process.exit(0);
});

socket.addEventListener("error", () => {
  clearTimeout(timeout);
  process.exit(1);
});
