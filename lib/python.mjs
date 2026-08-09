import { spawnSync } from 'node:child_process';

function probeScript(modules) {
  return [
    'import importlib, json, sys',
    `names = ${JSON.stringify(modules)}`,
    'loaded = {name: importlib.import_module(name) for name in names}',
    'sqlite = getattr(loaded.get("sqlite3"), "sqlite_version", None)',
    'print(json.dumps({"version": list(sys.version_info[:3]), "modules": names, "sqlite": sqlite}))',
  ].join('; ');
}

function candidateKey(candidate) {
  return [candidate.command, ...candidate.prefix].join('\0');
}

function candidates(explicit) {
  if (explicit) return [{ command: explicit, prefix: [], source: '--python' }];
  if (process.env.ARS_NOCTIS_PYTHON) {
    return [{
      command: process.env.ARS_NOCTIS_PYTHON,
      prefix: [],
      source: 'ARS_NOCTIS_PYTHON',
    }];
  }
  const values = [];
  values.push(
    { command: 'python3', prefix: [], source: 'PATH' },
    { command: 'python', prefix: [], source: 'PATH' },
  );
  if (process.platform === 'win32') {
    values.push({ command: 'py', prefix: ['-3'], source: 'PATH' });
  }
  const seen = new Set();
  return values.filter((candidate) => {
    const key = candidateKey(candidate);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function versionAtLeast(version, minimum) {
  for (let index = 0; index < Math.max(version.length, minimum.length); index += 1) {
    const actual = version[index] ?? 0;
    const required = minimum[index] ?? 0;
    if (actual > required) return true;
    if (actual < required) return false;
  }
  return true;
}

export function parsePythonRequirement(requirement) {
  const match = /^>=([1-9][0-9]*)\.([0-9]+)$/.exec(requirement);
  if (!match) throw new Error(`unsupported Python requirement: ${requirement}`);
  return [Number(match[1]), Number(match[2])];
}

export function inspectPython({ explicit, requirement = '>=3.11', modules = [] } = {}) {
  const minimum = parsePythonRequirement(requirement);
  const attempts = [];
  for (const candidate of candidates(explicit)) {
    const result = spawnSync(
      candidate.command,
      [...candidate.prefix, '-c', probeScript(modules)],
      { encoding: 'utf8', windowsHide: true },
    );
    if (result.status === 0) {
      try {
        const probe = JSON.parse(result.stdout.trim());
        if (
          !Array.isArray(probe.version)
          || probe.version.length !== 3
          || probe.version.some((part) => !Number.isInteger(part))
          || !Array.isArray(probe.modules)
          || probe.modules.some((item) => typeof item !== 'string')
          || !probe.modules.every((item, index) => item === modules[index])
          || (probe.sqlite !== null && typeof probe.sqlite !== 'string')
        ) {
          throw new Error('unexpected probe output');
        }
        return {
          available: true,
          supported: versionAtLeast(probe.version, minimum),
          command: candidate.command,
          prefix: candidate.prefix,
          source: candidate.source,
          version: probe.version.join('.'),
          sqlite: probe.sqlite,
          modules: probe.modules,
          requirement,
        };
      } catch (error) {
        attempts.push({
          command: candidate.command,
          error: `invalid probe output: ${error.message}`,
        });
      }
    } else {
      attempts.push({
        command: candidate.command,
        error: result.error?.message || result.stderr.trim() || `exit ${result.status}`,
      });
    }
  }
  return {
    available: false,
    supported: false,
    command: null,
    prefix: [],
    source: null,
    version: null,
    sqlite: null,
    modules,
    requirement,
    attempts,
  };
}

export function runPython(python, args, { cwd } = {}) {
  if (!python.available) throw new Error('Python is unavailable');
  return spawnSync(
    python.command,
    [...python.prefix, ...args],
    { cwd, encoding: 'utf8', windowsHide: true },
  );
}

export function inspectGit() {
  return inspectExecutable('git');
}

export function inspectExecutable(command) {
  const result = spawnSync(command, ['--version'], { encoding: 'utf8', windowsHide: true });
  return {
    available: result.status === 0,
    version: result.status === 0 ? (result.stdout.trim() || result.stderr.trim()) : null,
    error: result.status === 0
      ? null
      : result.error?.message || result.stderr.trim() || `exit ${result.status}`,
  };
}
