import OpenAI from "openai";

const PROVIDER = (process.env.LLM_PROVIDER || "openai").toLowerCase();

/**
 * Generate A2UI JSON from a system prompt + user prompt.
 * The provider is selected via LLM_PROVIDER so we can switch OpenAI -> Anthropic
 * later without touching the rest of the app.
 *
 * @returns {Promise<{ json: any, provider: string, model: string }>}
 */
export async function generateA2UI(systemPrompt, userPrompt) {
  if (PROVIDER === "anthropic") {
    return generateWithAnthropic(systemPrompt, userPrompt);
  }
  return generateWithOpenAI(systemPrompt, userPrompt);
}

async function generateWithOpenAI(systemPrompt, userPrompt) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY is not set.");

  const model = process.env.OPENAI_MODEL || "gpt-4o";
  const client = new OpenAI({ apiKey });

  const completion = await client.chat.completions.create({
    model,
    // Force strict JSON output so the response is always parseable.
    response_format: { type: "json_object" },
    temperature: 0.2,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
  });

  const content = completion.choices[0]?.message?.content || "";
  return { json: parseJson(content), provider: "openai", model };
}

/**
 * Placeholder for the future Anthropic path. Set LLM_PROVIDER=anthropic and
 * ANTHROPIC_API_KEY to enable. Uses the Anthropic SDK (default model
 * claude-opus-4-8) — install @anthropic-ai/sdk when you switch.
 */
async function generateWithAnthropic(systemPrompt, userPrompt) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("ANTHROPIC_API_KEY is not set.");

  const model = process.env.ANTHROPIC_MODEL || "claude-opus-4-8";

  // Lazy import so OpenAI-only deployments don't need the package installed.
  const { default: Anthropic } = await import("@anthropic-ai/sdk");
  const client = new Anthropic({ apiKey });

  const message = await client.messages.create({
    model,
    max_tokens: 16000,
    system: systemPrompt,
    messages: [{ role: "user", content: userPrompt }],
  });

  const text = message.content
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("")
    .trim();

  return { json: parseJson(text), provider: "anthropic", model };
}

/**
 * Parse model output into JSON, tolerating accidental code fences or stray text.
 */
function parseJson(text) {
  if (!text) throw new Error("LLM returned empty content.");

  try {
    return JSON.parse(text);
  } catch {
    // Strip ```json fences or extract the first {...} block as a fallback.
    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fenced) {
      try {
        return JSON.parse(fenced[1].trim());
      } catch {
        /* fall through */
      }
    }
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start !== -1 && end > start) {
      return JSON.parse(text.slice(start, end + 1));
    }
    throw new Error("LLM output was not valid JSON.");
  }
}
