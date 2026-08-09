import { randomUUID } from 'node:crypto';
import { lstat, mkdir, readdir, realpath, rename, rm } from 'node:fs/promises';
import path from 'node:path';

import { fail } from './errors.mjs';
import {
  atomicWriteJson,
  copyInventory,
  fileMapChanges,
  fileMapsEqual,
  inventoryTree,
  isWithin,
  readJsonIfPresent,
  validateRelativeDirectory,
} from './integrity.mjs';

export const INSTALL_RECORD_NAME = '.ars-noctis.install.json';

const IDENTIFIER = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
const DIGEST = /^sha256:[a-f0-9]{64}$/;

function exactFields(value, fields, context) {
  const actual = Object.keys(value);
  const missing = fields.filter((field) => !actual.includes(field));
  const unknown = actual.filter((field) => !fields.includes(field));
  if (missing.length > 0) {
    fail(`${context} is missing: ${missing.join(', ')}`, { code: 'invalid_install_record' });
  }
  if (unknown.length > 0) {
    fail(`${context} has unknown fields: ${unknown.join(', ')}`, {
      code: 'invalid_install_record',
    });
  }
}

function validateFiles(value, context) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(`${context} must be an object`, { code: 'invalid_install_record' });
  }
  const files = {};
  for (const [name, digest] of Object.entries(value)) {
    const normalized = name.replaceAll('\\', '/');
    if (
      normalized !== name
      || normalized.length === 0
      || normalized.startsWith('/')
      || normalized.split('/').some((part) => part === '' || part === '.' || part === '..')
    ) {
      fail(`${context} contains an unsafe path: ${name}`, { code: 'invalid_install_record' });
    }
    if (typeof digest !== 'string' || !DIGEST.test(digest)) {
      fail(`${context}.${name} has an invalid digest`, { code: 'invalid_install_record' });
    }
    files[name] = digest;
  }
  return files;
}

function emptyRecord(distribution) {
  return {
    schema: 'ars-noctis.install/v1',
    distribution: distribution.id,
    skills: {},
  };
}

function validateRecord(value, distribution) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail('install record must be an object', { code: 'invalid_install_record' });
  }
  exactFields(value, ['schema', 'distribution', 'skills'], 'install record');
  if (value.schema !== 'ars-noctis.install/v1') {
    fail("install record schema must be 'ars-noctis.install/v1'", {
      code: 'invalid_install_record',
    });
  }
  if (value.distribution !== distribution.id) {
    fail(`install record belongs to distribution '${value.distribution}'`, {
      code: 'install_conflict',
    });
  }
  if (value.skills === null || typeof value.skills !== 'object' || Array.isArray(value.skills)) {
    fail('install record skills must be an object', { code: 'invalid_install_record' });
  }
  const skills = {};
  for (const [id, raw] of Object.entries(value.skills)) {
    if (!IDENTIFIER.test(id) || raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
      fail(`install record has an invalid skill entry: ${id}`, {
        code: 'invalid_install_record',
      });
    }
    exactFields(raw, ['package', 'version', 'files'], `install record skill '${id}'`);
    if (typeof raw.package !== 'string' || raw.package.length === 0) {
      fail(`install record skill '${id}' has an invalid package`, {
        code: 'invalid_install_record',
      });
    }
    if (typeof raw.version !== 'string' || !VERSION.test(raw.version)) {
      fail(`install record skill '${id}' has an invalid version`, {
        code: 'invalid_install_record',
      });
    }
    skills[id] = {
      package: raw.package,
      version: raw.version,
      files: validateFiles(raw.files, `install record skill '${id}'.files`),
    };
  }
  return { schema: value.schema, distribution: value.distribution, skills };
}

