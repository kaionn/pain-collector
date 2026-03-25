/**
 * Discord Approve Worker
 *
 * Discord Interactions Endpoint として動作し、
 * Approve ボタンクリック時に GitHub Issue へ /approve コメントを投稿する。
 */

const DISCORD_INTERACTION_PING = 1;
const DISCORD_INTERACTION_COMPONENT = 3;
const DISCORD_RESPONSE_PONG = 1;
const DISCORD_RESPONSE_CHANNEL_MESSAGE = 4;
const DISCORD_RESPONSE_UPDATE_MESSAGE = 7;

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Not Found", { status: 404 });
    }

    const signature = request.headers.get("x-signature-ed25519");
    const timestamp = request.headers.get("x-signature-timestamp");
    const body = await request.text();

    const isValid = await verifySignature(
      signature,
      timestamp,
      body,
      env.DISCORD_PUBLIC_KEY
    );
    if (!isValid) {
      return new Response("Invalid signature", { status: 401 });
    }

    const interaction = JSON.parse(body);

    // PING → PONG
    if (interaction.type === DISCORD_INTERACTION_PING) {
      return jsonResponse({ type: DISCORD_RESPONSE_PONG });
    }

    // ボタンクリック
    if (interaction.type === DISCORD_INTERACTION_COMPONENT) {
      const customId = interaction.data?.custom_id || "";

      if (customId.startsWith("approve:")) {
        const issueNumber = customId.split(":")[1];
        const discordUser = interaction.member?.user?.username || "unknown";

        try {
          await postApproveComment(issueNumber, env.GITHUB_PAT);

          return jsonResponse({
            type: DISCORD_RESPONSE_UPDATE_MESSAGE,
            data: {
              content: `🚀 #${issueNumber} が承認されました！自動実装を開始します（by ${discordUser}）`,
              embeds: interaction.message?.embeds || [],
              components: [],
            },
          });
        } catch (error) {
          return jsonResponse({
            type: DISCORD_RESPONSE_CHANNEL_MESSAGE,
            data: {
              content: `❌ 承認に失敗しました: ${error.message}`,
              flags: 64,
            },
          });
        }
      }

      if (customId.startsWith("reject:")) {
        const issueNumber = customId.split(":")[1];
        const discordUser = interaction.member?.user?.username || "unknown";

        try {
          await closeIssue(issueNumber, env.GITHUB_PAT);

          return jsonResponse({
            type: DISCORD_RESPONSE_UPDATE_MESSAGE,
            data: {
              content: `🗑️ #${issueNumber} は却下されました。Issue をクローズしました（by ${discordUser}）`,
              embeds: interaction.message?.embeds || [],
              components: [],
            },
          });
        } catch (error) {
          return jsonResponse({
            type: DISCORD_RESPONSE_CHANNEL_MESSAGE,
            data: {
              content: `❌ 却下に失敗しました: ${error.message}`,
              flags: 64,
            },
          });
        }
      }
    }

    return jsonResponse({
      type: DISCORD_RESPONSE_CHANNEL_MESSAGE,
      data: { content: "Unknown interaction", flags: 64 },
    });
  },
};

async function postApproveComment(issueNumber, githubPat) {
  const resp = await fetch(
    `https://api.github.com/repos/kaionn/pain-collector/issues/${issueNumber}/comments`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${githubPat}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "discord-approve-worker",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ body: `/approve` }),
    }
  );

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`GitHub API ${resp.status}: ${text.slice(0, 200)}`);
  }
}

async function closeIssue(issueNumber, githubPat) {
  // rejected ラベルを付与
  await fetch(
    `https://api.github.com/repos/kaionn/pain-collector/issues/${issueNumber}/labels`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${githubPat}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "discord-approve-worker",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ labels: ["rejected"] }),
    }
  );

  // Issue をクローズ
  const resp = await fetch(
    `https://api.github.com/repos/kaionn/pain-collector/issues/${issueNumber}`,
    {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${githubPat}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "discord-approve-worker",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ state: "closed" }),
    }
  );

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`GitHub API ${resp.status}: ${text.slice(0, 200)}`);
  }
}

async function verifySignature(signature, timestamp, body, publicKey) {
  if (!signature || !timestamp) return false;
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      hexToUint8Array(publicKey),
      { name: "Ed25519", namedCurve: "Ed25519" },
      false,
      ["verify"]
    );
    const message = new TextEncoder().encode(timestamp + body);
    const sig = hexToUint8Array(signature);
    return await crypto.subtle.verify("Ed25519", key, sig, message);
  } catch {
    return false;
  }
}

function hexToUint8Array(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
  }
  return bytes;
}

function jsonResponse(data) {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
}
