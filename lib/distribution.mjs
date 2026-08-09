import { readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';

import { fail } from './errors.mjs';
import { isSemVer } from './semver.mjs';

const IDENTIFIER = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const EXECUTABLE = /^[A-Za-z0-9][A-Za-z0-9._+-]*$/;
const PYTHON_MODULE = /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/;
const PYTHON_REQUIREMENT = /^>=([1-9][0-9]*)\.([0-9]+)$/;

function objectValue(value, context) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(`${context} must be an object`, { code: 'invalid_distribution' });
  }
  return value;
}

function exactFields(value, fields, context) {
  const actual = Object.keys(value);
  const missing = fields.filter((field) => !actual.includes(field));
  const unknown = actual.filter((field) => !fields.includes(field));
  if (missing.length > 0) {
    fail(`${context} is missing: ${missing.join(', ')}`, { code: 'invalid_distribution' });
  }
  if (unknown.length > 0) {
    fail(`${context} has unknown fields: ${unknown.join(', ')}`, { code: 'invalid_distribution' });
  }
}

function optionalFields(value, fields, context) {
  const unknown = Object.keys(value).filter((field) => !fields.includes(field));
  if (unknown.length > 0) {
    fail(`${context} has unknown fields: ${unknown.join(', ')}`, {
      code: 'invalid_distribution',
    });
  }
}

function identifier(value, context) {
  if (typeof value !== 'string' || !IDENTIFIER.test(value)) {
    fail(`${context} must be a lowercase hyphenated identifier`, {
      code: 'invalid_distribution',
    });
  }
  return value;
}

function relativeSource(value, context) {
  if (typeof value !== 'string' || value.length === 0 || path.isAbsolute(value)) {
    fail(`${context} must be a non-empty relative path`, { code: 'invalid_distribution' });
  }
  const normalized = value.replaceAll('\\', '/');
  if (normalized.split('/').some((part) => part === '' || part === '.' || part === '..')) {
    fail(`${context} must not contain empty, current, or parent segments`, {
      code: 'invalid_distribution',
    });
  }
  return normalized;
}

function stringList(value, context) {
  if (!Array.isArray(value)) {
    fail(`${context} must be a list`, { code: 'invalid_distribution' });
  }
  const result = value.map((item, index) => identifier(item, `${context}[${index}]`));
  if (new Set(result).size !== result.length) {
    fail(`${context} contains duplicates`, { code: 'invalid_distribution' });
  }
  return result;
}

function parseRequires(value, context) {
  if (value === undefined) return { python: null, pythonModules: [], executables: [] };
  const requires = objectValue(value, context);
  optionalFields(requires, ['python', 'python_modules', 'executables'], context);
  let python = null;
  if (requires.python !== undefined) {
    if (typeof requires.python !== 'string' || !PYTHON_REQUIREMENT.test(requires.python)) {
      fail(`${context}.python must use the form >=MAJOR.MINOR`, {
        code: 'invalid_distribution',
      });
    }
    python = requires.python;
  }
  const pythonModules = requires.python_modules === undefined
    ? []
    : stringValues(requires.python_modules, `${context}.python_modules`, PYTHON_MODULE);
  if (pythonModules.length > 0 && python === null) {
    fail(`${context}.python_modules requires a Python version`, {
      code: 'invalid_distribution',
    });
  }
  const executables = requires.executables === undefined
    ? []
    : stringValues(requires.executables, `${context}.executables`, EXECUTABLE);
  return { python, pythonModules, executables };
}

function stringValues(value, context, pattern = null, unique = true) {
  if (!Array.isArray(value)) {
    fail(`${context} must be a list`, { code: 'invalid_distribution' });
  }
  const result = value.map((item, index) => {
    if (
      typeof item !== 'string'
      || item.length === 0
      || item.includes('\0')
      || (pattern !== null && !pattern.test(item))
    ) {
      fail(`${context}[${index}] is invalid`, { code: 'invalid_distribution' });
    }
    return item;
  });
  if (unique && new Set(result).size !== result.length) {
    fail(`${context} contains duplicates`, { code: 'invalid_distribution' });
  }
  return result;
}

