#!/usr/bin/env node
/**
 * Distill a Figma node JSON export into a compact indented tree for LLM use.
 * Handles Figma REST exports ({document} / {nodes:{id:{document}}}) and
 * plugin exports ({tree: <node>} or a bare node).
 *
 * Usage: node distill-figma.mjs <figma-node.json> [--depth N]
 */
import fs from "node:fs";

const file = process.argv[2];
if (!file) {
  console.error("usage: node distill-figma.mjs <figma-node.json> [--depth N]");
  process.exit(1);
}
const di = process.argv.indexOf("--depth");
const maxDepth = di > -1 ? Number(process.argv[di + 1]) : Infinity;

const raw = JSON.parse(fs.readFileSync(file, "utf8"));
let root = raw.tree ?? raw.document ?? raw;
if (raw.nodes && typeof raw.nodes === "object") {
  root = Object.values(raw.nodes)[0]?.document ?? root;
}

const hexByte = (v) => Math.round((v ?? 0) * 255).toString(16).padStart(2, "0");
function hex(c) {
  let s = "#" + hexByte(c.r) + hexByte(c.g) + hexByte(c.b);
  if (c.a !== undefined && c.a < 1) s += hexByte(c.a);
  return s;
}

function solidFills(node) {
  const fills = Array.isArray(node.fills) ? node.fills : [];
  return fills
    .filter((f) => f && f.visible !== false && f.type === "SOLID" && f.color)
    .map((f) => hex(f.color));
}

const cleanKey = (k) => k.split("#")[0].trim();

function instanceProps(node) {
  const out = [];
  const cp = node.componentProperties;
  if (cp && typeof cp === "object") {
    for (const [k, v] of Object.entries(cp)) {
      if (v && v.type === "INSTANCE_SWAP") continue; // opaque component keys — noise
      const val = v && typeof v === "object" && "value" in v ? v.value : v;
      out.push(`${cleanKey(k)}=${val}`);
    }
  }
  return out;
}

function layoutBits(node) {
  const bits = [];
  if (node.layoutMode && node.layoutMode !== "NONE") bits.push(node.layoutMode);
  if (node.itemSpacing) bits.push(`gap=${node.itemSpacing}`);
  const p = [node.paddingTop, node.paddingRight, node.paddingBottom, node.paddingLeft].map(
    (v) => v ?? 0
  );
  if (p.some(Boolean)) bits.push(`pad=${p.every((v) => v === p[0]) ? p[0] : p.join("/")}`);
  if (node.primaryAxisAlignItems && node.primaryAxisAlignItems !== "MIN")
    bits.push(`main=${node.primaryAxisAlignItems}`);
  if (node.counterAxisAlignItems && node.counterAxisAlignItems !== "MIN")
    bits.push(`cross=${node.counterAxisAlignItems}`);
  if (node.cornerRadius) bits.push(`radius=${node.cornerRadius}`);
  const box = node.absoluteBoundingBox ?? node.size;
  if (box && box.width) bits.push(`${Math.round(box.width)}x${Math.round(box.height)}`);
  return bits;
}

function textBits(node) {
  const s = node.style ?? node;
  const bits = [];
  if (s.fontSize) bits.push(`${s.fontSize}px`);
  if (s.fontWeight) bits.push(`w${s.fontWeight}`);
  const f = solidFills(node);
  if (f.length) bits.push(f[0]);
  return bits;
}

const lines = [];
function walk(node, depth) {
  if (!node || typeof node !== "object" || node.visible === false) return;
  if (depth > maxDepth) return;
  const ind = "  ".repeat(depth);
  const type = node.type ?? "NODE";
  const name = node.name ? ` "${node.name}"` : "";
  const bits = [];
  if (type === "INSTANCE") {
    const comp = node.mainComponent?.name ?? node.componentName;
    if (comp && comp !== node.name) bits.push(`component=${comp}`);
    bits.push(...instanceProps(node));
  }
  bits.push(...layoutBits(node));
  if (type === "TEXT") bits.push(...textBits(node));
  else {
    const f = solidFills(node);
    if (f.length) bits.push(`bg=${f.join(",")}`);
  }
  lines.push(`${ind}${type}${name}${bits.length ? " [" + bits.join(" ") + "]" : ""}`);
  if (type === "TEXT" && node.characters)
    lines.push(`${ind}  > "${String(node.characters).replace(/\n/g, "\\n")}"`);
  for (const child of node.children ?? []) walk(child, depth + 1);
}
walk(root, 0);
console.log(lines.join("\n"));
