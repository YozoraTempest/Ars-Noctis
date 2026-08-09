import { readFile, realpath, stat } from 'node:fs/promises';
import path from 'node:path';

import { fail } from './errors.mjs';

const IDENTIFIER = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
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
  if (value === undefined) return {};
  const requires = objectValue(value, context);
  exactFields(requires, ['python'], context);
  if (typeof requires.python !== 'string' || !PYTHON_REQUIREMENT.test(requires.python)) {
    fail(`${context}.python must use the form >=MAJOR.MINOR`, {
      code: 'invalid_distribution',
    });
  }
  return { python: requires.python };
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
  if (typeof packageValue.name !== 'string' || typeof packageValue.version !== 'string') {
    fail('package.json must contain name and version', { code: 'invalid_distribution' });
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
    const allowed = item.requires === undefined
      ? ['id', 'source']
      : ['id', 'source', 'requires'];
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
    const skill = {
      id,
      source,
      sourcePath,
      requires: parseRequires(item.requires, `distribution.skills[${index}].requires`),
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
