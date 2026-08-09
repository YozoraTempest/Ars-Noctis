import { lstat, readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

import { fileMapChanges, fileMapsEqual, inventoryTree } from './integrity.mjs';
import { readInstallRecord } from './installer.mjs';
import { inspectGit, inspectPython, parsePythonRequirement, runPython } from './python.mjs';

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

async function inspectCatalog(skillsRoot, issues) {
  let children;
  try {
    children = await readdir(skillsRoot, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') return;
    throw error;
  }
  const manifests = new Map();
  for (const child of children.filter((item) => item.isDirectory())) {
    const manifestPath = path.join(skillsRoot, child.name, 'ars.json');
    if (!(await isFile(manifestPath))) continue;
    try {
      const manifest = JSON.parse((await readFile(manifestPath, 'utf8')).replace(/^\uFEFF/, ''));
      if (typeof manifest.id !== 'string' || manifest.id.length === 0) {
        issues.push({ code: 'invalid_ars_manifest', skill: child.name, message: 'ars.json has no id' });
        continue;
      }
      const previous = manifests.get(manifest.id);
      if (previous !== undefined) {
        issues.push({
          code: 'ambiguous_provider',
          provider: manifest.id,
          skills: [previous, child.name],
          message: `provider '${manifest.id}' is declared by multiple skills`,
        });
      } else {
        manifests.set(manifest.id, child.name);
      }
    } catch (error) {
      issues.push({
        code: 'invalid_ars_manifest',
        skill: child.name,
        message: `cannot parse ars.json: ${error.message}`,
      });
    }
  }
}

function commandFailure(code, skill, result) {
  return {
    code,
    skill,
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
    installedSkills.push(skill);
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

  await inspectCatalog(installation.skillsRoot, issues);
  const requirement = highestPythonRequirement(installedSkills);
  const python = requirement === null
    ? null
    : inspectPython({ explicit: explicitPython, requirement });
  if (python !== null && !python.available) {
    issues.push({
      code: 'python_missing',
      requirement,
      message: `Python ${requirement} with sqlite3 is required but was not found`,
    });
  } else if (python !== null && !python.supported) {
    issues.push({
      code: 'python_unsupported',
      requirement,
      version: python.version,
      message: `Python ${python.version} does not satisfy ${requirement}`,
    });
  }

  const git = inspectGit();
  if (!git.available) {
    issues.push({ code: 'git_missing', message: `Git is required but unavailable: ${git.error}` });
  }

  if (python?.available && python.supported) {
    const arsScript = path.join(installation.skillsRoot, 'ars', 'scripts', 'ars.py');
    if (healthy.has('ars') && await isFile(arsScript)) {
      for (const id of Object.keys(record.skills).sort()) {
        const manifest = path.join(installation.skillsRoot, id, 'ars.json');
        if (!(await isFile(manifest))) continue;
        const result = runPython(
          python,
          [arsScript, 'validate', '--skill', path.join(installation.skillsRoot, id)],
          { cwd: installation.project },
        );
        if (result.status !== 0) issues.push(commandFailure('ars_validation_failed', id, result));
      }
    }
    const noctisScript = path.join(
      installation.skillsRoot,
      'noctis',
      'scripts',
      'noctis.py',
    );
    const examplePlan = path.join(
      installation.skillsRoot,
      'noctis',
      'assets',
      'plan.example.json',
    );
    if (healthy.has('noctis') && await isFile(noctisScript) && await isFile(examplePlan)) {
      const result = runPython(
        python,
        [noctisScript, 'plan-check', '--plan', examplePlan],
        { cwd: installation.project },
      );
      if (result.status !== 0) {
        issues.push(commandFailure('noctis_validation_failed', 'noctis', result));
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
    git,
    issues,
    warnings,
  };
}

export function runtimeWarning(skills, explicitPython) {
  const requirement = highestPythonRequirement(skills);
  if (requirement === null) return null;
  const python = inspectPython({ explicit: explicitPython, requirement });
  if (!python.available) {
    return {
      code: 'python_missing',
      message: `Installed successfully, but Python ${requirement} with sqlite3 was not found`,
    };
  }
  if (!python.supported) {
    return {
      code: 'python_unsupported',
      message: `Installed successfully, but Python ${python.version} does not satisfy ${requirement}`,
    };
  }
  return null;
}