async function parseChecks(value, context, sourcePath, requires) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    fail(`${context} must be a list`, { code: 'invalid_distribution' });
  }
  const checks = [];
  const ids = new Set();
  for (const [index, raw] of value.entries()) {
    const checkContext = `${context}[${index}]`;
    const check = objectValue(raw, checkContext);
    exactFields(check, ['id', 'run', 'path', 'args'], checkContext);
    const id = identifier(check.id, `${checkContext}.id`);
    if (ids.has(id)) {
      fail(`${context} repeats check '${id}'`, { code: 'invalid_distribution' });
    }
    ids.add(id);
    if (check.run !== 'python') {
      fail(`${checkContext}.run must be 'python'`, { code: 'invalid_distribution' });
    }
    if (requires.python === null) {
      fail(`${checkContext} requires a Python runtime declaration`, {
        code: 'invalid_distribution',
      });
    }
    const checkPath = relativeSource(check.path, `${checkContext}.path`);
    const absolutePath = path.resolve(sourcePath, ...checkPath.split('/'));
    if (!isWithin(sourcePath, absolutePath)) {
      fail(`${checkContext}.path escapes its Skill`, { code: 'invalid_distribution' });
    }
    try {
      if (!(await stat(absolutePath)).isFile()) throw new Error('not a file');
    } catch (error) {
      fail(`${checkContext}.path is unavailable: ${checkPath}`, {
        code: 'invalid_distribution',
        details: error.message,
      });
    }
    checks.push({
      id,
      run: check.run,
      path: checkPath,
      args: stringValues(check.args, `${checkContext}.args`, null, false),
    });
  }
  return checks;
}

function frontmatterName(content, context) {
  const lines = content.replace(/^\uFEFF/, '').split(/\r?\n/);
  if (lines[0] !== '---') {
    fail(`${context} is missing YAML frontmatter`, { code: 'invalid_distribution' });
  }
  const end = lines.indexOf('---', 1);
  if (end < 0) {
    fail(`${context} has unterminated YAML frontmatter`, { code: 'invalid_distribution' });
  }
  for (const line of lines.slice(1, end)) {
    const match = /^name:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*$/.exec(line);
    if (match) return match[1];
  }
  fail(`${context} frontmatter must contain a scalar name`, {
    code: 'invalid_distribution',
  });
}

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

async function loadJson(file, context) {
  let content;
  try {
    content = await readFile(file, 'utf8');
  } catch (error) {
    fail(`cannot read ${context}: ${file}`, {
      code: 'invalid_distribution',
      details: error.message,
    });
  }
  try {
    return JSON.parse(content.replace(/^\uFEFF/, ''));
  } catch (error) {
    fail(`invalid JSON in ${context}: ${error.message}`, { code: 'invalid_distribution' });
  }
}

