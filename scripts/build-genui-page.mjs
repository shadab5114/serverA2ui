// Build the standalone, shareable versions of the GenUI docs pages.
//
//   npm run docs:genui
//
// Each page has one editable source in "artifact body" form and one generated,
// downloadable file (don't hand-edit the generated ones):
//
//   docs/genui-playground.src.html  ->  docs/genui-playground-architecture.html
//   docs/genui-stack.src.html       ->  docs/genui-stack.html
//
// Artifact-body form means page content only: no <!doctype>, <html>, <head> or
// <body>, because the Artifact host supplies those at publish time. A file
// someone downloads has to carry them itself, so this script hoists <title> and
// the font <link>s into a real <head>, adds the small reset the host was
// providing, and wraps the rest in <body>.
//
// Keeping one source per page means the published page and the downloadable
// file can never drift apart.

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const docs = (name) => join(root, "docs", name);

const PAGES = [
  {
    src: docs("genui-playground.src.html"),
    out: docs("genui-playground-architecture.html"),
    description:
      "System architecture and two-persona user flows for a design-system-grounded generative UI playground.",
  },
  {
    src: docs("genui-stack.src.html"),
    out: docs("genui-stack.html"),
    description:
      "Every runtime entity in the GenUI playground (React client, Python server, external services and data) and how they connect.",
  },
];

// The reset the Artifact host injects, plus the two accessibility defaults a
// standalone file should not ship without.
const RESET = `    html { color-scheme: light dark; }
    body { margin: 0; }
    img { max-width: 100%; }
    [hidden] { display: none !important; }
    *, *::before, *::after { box-sizing: border-box; }
    :where(a):focus-visible, :where(button):focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }`;

async function build({ src, out, description }) {
  const body = await readFile(src, "utf8");

  const title = body.match(/<title>([\s\S]*?)<\/title>/i)?.[1]?.trim();
  if (!title) {
    throw new Error(`No <title> found in ${relative(root, src)}; refusing to build an untitled page.`);
  }

  const links = [...body.matchAll(/<link\b[^>]*>/gi)].map((m) => m[0]);

  const rest = body
    .replace(/<title>[\s\S]*?<\/title>\s*/i, "")
    .replace(/<link\b[^>]*>\s*/gi, "")
    .trimStart();

  const doc = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="${description}">
<title>${title}</title>
${links.join("\n")}
<style>
${RESET}
</style>
</head>
<body>
${rest}
</body>
</html>
`;

  await writeFile(out, doc, "utf8");
  const kb = (doc.length / 1024).toFixed(1);
  console.log(`${relative(root, out)}: ${kb} KB, "${title}", ${links.length} link tags hoisted`);
}

let failed = false;
for (const page of PAGES) {
  try {
    await build(page);
  } catch (err) {
    failed = true;
    console.error(err.message);
  }
}
if (failed) process.exit(1);
