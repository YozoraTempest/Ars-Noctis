import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { loadDistribution } from '../lib/distribution.mjs';
import { inventoryTree } from '../lib/integrity.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nodeMajor = Number(process.versions.node.split('.')[0]);
if (!Number.isInteger(nodeMajor) || nodeMajor < 22) {
  throw new Error(`package validation requires Node.js 22+; found ${process.versions.node}`);
}
const distribution = await loadDistribution(ROOT);
const packageManifest = JSON.parse(await readFile(path.join(ROOT, 'package.json'), 'utf8'));
const pluginManifest = JSON.parse(
  await readFile(path.join(ROOT, '.codex-plugin', 'plugin.json'), 'utf8'),
);

if (pluginManifest.name !== packageManifest.name) {
  throw new Error('plugin name must match the npm package name');
}
if (pluginManifest.version !== packageManifest.version) {
  throw new Error('plugin version must match the npm package version');
}
if (pluginManifest.skills !== './skills/') {
  throw new Error("plugin skills must resolve to './skills/'");
}
if (!packageManifest.files.includes('.codex-plugin/')) {
  throw new Error('npm package must include the plugin manifest');
}
let files = 0;

for (const skill of distribution.skills) {
  const inventory = await inventoryTree(skill.sourcePath, { excludeDevelopment: true });
  if (!('SKILL.md' in inventory.files) || !('agents/openai.yaml' in inventory.files)) {
    throw new Error(`skill '${skill.id}' is missing required runtime files`);
  }
  files += inventory.entries.length;
}

process.stdout.write(
  `Package validation passed: ${distribution.skills.length} Skills, ${files} runtime files.\n`,
);
