const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} = require("@whiskeysockets/baileys");
const pino = require("pino");
const axios = require("axios");
const express = require("express");
const QRCode = require("qrcode");
const fs = require("fs");
const path = require("path");

const API_URL = process.env.WHATSAPP_API_URL || "http://localhost:8000";
const QR_PORT = parseInt(process.env.QR_SERVER_PORT || "3001");
const INBOUND_DEBOUNCE_MS = parseInt(process.env.WHATSAPP_INBOUND_DEBOUNCE_MS || "1500", 10);
const AUTH_DIR = path.join(__dirname, "auth_state");
const logger = pino({ level: "warn" });

let currentQR = null;
let connectionStatus = "disconnected";
let sock = null;
const chatQueues = new Map();
const inboundBuffers = new Map();

// ── QR Code Web Server ──────────────────────────────────────────────
const app = express();

app.get("/", async (req, res) => {
  let qrHtml = '<p style="color:#999;">Aguardando...</p>';
  let statusClass = "waiting";
  let statusText = "Aguardando QR Code...";

  if (connectionStatus === "connected") {
    qrHtml = '<p style="color:#25D366;font-size:3rem;">&#10003;</p><p style="color:#333;">Conectado</p>';
    statusClass = "connected";
    statusText = "Conectado ao WhatsApp!";
  } else if (currentQR) {
    try {
      const qrDataUrl = await QRCode.toDataURL(currentQR, { width: 280 });
      qrHtml = '<img src="' + qrDataUrl + '" alt="QR Code"/>';
      statusClass = "waiting";
      statusText = "Escaneie o QR Code com seu WhatsApp";
    } catch (e) {
      qrHtml = '<p style="color:red;">Erro ao gerar QR</p>';
    }
  }

  res.send(`
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>WhatsApp Agent - QR Code</title>
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0a1628; color: #fff;
               display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .container { text-align: center; padding: 2rem; }
        h1 { font-size: 1.8rem; margin-bottom: 0.5rem; color: #25D366; }
        .subtitle { color: #8899aa; margin-bottom: 2rem; }
        #qr-container { background: #fff; padding: 1.5rem; border-radius: 16px;
                        display: inline-block; margin: 1rem 0; }
        #qr-container img { width: 280px; height: 280px; }
        .status { padding: 0.5rem 1.5rem; border-radius: 20px; display: inline-block;
                  margin-top: 1rem; font-weight: 600; }
        .status.connected { background: #25D366; color: #000; }
        .status.waiting { background: #f59e0b; color: #000; }
        .status.disconnected { background: #ef4444; }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Andrade & Lemos</h1>
        <p class="subtitle">Agente de Atendimento WhatsApp</p>
        <div id="qr-container">${qrHtml}</div>
        <div id="status" class="status ${statusClass}">${statusText}</div>
      </div>
      <script>
        setTimeout(function() { window.location.reload(); }, 3000);
      </script>
    </body>
    </html>
  `);
});

app.get("/status", async (req, res) => {
  if (connectionStatus === "connected") {
    return res.json({ status: "connected" });
  }
  if (currentQR) {
    const qrDataUrl = await QRCode.toDataURL(currentQR, { width: 280 });
    return res.json({ status: "waiting", qr: qrDataUrl });
  }
  res.json({ status: "disconnected" });
});

app.get("/health", (req, res) => {
  res.json({ status: connectionStatus });
});

// ── Send message endpoint (called by FastAPI) ───────────────────────
app.use(express.json());

app.post("/send", async (req, res) => {
  const { phone, message } = req.body;
  if (!sock || connectionStatus !== "connected") {
    return res.status(503).json({ error: "WhatsApp not connected" });
  }
  try {
    const jid = phone.includes("@s.whatsapp.net")
      ? phone
      : `${phone.replace(/\D/g, "")}@s.whatsapp.net`;
    await enqueueChatTask(jid, async () => {
      await sock.sendMessage(jid, { text: message });
    });
    res.json({ success: true, jid });
  } catch (err) {
    console.error("Send error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

app.listen(QR_PORT, () => {
  console.log(`[QR Server] http://localhost:${QR_PORT}`);
  console.log(`[WhatsApp] Forwarding messages to ${API_URL}`);
});

// ── WhatsApp Connection ─────────────────────────────────────────────
async function connectWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger,
    generateHighQualityLinkPreview: false,
  });

  // Connection updates
  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      currentQR = qr;
      connectionStatus = "waiting_qr";
      console.log("[WhatsApp] QR Code generated - scan at http://localhost:" + QR_PORT);
    }

    if (connection === "close") {
      connectionStatus = "disconnected";
      currentQR = null;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log(`[WhatsApp] Disconnected (code: ${statusCode}). Reconnecting: ${shouldReconnect}`);
      if (shouldReconnect) {
        setTimeout(connectWhatsApp, 3000);
      }
    }

    if (connection === "open") {
      connectionStatus = "connected";
      currentQR = null;
      console.log("[WhatsApp] Connected successfully!");
    }
  });

  // Save credentials on update
  sock.ev.on("creds.update", saveCreds);

  // Handle incoming messages
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    const tasks = [];
    for (const msg of messages) {
      if (msg.key.fromMe) continue;
      if (!msg.message) continue;

      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        "";
      if (!text.trim()) continue;

      const sender = msg.key.remoteJid;
      const pushName = msg.pushName || "";

      tasks.push(
        queueInboundMessage({
          sender,
          pushName,
          text,
          messageId: msg.key.id,
          timestamp: msg.messageTimestamp,
        })
      );
    }

    await Promise.allSettled(tasks);
  });
}