async function existingInfo(target) {
  try {
    const info = await lstat(target);
    if (info.isSymbolicLink() || !info.isDirectory()) {
      fail(`skill target must be a real directory: ${target}`, { code: 'unsafe_path' });
    }
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  return inventoryTree(target, { excludeCaches: true });
}

async function assertUnlinkedAncestors(project, target) {
  const relative = path.relative(project, target);
  if (relative === '' || relative.startsWith('..') || path.isAbsolute(relative)) {
    fail(`skills directory must be inside the project: ${target}`, { code: 'unsafe_path' });
  }
  let current = project;
  for (const segment of relative.split(path.sep)) {
    current = path.join(current, segment);
    try {
      const info = await lstat(current);
      if (info.isSymbolicLink()) {
        fail(`skills path contains a symbolic link or junction: ${current}`, {
          code: 'unsafe_path',
        });
      }
      if (!info.isDirectory()) {
        fail(`skills path contains a non-directory: ${current}`, { code: 'unsafe_path' });
      }
    } catch (error) {
      if (error.code === 'ENOENT') return;
      throw error;
    }
  }
}

export async function resolveInstallation(projectValue, skillsDirectory = '.agents/skills') {
  const projectInput = path.resolve(projectValue);
  let project;
  try {
    project = await realpath(projectInput);
  } catch (error) {
    fail(`project directory does not exist: ${projectInput}`, {
      code: 'usage',
      details: error.message,
    });
  }
  const normalized = validateRelativeDirectory(skillsDirectory, 'skills directory');
  const skillsRoot = path.resolve(project, ...normalized.split('/'));
  if (!isWithin(project, skillsRoot) || skillsRoot === project) {
    fail('skills directory must be a child of the project', { code: 'unsafe_path' });
  }
  await assertUnlinkedAncestors(project, skillsRoot);
  return {
    project,
    skillsRoot,
    recordPath: path.join(skillsRoot, INSTALL_RECORD_NAME),
  };
}

export async function readInstallRecord(installation, distribution, { required = false } = {}) {
  try {
    const info = await lstat(installation.recordPath);
    if (info.isSymbolicLink() || !info.isFile()) {
      fail(`installation record must be a real file: ${installation.recordPath}`, {
        code: 'unsafe_path',
      });
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const value = await readJsonIfPresent(installation.recordPath);
  if (value === null) {
    if (required) {
      fail(`no Ars-Noctis installation record exists in ${installation.skillsRoot}`, {
        code: 'not_initialized',
      });
    }
    return emptyRecord(distribution);
  }
  return validateRecord(value, distribution);
}

async function sourceInventories(skills) {
  const result = new Map();
  for (const skill of skills) {
    const inventory = await inventoryTree(skill.sourcePath, { excludeDevelopment: true });
    if (!('SKILL.md' in inventory.files) || !('agents/openai.yaml' in inventory.files)) {
      fail(`skill '${skill.id}' does not contain its required runtime files`, {
        code: 'invalid_distribution',
      });
    }
    result.set(skill.id, inventory);
  }
  return result;
}

function recordEntry(distribution, files) {
  return {
    package: distribution.package.name,
    version: distribution.package.version,
    files,
  };
}

function relativeDisplay(project, target) {
  return path.relative(project, target).split(path.sep).join('/');
}

async function removeIfEmpty(directory) {
  try {
    if ((await readdir(directory)).length === 0) await rm(directory, { recursive: true });
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

async function rollbackPromotions(promotions) {
  for (const promotion of [...promotions].reverse()) {
    try {
      await rm(promotion.target, { recursive: true, force: true });
      if (promotion.backup !== null) {
        await mkdir(path.dirname(promotion.target), { recursive: true });
        await rename(promotion.backup, promotion.target);
      }
    } catch {
      // Preserve the original error; doctor will expose an incomplete rollback.
    }
  }
}

export async function installSkills({
  distribution,
  installation,
  skills,
  dryRun = false,
  replaceModified = false,
}) {
  const record = await readInstallRecord(installation, distribution);
  const inventories = await sourceInventories(skills);
  const actions = [];

  for (const skill of skills) {
    const source = inventories.get(skill.id);
    const target = path.join(installation.skillsRoot, skill.id);
    const current = await existingInfo(target);
    const previous = record.skills[skill.id];
    let status;
    let materialize = false;
    let keepBackup = false;
    let changes = [];

    if (previous !== undefined) {
      if (current === null) {
        status = 'restored';
        materialize = true;
      } else if (fileMapsEqual(previous.files, current.files)) {
        if (fileMapsEqual(source.files, current.files)) {
          status = 'unchanged';
        } else {
          status = 'updated';
          materialize = true;
        }
      } else if (replaceModified) {
        status = 'replaced';
        materialize = true;
        keepBackup = true;
        changes = fileMapChanges(previous.files, current.files);
      } else {
        fail(`managed skill '${skill.id}' has local changes`, {
          code: 'install_conflict',
          details: { skill: skill.id, files: fileMapChanges(previous.files, current.files) },
        });
      }
    } else if (current === null || Object.keys(current.files).length === 0) {
      status = 'installed';
      materialize = true;
    } else if (fileMapsEqual(source.files, current.files)) {
      status = 'adopted';
    } else if (replaceModified) {
      status = 'replaced';
      materialize = true;
      keepBackup = true;
      changes = Object.keys(current.files).sort();
    } else {
      fail(`unmanaged skill target '${skill.id}' already contains different files`, {
        code: 'install_conflict',
        details: { skill: skill.id, files: Object.keys(current.files).sort() },
      });
    }
    actions.push({ skill, source, target, current, status, materialize, keepBackup, changes });
  }

  const nextRecord = structuredClone(record);
  for (const action of actions) {
    nextRecord.skills[action.skill.id] = recordEntry(distribution, action.source.files);
  }
  const result = {
    ok: true,
    command: 'init',
    project: installation.project,
    skills_root: installation.skillsRoot,
    package: distribution.package,
    dry_run: dryRun,
    actions: actions.map((action) => ({
      skill: action.skill.id,
      status: action.status,
      changed_files: action.changes,
    })),
    backups: [],
    warnings: [],
  };
  if (dryRun) return result;

  await mkdir(installation.skillsRoot, { recursive: true });
  await assertUnlinkedAncestors(installation.project, installation.skillsRoot);
  const transactionId = randomUUID();
  const stagingRoot = path.join(installation.skillsRoot, '.ars-noctis-tmp', transactionId);
  const backupRoot = path.join(installation.skillsRoot, '.ars-noctis-backups', transactionId);
  const promotions = [];

  try {
    await assertUnlinkedAncestors(installation.project, stagingRoot);
    await assertUnlinkedAncestors(installation.project, backupRoot);
    await mkdir(stagingRoot, { recursive: true });
    await mkdir(backupRoot, { recursive: true });
    await assertUnlinkedAncestors(installation.project, stagingRoot);
    await assertUnlinkedAncestors(installation.project, backupRoot);
    for (const action of actions.filter((item) => item.materialize)) {
      await copyInventory(action.source, path.join(stagingRoot, action.skill.id));
    }
    for (const action of actions.filter((item) => item.materialize)) {
      let backup = null;
      if (action.current !== null) {
        backup = path.join(backupRoot, action.skill.id);
        await mkdir(path.dirname(backup), { recursive: true });
        await rename(action.target, backup);
      }
      promotions.push({ target: action.target, backup, keepBackup: action.keepBackup });
      await mkdir(path.dirname(action.target), { recursive: true });
      await rename(path.join(stagingRoot, action.skill.id), action.target);
    }
    await atomicWriteJson(installation.recordPath, nextRecord);
  } catch (error) {
    await rollbackPromotions(promotions);
    await rm(stagingRoot, { recursive: true, force: true });
    await removeIfEmpty(path.dirname(stagingRoot));
    throw error;
  }

  try {
    await rm(stagingRoot, { recursive: true, force: true });
    await removeIfEmpty(path.dirname(stagingRoot));
  } catch (error) {
    result.warnings.push({
      code: 'cleanup_failed',
      message: `installation succeeded but staging cleanup failed: ${error.message}`,
    });
  }
  for (const promotion of promotions) {
    if (promotion.backup === null) continue;
    if (promotion.keepBackup) {
      result.backups.push(relativeDisplay(installation.project, promotion.backup));
    } else {
      try {
        await rm(promotion.backup, { recursive: true, force: true });
      } catch (error) {
        result.warnings.push({
          code: 'cleanup_failed',
          message: `installation succeeded but backup cleanup failed: ${error.message}`,
        });
      }
    }
  }
  try {
    await removeIfEmpty(backupRoot);
    await removeIfEmpty(path.dirname(backupRoot));
  } catch (error) {
    result.warnings.push({
      code: 'cleanup_failed',
      message: `installation succeeded but backup directory cleanup failed: ${error.message}`,
    });
  }
  return result;
}

export async function updateSkills(options) {
  const record = await readInstallRecord(options.installation, options.distribution, {
    required: true,
  });
  const skills = [];
  for (const id of Object.keys(record.skills).sort()) {
    const skill = options.distribution.byId.get(id);
    if (skill === undefined) {
      fail(`installed skill '${id}' is not present in this package version`, {
        code: 'invalid_distribution',
      });
    }
    skills.push(skill);
  }
  const result = await installSkills({ ...options, skills });
  return { ...result, command: 'update' };
}

export async function removeSkills({
  distribution,
  installation,
  skillIds,
  dryRun = false,
  replaceModified = false,
}) {
  const record = await readInstallRecord(installation, distribution, { required: true });
  const unique = [...new Set(skillIds)];
  if (unique.length === 0) fail('remove requires at least one --skill', { code: 'usage' });
  const actions = [];
  for (const id of unique) {
    if (!IDENTIFIER.test(id)) fail(`invalid skill id '${id}'`, { code: 'usage' });
    const previous = record.skills[id];
    if (previous === undefined) {
      fail(`skill '${id}' is not managed by this installation`, { code: 'not_installed' });
    }
    const target = path.join(installation.skillsRoot, id);
    const current = await existingInfo(target);
    let keepBackup = false;
    let changes = [];
    let status = 'removed';
    if (current === null) {
      status = 'forgotten';
    } else if (!fileMapsEqual(previous.files, current.files)) {
      changes = fileMapChanges(previous.files, current.files);
      if (!replaceModified) {
        fail(`managed skill '${id}' has local changes`, {
          code: 'install_conflict',
          details: { skill: id, files: changes },
        });
      }
      keepBackup = true;
      status = 'backed-up';
    }
    actions.push({ id, target, current, keepBackup, changes, status });
  }

  const nextRecord = structuredClone(record);
  for (const action of actions) delete nextRecord.skills[action.id];
  const result = {
    ok: true,
    command: 'remove',
    project: installation.project,
    skills_root: installation.skillsRoot,
    package: distribution.package,
    dry_run: dryRun,
    actions: actions.map((action) => ({
      skill: action.id,
      status: action.status,
      changed_files: action.changes,
    })),
    backups: [],
    warnings: [],
  };
  if (dryRun) return result;

  const transactionId = randomUUID();
  const backupRoot = path.join(installation.skillsRoot, '.ars-noctis-backups', transactionId);
  const moved = [];
  try {
    await assertUnlinkedAncestors(installation.project, backupRoot);
    await mkdir(backupRoot, { recursive: true });
    await assertUnlinkedAncestors(installation.project, backupRoot);
    for (const action of actions.filter((item) => item.current !== null)) {
      const backup = path.join(backupRoot, action.id);
      await mkdir(path.dirname(backup), { recursive: true });
      await rename(action.target, backup);
      moved.push({ ...action, backup });
    }
    await atomicWriteJson(installation.recordPath, nextRecord);
  } catch (error) {
    for (const action of [...moved].reverse()) {
      try {
        await rename(action.backup, action.target);
      } catch {
        // Preserve the original error; doctor will expose an incomplete rollback.
      }
    }
    throw error;
  }

  for (const action of moved) {
    if (action.keepBackup) {
      result.backups.push(relativeDisplay(installation.project, action.backup));
    } else {
      try {
        await rm(action.backup, { recursive: true, force: true });
      } catch (error) {
        result.warnings.push({
          code: 'cleanup_failed',
          message: `removal succeeded but backup cleanup failed: ${error.message}`,
        });
      }
    }
  }
  try {
    await removeIfEmpty(backupRoot);
    await removeIfEmpty(path.dirname(backupRoot));
  } catch (error) {
    result.warnings.push({
      code: 'cleanup_failed',
      message: `removal succeeded but backup directory cleanup failed: ${error.message}`,
    });
  }
  return result;
}

export async function installationSnapshot({ distribution, installation }) {
  const record = await readInstallRecord(installation, distribution);
  const skills = [];
  for (const skill of distribution.skills) {
    const installed = record.skills[skill.id] ?? null;
    skills.push({
      id: skill.id,
      profiles: Object.entries(distribution.profiles)
        .filter(([, ids]) => ids.includes(skill.id))
        .map(([name]) => name)
        .sort(),
      installed: installed !== null,
      installed_version: installed?.version ?? null,
      available_version: distribution.package.version,
      requires: skill.requires,
    });
  }
  return {
    ok: true,
    command: 'list',
    project: installation.project,
    skills_root: installation.skillsRoot,
    package: distribution.package,
    default_profile: distribution.defaultProfile,
    profiles: distribution.profiles,
    skills,
  };
}
