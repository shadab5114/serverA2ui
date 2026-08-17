// Phase 3b — checkpointer selection.
//
// Returns the LangGraph checkpointer that gives the graph its conversation
// memory (keyed by thread_id):
//   - Postgres (durable, survives restarts) when DATABASE_URL is set, or
//   - in-memory MemorySaver (lost on restart) as a fallback.
//
// The Postgres saver needs a one-time .setup() to create its checkpoint tables;
// we run it here so callers just get a ready-to-use checkpointer.

import { MemorySaver } from "@langchain/langgraph";

/**
 * @returns {Promise<{ checkpointer: import("@langchain/langgraph").BaseCheckpointSaver, kind: "postgres"|"memory", detail: string }>}
 */
export async function getCheckpointer() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    return { checkpointer: new MemorySaver(), kind: "memory", detail: "in-memory (no DATABASE_URL)" };
  }

  const { PostgresSaver } = await import("@langchain/langgraph-checkpoint-postgres");
  const saver = PostgresSaver.fromConnString(url);
  await saver.setup(); // create checkpoint tables if they don't exist yet

  // Show host/db without leaking credentials.
  let detail = "postgres";
  try {
    const u = new URL(url);
    detail = `postgres ${u.host}${u.pathname}`;
  } catch {
    /* ignore */
  }
  return { checkpointer: saver, kind: "postgres", detail };
}