export async function loadDistribution(packageRoot) {
  const root = await realpath(path.resolve(packageRoot));
  const packageValue = objectValue(
    await loadJson(path.join(root, 'package.json'), 'package.json'),
    'package.json',
  );
  if (typeof packageValue.name !== 'string' || !isSemVer(packageValue.version)) {
    fail('package.json must contain a name and valid SemVer version', {
      code: 'invalid_distribution',
    });
  }

  const value = objectValue(
    await loadJson(path.join(root, 'distribution.json'), 'distribution.json'),
    'distribution',
  );
  exactFields(value, ['schema', 'id', 'default_profile', 'profiles', 'skills'], 'distribution');
  if (value.schema !== 'ars-noctis.distribution/v1') {
    fail("distribution.schema must be 'ars-noctis.distribution/v1'", {
      code: 'invalid_distribution',
    });
  }
  const distributionId = identifier(value.id, 'distribution.id');
  const defaultProfile = identifier(value.default_profile, 'distribution.default_profile');

  if (!Array.isArray(value.skills) || value.skills.length === 0) {
    fail('distribution.skills must be a non-empty list', { code: 'invalid_distribution' });
  }
  const skills = [];
  const byId = new Map();
  for (const [index, raw] of value.skills.entries()) {
    const item = objectValue(raw, `distribution.skills[${index}]`);
    const allowed = [
      'id',
      'source',
      ...(item.requires === undefined ? [] : ['requires']),
      ...(item.checks === undefined ? [] : ['checks']),
    ];
    exactFields(item, allowed, `distribution.skills[${index}]`);
    const id = identifier(item.id, `distribution.skills[${index}].id`);
    if (byId.has(id)) {
      fail(`distribution repeats skill '${id}'`, { code: 'invalid_distribution' });
    }
    const source = relativeSource(item.source, `distribution.skills[${index}].source`);
    if (path.posix.basename(source) !== id) {
      fail(`skill '${id}' source directory must have the same name`, {
        code: 'invalid_distribution',
      });
    }
    const sourcePath = path.resolve(root, ...source.split('/'));
    if (!isWithin(root, sourcePath)) {
      fail(`skill '${id}' source escapes the package`, { code: 'invalid_distribution' });
    }
    try {
      if (!(await stat(sourcePath)).isDirectory()) throw new Error('not a directory');
    } catch (error) {
      fail(`skill '${id}' source is unavailable: ${source}`, {
        code: 'invalid_distribution',
        details: error.message,
      });
    }
    const skillFile = path.join(sourcePath, 'SKILL.md');
    const name = frontmatterName(await readFile(skillFile, 'utf8'), skillFile);
    if (name !== id) {
      fail(`skill '${id}' directory and SKILL.md name differ`, {
        code: 'invalid_distribution',
      });
    }
    try {
      if (!(await stat(path.join(sourcePath, 'agents', 'openai.yaml'))).isFile()) {
        throw new Error('not a file');
      }
    } catch (error) {
      fail(`skill '${id}' is missing agents/openai.yaml`, {
        code: 'invalid_distribution',
        details: error.message,
      });
    }
    const requires = parseRequires(item.requires, `distribution.skills[${index}].requires`);
    const skill = {
      id,
      source,
      sourcePath,
      requires,
      checks: await parseChecks(
        item.checks,
        `distribution.skills[${index}].checks`,
        sourcePath,
        requires,
      ),
    };
    skills.push(skill);
    byId.set(id, skill);
  }

  const profilesValue = objectValue(value.profiles, 'distribution.profiles');
  const profiles = {};
  for (const [profile, rawSkills] of Object.entries(profilesValue)) {
    identifier(profile, `distribution.profiles.${profile}`);
    const selected = stringList(rawSkills, `distribution.profiles.${profile}`);
    for (const id of selected) {
      if (!byId.has(id)) {
        fail(`profile '${profile}' references unknown skill '${id}'`, {
          code: 'invalid_distribution',
        });
      }
    }
    profiles[profile] = selected;
  }
  if (!(defaultProfile in profiles)) {
    fail(`default profile '${defaultProfile}' does not exist`, {
      code: 'invalid_distribution',
    });
  }

  return {
    schema: value.schema,
    id: distributionId,
    defaultProfile,
    profiles,
    skills,
    byId,
    package: { name: packageValue.name, version: packageValue.version },
    packageRoot: root,
  };
}

export function selectSkills(distribution, { profile, skillIds = [] }) {
  const explicit = stringList(skillIds, 'skills');
  let selected = [];
  if (profile !== undefined) {
    if (!(profile in distribution.profiles)) {
      fail(`unknown profile '${profile}'`, {
        code: 'usage',
        details: { available: Object.keys(distribution.profiles).sort() },
      });
    }
    selected = [...distribution.profiles[profile]];
  } else if (explicit.length === 0) {
    selected = [...distribution.profiles[distribution.defaultProfile]];
  }
  for (const id of explicit) {
    if (!distribution.byId.has(id)) {
      fail(`unknown skill '${id}'`, {
        code: 'usage',
        details: { available: distribution.skills.map((skill) => skill.id) },
      });
    }
    if (!selected.includes(id)) selected.push(id);
  }
  return selected.map((id) => distribution.byId.get(id));
}
