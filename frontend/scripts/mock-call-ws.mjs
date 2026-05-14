/**
 * Minimal mock WebSocket server (Node stdlib only — no `ws` package).
 * Implements enough of RFC 6455 for browser clients sending JSON text frames.
 *
 * Run: npm run mock:call-ws
 * Frontend default: ws://localhost:8001/ws
 *
 * In Vite dev, the app auto-plays a short WAV when it receives `complete`
 * (mock “professor reply” UI/audio). Override with VITE_MOCK_PLAYBACK_URL or
 * set VITE_MOCK_PLAYBACK=false in `.env` to disable that behavior.
 */
import crypto from "crypto";
import http from "http";

const PORT = Number(process.env.MOCK_CALL_PORT || 8001);
const WS_PATH = process.env.MOCK_CALL_PATH || "/ws";
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

function sendWsText(socket, text) {
  const payload = Buffer.from(text, "utf8");
  let header;
  if (payload.length < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81;
    header[1] = payload.length;
  } else if (payload.length < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(payload.length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeUInt32BE(0, 2);
    header.writeUInt32BE(payload.length, 6);
  }
  socket.write(Buffer.concat([header, payload]));
}

/**
 * @returns {number} total bytes consumed from `buf`, or 0 if incomplete
 */
function consumeOneWsFrame(buf, socket, onTextPayload) {
  if (buf.length < 2) return 0;

  const fin = (buf[0] & 0x80) !== 0;
  const opcode = buf[0] & 0x0f;
  const masked = (buf[1] & 0x80) !== 0;
  let len = buf[1] & 0x7f;
  let offset = 2;

  if (len === 126) {
    if (buf.length < 4) return 0;
    len = buf.readUInt16BE(2);
    offset = 4;
  } else if (len === 127) {
    if (buf.length < 10) return 0;
    const high = buf.readUInt32BE(2);
    if (high !== 0) {
      throw new Error("Frame too large");
    }
    len = buf.readUInt32BE(6);
    offset = 10;
  }

  let maskKey = null;
  if (masked) {
    if (buf.length < offset + 4) return 0;
    maskKey = buf.subarray(offset, offset + 4);
    offset += 4;
  }

  if (buf.length < offset + len) return 0;

  let payload = buf.subarray(offset, offset + len);
  if (masked && maskKey) {
    const out = Buffer.from(payload);
    for (let i = 0; i < out.length; i += 1) {
      out[i] ^= maskKey[i % 4];
    }
    payload = out;
  }

  const total = offset + len;

  if (opcode === 0x8) {
    socket.end();
    return total;
  }

  if (opcode === 0x9) {
    const pongHeader = Buffer.alloc(2);
    pongHeader[0] = 0x8a;
    pongHeader[1] = payload.length;
    socket.write(Buffer.concat([pongHeader, payload]));
    return total;
  }

  if (opcode === 0x1 && fin) {
    onTextPayload(payload);
  } else if (opcode === 0x1 && !fin) {
    console.warn("[mock] fragmented text frame — not handled; increase chunk size or extend parser");
  } else if (opcode === 0x2 && fin) {
    console.log("[mock] binary frame from client, bytes=", payload.length);
  }

  return total;
}

const server = http.createServer((_req, res) => {
  res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("DigitalTwins mock call WS — use WebSocket at /ws\n");
});

server.on("upgrade", (req, socket, _head) => {
  try {
    const host = req.headers.host || `localhost:${PORT}`;
    const url = new URL(req.url || "/", `http://${host}`);
    if (url.pathname !== WS_PATH) {
      socket.destroy();
      return;
    }

    const key = req.headers["sec-websocket-key"];
    if (typeof key !== "string") {
      socket.destroy();
      return;
    }

    const accept = crypto.createHash("sha1").update(key + WS_GUID).digest("base64");
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\n" +
        "Upgrade: websocket\r\n" +
        "Connection: Upgrade\r\n" +
        `Sec-WebSocket-Accept: ${accept}\r\n` +
        "\r\n"
    );

    let buffer = Buffer.alloc(0);
    let chunkCount = 0;
    let decodedBytes = 0;

    const handlePayload = (payload) => {
      let msg;
      try {
        msg = JSON.parse(payload.toString("utf8"));
      } catch {
        console.log("[mock] non-JSON:", payload.toString("utf8").slice(0, 120));
        return;
      }

      if (msg.type === "init") {
        console.log("[mock] init speaker=", msg.speaker);
        return;
      }
      if (msg.type === "audio_chunk") {
        chunkCount += 1;
        const n = msg.data ? Buffer.from(msg.data, "base64").length : 0;
        decodedBytes += n;
        console.log(
          `[mock] audio_chunk #${chunkCount} format=${msg.format ?? "wav"} decodedBytes=${n} (cumulative ${decodedBytes})`
        );
        return;
      }
      if (msg.type === "audio_end") {
        console.log(`[mock] audio_end — ${chunkCount} chunk(s), ${decodedBytes} raw bytes`);
        chunkCount = 0;
        decodedBytes = 0;
        sendWsText(socket, JSON.stringify({ type: "complete" }));
        return;
      }
      if (msg.type === "terminate") {
        console.log("[mock] terminate");
        socket.end();
      }
    };

    socket.on("data", (data) => {
      buffer = Buffer.concat([buffer, data]);
      try {
        while (buffer.length > 0) {
          const used = consumeOneWsFrame(buffer, socket, handlePayload);
          if (used === 0) break;
          buffer = buffer.subarray(used);
        }
      } catch (err) {
        console.error("[mock] frame error:", err);
        socket.destroy();
      }
    });

    socket.on("close", () => console.log("[mock] client disconnected"));
    console.log("[mock] client connected");
  } catch (e) {
    console.error("[mock] upgrade error:", e);
    socket.destroy();
  }
});

server.listen(PORT, () => {
  console.log(`Mock call WebSocket at ws://localhost:${PORT}${WS_PATH}`);
  console.log("Open the app → start call → speak and pause; watch logs for chunks + audio_end.");
});
