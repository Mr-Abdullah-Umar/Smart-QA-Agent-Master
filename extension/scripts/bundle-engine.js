// Copies the Python engine (qa_engine package + runtime requirements) into extension/engine
// so the packaged VSIX works in any project folder, not only inside this repository.
const fs = require("fs");
const path = require("path");

const source = path.resolve(__dirname, "..", "..", "engine");
const target = path.resolve(__dirname, "..", "engine");
const skip = new Set(["__pycache__", ".pytest_cache", ".ruff_cache"]);

function copyDir(from, to) {
  fs.mkdirSync(to, { recursive: true });
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    if (skip.has(entry.name) || entry.name.endsWith(".pyc")) continue;
    const src = path.join(from, entry.name);
    const dest = path.join(to, entry.name);
    if (entry.isDirectory()) copyDir(src, dest);
    else fs.copyFileSync(src, dest);
  }
}

fs.rmSync(target, { recursive: true, force: true });
copyDir(path.join(source, "qa_engine"), path.join(target, "qa_engine"));
fs.copyFileSync(path.join(source, "requirements.txt"), path.join(target, "requirements.txt"));
console.log(`Bundled engine into ${target}`);
