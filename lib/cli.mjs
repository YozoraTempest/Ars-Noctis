import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseArgs } from 'node:util';

import { loadDistribution, selectSkills } from './distribution.mjs';
import { doctorInstallation, runtimeWarnings } from './doctor.mjs';
import { ArsNoctisError, fail } from './errors.mjs';
import {
  installSkills,
  installationSnapshot,
  removeSkills,
  resolveInstallation,
  updateSkills,
} from './installer.mjs';

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const HELP = `Ars-Noctis Skill installer

Usage:
  ars-noctis init [path] [--profile <name>] [--skill <id>...] [options]
  ars-noctis update [path] [options]
  ars-noctis doctor [path] [options]
  ars-noctis list [path] [options]
  ars-noctis remove [path] --skill <id>... [options]

Common options:
  --project <path>          Target project instead of a positional path
  --skills-dir <path>       Project-relative skills directory (default: .agents/skills)
  --python <path>           Python executable for runtime checks
  --dry-run                 Report changes without writing
  --replace-modified        Back up and replace locally modified managed targets
  --json                    Emit structured JSON
  --help, -h                Show help
  --version, -V             Show package version
`;

const COMMON_OPTIONS = {
  project: { type: 'string' },
  'skills-dir': { type: 'string', default: '.agents/skills' },
  python: { type: 'string' },
  'dry-run': { type: 'boolean', default: false },
  'replace-modified': { type: 'boolean', default: false },
  json: { type: 'boolean', default: false },
  help: { type: 'boolean', short: 'h', default: false },
};

function commandOptions(command) {
  if (command === 'init') {
    return {
      ...COMMON_OPTIONS,
      profile: { type: 'string' },
      skill: { type: 'string', multiple: true, default: [] },
    };
  }
  if (command === 'remove') {
    return {
      ...COMMON_OPTIONS,
      skill: { type: 'string', multiple: true, default: [] },
    };
  }
  if (command === 'update') return COMMON_OPTIONS;
  if (command === 'doctor') {
    const options = { ...COMMON_OPTIONS };
    delete options['dry-run'];
    delete options['replace-modified'];
    return options;
  }
  if (command === 'list') {
    return {
      project: COMMON_OPTIONS.project,
      'skills-dir': COMMON_OPTIONS['skills-dir'],
      json: COMMON_OPTIONS.json,
      help: COMMON_OPTIONS.help,
    };
  }
  fail(`unknown command '${command}'`, { code: 'usage' });
}

function parseCommand(command, args) {
  let parsed;
  try {
    parsed = parseArgs({
      args,
      options: commandOptions(command),
      allowPositionals: true,
      strict: true,
    });
  } catch (error) {
    fail(error.message, { code: 'usage' });
  }
  if (parsed.positionals.length > 1) {
    fail(`${command} accepts at most one target path`, { code: 'usage' });
  }
  if (parsed.positionals.length === 1 && parsed.values.project !== undefined) {
    fail('use either a positional path or --project, not both', { code: 'usage' });
  }
  return {
    values: parsed.values,
    project: parsed.values.project ?? parsed.positionals[0] ?? process.cwd(),
  };
}

function printActionResult(result) {
  const label = result.dry_run ? 'Planned' : 'Completed';
  process.stdout.write(`${label} ${result.command} in ${result.skills_root}\n`);
  for (const action of result.actions) {
    process.stdout.write(`  ${action.skill}: ${action.status}\n`);
  }
  for (const backup of result.backups) process.stdout.write(`  backup: ${backup}\n`);
  for (const warning of result.warnings ?? []) process.stdout.write(`Warning: ${warning.message}\n`);
}

function printList(result) {
  process.stdout.write(`Ars-Noctis ${result.package.version}\n`);
  process.stdout.write(`Default profile: ${result.default_profile}\n`);
  for (const skill of result.skills) {
    const state = skill.installed ? `installed ${skill.installed_version}` : 'available';
    process.stdout.write(`  ${skill.id}: ${state}\n`);
  }
}