function enqueueChatTask(chatId, task) {
  if (!chatId) {
    return Promise.resolve().then(task);
  }

  const previous = chatQueues.get(chatId) || Promise.resolve();
  const next = previous.catch(() => {}).then(task);
  let tracked = null;
  tracked = next.finally(() => {
    if (chatQueues.get(chatId) === tracked) {
      chatQueues.delete(chatId);
    }
  });
  chatQueues.set(chatId, tracked);
  return tracked;
}

function queueInboundMessage({ sender, pushName, text, messageId, timestamp }) {
  if (!sender || !text.trim()) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    const existing = inboundBuffers.get(sender);
    const entry = existing || {
      sender,
      pushName,
      texts: [],
      messageIds: [],
      timestamp,
      resolvers: [],
      timer: null,
    };

    if (entry.timer) {
      clearTimeout(entry.timer);
    }

    entry.pushName = pushName || entry.pushName;
    entry.texts.push(text.trim());
    if (messageId) {
      entry.messageIds.push(messageId);
    }
    if (timestamp) {
      entry.timestamp = timestamp;
    }
    entry.resolvers.push(resolve);
    entry.timer = setTimeout(() => {
      flushInboundMessage(sender).catch((err) => {
        console.error("[Inbound Buffer Error]", err.message);
      });
    }, INBOUND_DEBOUNCE_MS);

    inboundBuffers.set(sender, entry);
  });
}

async function flushInboundMessage(sender) {
  const entry = inboundBuffers.get(sender);
  if (!entry) {
    return;
  }

  inboundBuffers.delete(sender);
  const combinedText = collapseSequentialMessages(entry.texts);
  const messageId = entry.messageIds.filter(Boolean).join(",") || `buffered:${Date.now()}`;

  try {
    await enqueueChatTask(sender, async () => {
      console.log(`[Message] ${entry.pushName} (${sender}): ${combinedText}`);

      await sock.presenceSubscribe(sender);
      await sock.sendPresenceUpdate("composing", sender);

      try {
        const response = await axios.post(
          `${API_URL}/api/v1/message`,
          {
            phone: sender,
            name: entry.pushName,
            text: combinedText,
            message_id: messageId,
            timestamp: entry.timestamp,
          },
          { timeout: 60000 }
        );

        await sock.sendPresenceUpdate("paused", sender);

        if (response.data?.duplicate) {
          return;
        }

        if (response.data?.reply) {
          const replies = splitMessage(response.data.reply);
          for (const part of replies) {
            await sock.sendPresenceUpdate("composing", sender);
            await delay(Math.min(part.length * 30, 3000));
            await sock.sendMessage(sender, { text: part });
            await sock.sendPresenceUpdate("paused", sender);
          }
        }
      } catch (err) {
        const apiDetail =
          err.response?.data?.detail ||
          err.response?.data?.error ||
          err.response?.data ||
          err.message;
        console.error("[API Error]", apiDetail);
        await sock.sendPresenceUpdate("paused", sender);
        await sock.sendMessage(sender, {
          text: "Desculpe, estou com uma instabilidade no momento. Já já te respondo! 😊",
        });
      }
    });
  } finally {
    for (const resolve of entry.resolvers) {
      resolve();
    }
  }
}

function collapseSequentialMessages(messages) {
  const parts = [];
  for (const message of messages) {
    const trimmed = (message || "").trim();
    if (!trimmed) continue;
    if (parts.length && parts[parts.length - 1].toLowerCase() === trimmed.toLowerCase()) {
      continue;
    }
    parts.push(trimmed);
  }
  return parts.join("\n");
}

function splitMessage(text, maxLen = 1200) {
  if (text.length <= maxLen) return [text];
  const parts = [];
  const paragraphs = text.split("\n\n");
  let current = "";
  for (const p of paragraphs) {
    if ((current + "\n\n" + p).length > maxLen && current) {
      parts.push(current.trim());
      current = p;
    } else {
      current = current ? current + "\n\n" + p : p;
    }
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Start
connectWhatsApp().catch(console.error);
