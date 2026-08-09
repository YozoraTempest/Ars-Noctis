import { lstat } from 'node:fs/promises';
import path from 'node:path';

import { fileMapChanges, fileMapsEqual, inventoryTree } from './integrity.mjs';
import { readInstallRecord } from './installer.mjs';
import {
  inspectExecutable,
  inspectPython,
  parsePythonRequirement,
  runPython,
} from './python.mjs';

async function isFile(file) {
  try {
    return (await lstat(file)).isFile();
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

function highestPythonRequirement(skills) {
  let selected = null;
  let selectedParts = null;
  for (const skill of skills) {
    if (!skill?.requires.python) continue;
    const parts = parsePythonRequirement(skill.requires.python);
    if (
      selectedParts === null
      || parts[0] > selectedParts[0]
      || (parts[0] === selectedParts[0] && parts[1] > selectedParts[1])
    ) {
      selected = skill.requires.python;
      selectedParts = parts;
    }
  }
  return selected;
}

function requiredValues(skills, field) {
  return [...new Set(skills.flatMap((skill) => skill?.requires[field] ?? []))].sort();
}

function pythonDescription(requirement, modules) {
  const suffix = modules.length === 0 ? '' : ` with modules ${modules.join(', ')}`;
  return `Python ${requirement}${suffix}`;
}

function commandFailure(skill, check, result) {
  return {
    code: 'skill_check_failed',
    skill: skill.id,
    check: check.id,
    message: result.stderr.trim() || result.stdout.trim() || `command exited ${result.status}`,
  };
}

export async function doctorInstallation({ distribution, installation, python: explicitPython }) {
  const record = await readInstallRecord(installation, distribution, { required: true });
  const issues = [];
  const warnings = [];
  const healthy = new Set();
  const installedSkills = [];

  for (const [id, installed] of Object.entries(record.skills).sort(([left], [right]) => left.localeCompare(right))) {
    const skill = distribution.byId.get(id);
    if (skill !== undefined) installedSkills.push(skill);
    const target = path.join(installation.skillsRoot, id);
    let current;
    try {
      current = await inventoryTree(target, { excludeCaches: true, missing: true });
    } catch (error) {
      issues.push({ code: 'unsafe_skill', skill: id, message: error.message });
      continue;
    }
    if (current === null) {
      issues.push({ code: 'missing_skill', skill: id, message: `managed skill '${id}' is missing` });
      continue;
    }
    if (!fileMapsEqual(installed.files, current.files)) {
      issues.push({
        code: 'modified_skill',
        skill: id,
        files: fileMapChanges(installed.files, current.files),
        message: `managed skill '${id}' differs from its installation record`,
      });
      continue;
    }
    healthy.add(id);
    if (skill === undefined) {
      warnings.push({
        code: 'skill_not_in_package',
        skill: id,
        message: `installed skill '${id}' is not shipped by this package version`,
      });
      continue;
    }
    const available = await inventoryTree(skill.sourcePath, { excludeDevelopment: true });
    if (!fileMapsEqual(installed.files, available.files)) {
      warnings.push({
        code: 'update_available',
        skill: id,
        installed_version: installed.version,
        available_version: distribution.package.version,
        message: `skill '${id}' differs from the current package payload`,
      });
    }
  }

  const requirement = highestPythonRequirement(installedSkills);
  const modules = requiredValues(installedSkills, 'pythonModules');
  const python = requirement === null
    ? null
    : inspectPython({ explicit: explicitPython, requirement, modules });
  if (python !== null && !python.available) {
    issues.push({
      code: 'python_missing',
      requirement,
      modules,
      message: `${pythonDescription(requirement, modules)} is required but was not found`,
    });
  } else if (python !== null && !python.supported) {
    issues.push({
      code: 'python_unsupported',
      requirement,
      version: python.version,
      message: `Python ${python.version} does not satisfy ${requirement}`,
    });
  }

  const executables = {};
  for (const name of requiredValues(installedSkills, 'executables')) {
    const inspected = inspectExecutable(name);
    executables[name] = inspected;
    if (!inspected.available) {
      issues.push({
        code: 'executable_missing',
        executable: name,
        message: `${name} is required but unavailable: ${inspected.error}`,
      });
    }
  }

  if (python?.available && python.supported) {
    for (const skill of installedSkills) {
      if (!healthy.has(skill.id)) continue;
      const target = path.join(installation.skillsRoot, skill.id);
      for (const check of skill.checks) {
        const script = path.join(target, ...check.path.split('/'));
        if (!(await isFile(script))) {
          issues.push({
            code: 'skill_check_missing',
            skill: skill.id,
            check: check.id,
            message: `declared check '${check.id}' is missing for skill '${skill.id}'`,
          });
          continue;
        }
        const result = runPython(python, [script, ...check.args], { cwd: target });
        if (result.status !== 0) issues.push(commandFailure(skill, check, result));
      }
    }
  }

  return {
    ok: issues.length === 0,
    command: 'doctor',
    project: installation.project,
    skills_root: installation.skillsRoot,
    package: distribution.package,
    installed_skills: Object.keys(record.skills).sort(),
    python,
    executables,
    issues,
    warnings,
  };
}

export function runtimeWarnings(skills, explicitPython) {
  const warnings = [];
  const requirement = highestPythonRequirement(skills);
  const modules = requiredValues(skills, 'pythonModules');
  if (requirement !== null) {
    const python = inspectPython({ explicit: explicitPython, requirement, modules });
    if (!python.available) {
      warnings.push({
        code: 'python_missing',
        message: `Installed successfully, but ${pythonDescription(requirement, modules)} was not found`,
      });
    } else if (!python.supported) {
      warnings.push({
        code: 'python_unsupported',
        message: `Installed successfully, but Python ${python.version} does not satisfy ${requirement}`,
      });
    }
  }
  for (const name of requiredValues(skills, 'executables')) {
    const inspected = inspectExecutable(name);
    if (!inspected.available) {
      warnings.push({
        code: 'executable_missing',
        message: `Installed successfully, but required executable '${name}' was not found`,
      });
    }
  }
  return warnings;
}
