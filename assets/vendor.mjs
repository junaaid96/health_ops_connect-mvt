// Copies third-party browser bundles into static/vendor and the Lucide icons
// the templates actually use into core/icons (read by the {% icon %} tag).
import { copyFileSync, mkdirSync, readFileSync, readdirSync, statSync, existsSync, rmSync, writeFileSync } from "node:fs";
import { join, extname } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const nm = join(root, "node_modules");

mkdirSync(join(root, "static/vendor"), { recursive: true });
for (const [src, dest] of [
  ["htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["alpinejs/dist/cdn.min.js", "alpine.min.js"],
  ["chart.js/dist/chart.umd.min.js", "chart.umd.min.js"],
]) {
  // Drop sourceMappingURL comments: the .map files aren't shipped, and
  // Django's manifest storage fails collectstatic on missing references.
  const code = readFileSync(join(nm, src), "utf8").replace(/\n?\/\/# sourceMappingURL=\S+\s*$/, "\n");
  writeFileSync(join(root, "static/vendor", dest), code);
}

// Collect icon names: {% icon "name" %} in templates, icon="name" / "icon": "name" in Python,
// plus assets/icons.txt for names that only live in the database or are built dynamically.
const names = new Set(readFileSync(join(root, "assets/icons.txt"), "utf8").split(/\s+/).filter(Boolean));
const skip = new Set(["node_modules", ".git", "static", "staticfiles", "media", "assets"]);
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (skip.has(entry)) continue;
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) { walk(p); continue; }
    const ext = extname(p);
    if (ext !== ".html" && ext !== ".py") continue;
    const text = readFileSync(p, "utf8");
    for (const m of text.matchAll(/\{%\s*icon\s+"([a-z0-9-]+)"/g)) names.add(m[1]);
    for (const m of text.matchAll(/(?:icon\s*=\s*|"icon"\s*:\s*|icon_name\s*=\s*)"([a-z0-9-]+)"/g)) names.add(m[1]);
    for (const m of text.matchAll(/ICON:([a-z0-9-]+)/g)) names.add(m[1]);
  }
}
walk(root);

const out = join(root, "core/icons");
if (existsSync(out)) rmSync(out, { recursive: true });
mkdirSync(out, { recursive: true });
const missing = [];
for (const name of [...names].sort()) {
  const src = join(nm, "lucide-static/icons", `${name}.svg`);
  if (existsSync(src)) copyFileSync(src, join(out, `${name}.svg`));
  else missing.push(name);
}
console.log(`vendored ${names.size - missing.length} icons`);
if (missing.length) { console.error(`missing icons: ${missing.join(", ")}`); process.exitCode = 1; }
