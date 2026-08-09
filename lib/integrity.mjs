import { createHash, randomUUID } from 'node:crypto';
import {
  copyFile,
  lstat,
  mkdir,
  open,
  readdir,
  readFile,
  realpath,
  rename,
  rm,
} from 'node:fs/promises';
import path from 'node:path';

import { fail } from './errors.mjs';

const CACHE_DIRECTORIES = new Set([
  '__pycache__',
  '.mypy_cache',
  '.pytest_cache',
]);
const DEVELOPMENT_DIRECTORIES = new Set([
  ...CACHE_DIRECTORIES,
  'node_modules',
  'tests',
]);

function slash(value) {
  return value.split(path.sep).join('/');
}

export function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

export function validateRelativeDirectory(value, context = 'directory') {
  if (typeof value !== 'string' || value.length === 0 || path.isAbsolute(value)) {
    fail(`${context} must be a non-empty relative path`, { code: 'usage' });
  }
  const normalized = value.replaceAll('\\', '/');
  if (normalized.split('/').some((part) => part === '' || part === '.' || part === '..')) {
    fail(`${context} must not contain empty, current, or parent segments`, { code: 'usage' });
  }
  return normalized;
}

async function digestFile(file) {
  const content = await readFile(file);
  return `sha256:${createHash('sha256').update(content).digest('hex')}`;
}

function excluded(relative, directories) {
  const parts = relative.split('/');
  return parts.some((part) => directories.has(part))
    || relative.endsWith('.pyc')
    || relative.endsWith('/.DS_Store')
    || relative === '.DS_Store';
}

export async function inventoryTree(
  root,
  { excludeDevelopment = false, excludeCaches = false, missing = false } = {},
) {
  const absoluteRoot = path.resolve(root);
  let rootInfo;
  try {
    rootInfo = await lstat(absoluteRoot);
  } catch (error) {
    if (missing && error.code === 'ENOENT') return null;
    throw error;
  }
  if (rootInfo.isSymbolicLink() || !rootInfo.isDirectory()) {
    fail(`expected a real directory: ${absoluteRoot}`, { code: 'unsafe_path' });
  }
  const resolvedRoot = await realpath(absoluteRoot);
  const entries = [];

  async function visit(directory) {
    const resolvedDirectory = await realpath(directory);
    if (!isWithin(resolvedRoot, resolvedDirectory)) {
      fail(`directory escapes its root: ${directory}`, { code: 'unsafe_path' });
    }
    const children = await readdir(directory, { withFileTypes: true });
    children.sort((left, right) => left.name.localeCompare(right.name, 'en'));
    for (const child of children) {
      const absolute = path.join(directory, child.name);
      const relative = slash(path.relative(absoluteRoot, absolute));
      if (excludeDevelopment && excluded(relative, DEVELOPMENT_DIRECTORIES)) continue;
      if (excludeCaches && excluded(relative, CACHE_DIRECTORIES)) continue;
      const info = await lstat(absolute);
      if (info.isSymbolicLink()) {
        fail(`symbolic links and junctions are not installable: ${absolute}`, {
          code: 'unsafe_path',
        });
      }
      if (info.isDirectory()) {
        await visit(absolute);
      } else if (info.isFile()) {
        entries.push({ relative, absolute, digest: await digestFile(absolute) });
      } else {
        fail(`unsupported filesystem entry: ${absolute}`, { code: 'unsafe_path' });
      }
    }
  }

  await visit(absoluteRoot);
  const files = {};
  for (const entry of entries) files[entry.relative] = entry.digest;
  return { root: absoluteRoot, entries, files };
}

export function fileMapsEqual(left, right) {
  const leftEntries = Object.entries(left);
  const rightEntries = Object.entries(right);
  if (leftEntries.length !== rightEntries.length) return false;
  return leftEntries.every(([name, digest]) => right[name] === digest);
}

export function fileMapChanges(expected, actual) {
  const names = [...new Set([...Object.keys(expected), ...Object.keys(actual)])].sort();
  return names.filter((name) => expected[name] !== actual[name]);
}

export async function copyInventory(inventory, target) {
  await mkdir(target, { recursive: true });
  for (const entry of inventory.entries) {
    const destination = path.join(target, ...entry.relative.split('/'));
    if (!isWithin(path.resolve(target), path.resolve(destination))) {
      fail(`copy target escapes the staging directory: ${entry.relative}`, {
        code: 'unsafe_path',
      });
    }
    await mkdir(path.dirname(destination), { recursive: true });
    await copyFile(entry.absolute, destination);
  }
}

function sortedValue(value) {
  if (Array.isArray(value)) return value.map(sortedValue);
  if (value !== null && typeof value === 'object') {
    const result = {};
    for (const key of Object.keys(value).sort()) result[key] = sortedValue(value[key]);
    return result;
  }
  return value;
}

export function stableJson(value) {
  return `${JSON.stringify(sortedValue(value), null, 2)}\n`;
}

export async function atomicWriteJson(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = path.join(path.dirname(file), `.${path.basename(file)}.${randomUUID()}.tmp`);
  const handle = await open(temporary, 'wx');
  try {
    await handle.writeFile(stableJson(value), 'utf8');
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    await rename(temporary, file);
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
}

export async function readJsonIfPresent(file) {
  let content;
  try {
    content = await readFile(file, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  try {
    return JSON.parse(content.replace(/^\uFEFF/, ''));
  } catch (error) {
    fail(`invalid JSON in ${file}: ${error.message}`, { code: 'invalid_install_record' });
  }
}