function printDoctor(result) {
  process.stdout.write(result.ok ? 'Ars-Noctis installation is healthy\n' : 'Ars-Noctis installation has issues\n');
  process.stdout.write(`  Skills: ${result.installed_skills.join(', ') || 'none'}\n`);
  if (result.python !== null) {
    const python = result.python.available ? `Python ${result.python.version}` : 'not found';
    process.stdout.write(`  Python: ${python}\n`);
  }
  for (const [name, executable] of Object.entries(result.executables)) {
    process.stdout.write(`  ${name}: ${executable.available ? executable.version : 'not found'}\n`);
  }
  for (const warning of result.warnings) process.stdout.write(`Warning: ${warning.message}\n`);
  for (const issue of result.issues) process.stdout.write(`Error: ${issue.message}\n`);
}

function emit(result, json) {
  if (json) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } else if (result.command === 'list') {
    printList(result);
  } else if (result.command === 'doctor') {
    printDoctor(result);
  } else {
    printActionResult(result);
  }
}

async function execute(command, parsed, distribution) {
  const { values, project } = parsed;
  const installation = await resolveInstallation(project, values['skills-dir']);
  if (command === 'init') {
    const skills = selectSkills(distribution, {
      profile: values.profile,
      skillIds: values.skill,
    });
    const result = await installSkills({
      distribution,
      installation,
      skills,
      dryRun: values['dry-run'],
      replaceModified: values['replace-modified'],
    });
    const warnings = runtimeWarnings(skills, values.python);
    return {
      ...result,
      warnings: [...(result.warnings ?? []), ...warnings],
    };
  }
  if (command === 'update') {
    const result = await updateSkills({
      distribution,
      installation,
      dryRun: values['dry-run'],
      replaceModified: values['replace-modified'],
    });
    const skills = result.actions
      .map((action) => distribution.byId.get(action.skill))
      .filter((skill) => skill !== undefined);
    const warnings = runtimeWarnings(skills, values.python);
    return {
      ...result,
      warnings: [...(result.warnings ?? []), ...warnings],
    };
  }
  if (command === 'remove') {
    return removeSkills({
      distribution,
      installation,
      skillIds: values.skill,
      dryRun: values['dry-run'],
      replaceModified: values['replace-modified'],
    });
  }
  if (command === 'doctor') {
    return doctorInstallation({
      distribution,
      installation,
      python: values.python,
    });
  }
  return installationSnapshot({ distribution, installation });
}

export async function main(args, { packageRoot = PACKAGE_ROOT } = {}) {
  let json = args.includes('--json');
  try {
    const distribution = await loadDistribution(packageRoot);
    if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
      process.stdout.write(HELP);
      return 0;
    }
    if (args[0] === '--version' || args[0] === '-V') {
      process.stdout.write(`${distribution.package.version}\n`);
      return 0;
    }
    const command = args[0];
    const parsed = parseCommand(command, args.slice(1));
    json = parsed.values.json;
    if (parsed.values.help) {
      process.stdout.write(HELP);
      return 0;
    }
    const result = await execute(command, parsed, distribution);
    emit(result, json);
    return command === 'doctor' && !result.ok ? 1 : 0;
  } catch (error) {
    const normalized = error instanceof ArsNoctisError
      ? error
      : new ArsNoctisError(error.message, { details: error.stack });
    const value = {
      ok: false,
      error: normalized.message,
      code: normalized.code,
      ...(normalized.details === undefined ? {} : { details: normalized.details }),
    };
    if (json) {
      process.stderr.write(`${JSON.stringify(value, null, 2)}\n`);
    } else {
      process.stderr.write(`Error: ${normalized.message}\n`);
      if (normalized.code === 'usage') process.stderr.write('\nRun ars-noctis --help for usage.\n');
    }
    return normalized.code === 'usage' ? 2 : 1;
  }
}
