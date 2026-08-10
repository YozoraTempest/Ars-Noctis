import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import {
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  rm,
  symlink,
  unlink,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { loadDistribution, selectSkills } from '../lib/distribution.mjs';
import { doctorInstallation } from '../lib/doctor.mjs';
import {
  DEFAULT_SKILLS_DIRECTORY,
  promptInitOptions,
  shouldRunInitWizard,
} from '../lib/init-wizard.mjs';
import {
  installSkills,
  installationSnapshot,
  readInstallRecord,
  removeSkills,
  resolveInstallation,
  updateSkills,
} from '../lib/installer.mjs';
import { isSemVer } from '../lib/semver.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BIN = path.join(ROOT, 'bin', 'ars-noctis.mjs');
const distribution = await loadDistribution(ROOT);

async function projectFor(t) {
  const project = await mkdtemp(path.join(os.tmpdir(), 'ars-noctis-test-'));
  t.after(() => rm(project, { recursive: true, force: true }));
  return project;
}

async function context(t) {
  const project = await projectFor(t);
  const installation = await resolveInstallation(project);
  return { project, installation };
}

function coreSkills() {
  return selectSkills(distribution, { profile: 'core' });
}


function scriptedWizard(answers) {
  const pending = [...answers];
  let output = '';
  return {
    question: async () => {
      assert.notEqual(pending.length, 0, 'wizard requested more answers than expected');
      return pending.shift();
    },
    write: (value) => { output += value; },
    output: () => output,
    remaining: () => pending,
  };
}

function runCli(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [BIN, ...args], { windowsHide: true });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (value) => { stdout += value; });
    child.stderr.on('data', (value) => { stderr += value; });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error(stderr || stdout || `CLI exited ${code}`));
    });
  });
}

test('distribution exposes declarative profiles and independent skills', () => {
  assert.equal(distribution.id, 'ars-noctis');
  assert.equal(distribution.defaultProfile, 'core');
  assert.deepEqual(distribution.profiles.core, ['ars', 'noctis']);
  assert.deepEqual(
    distribution.skills.map((skill) => skill.id),
    ['ars', 'noctis', 'implement', 'code-review', 'verify'],
  );
  assert.deepEqual(
    selectSkills(distribution, { skillIds: ['verify'] }).map((skill) => skill.id),
    ['verify'],
  );
  assert.deepEqual(distribution.byId.get('ars').requires.executables, ['git']);
  assert.deepEqual(distribution.byId.get('noctis').requires.pythonModules, ['sqlite3']);
  assert.deepEqual(distribution.byId.get('verify').requires.executables, []);
  assert.deepEqual(distribution.byId.get('ars').checks.map((check) => check.id), ['manifest']);
});

test('init wizard runs only for an unconfigured human TTY', () => {
  const tty = { isTTY: true };
  const values = {
    profile: undefined,
    skill: [],
    json: false,
    'no-interactive': false,
  };
  assert.equal(shouldRunInitWizard(values, { input: tty, output: tty, env: {} }), true);
  assert.equal(
    shouldRunInitWizard({ ...values, profile: 'full' }, { input: tty, output: tty, env: {} }),
    false,
  );
  assert.equal(
    shouldRunInitWizard({ ...values, skill: ['verify'] }, { input: tty, output: tty, env: {} }),
    false,
  );
  assert.equal(
    shouldRunInitWizard({ ...values, json: true }, { input: tty, output: tty, env: {} }),
    false,
  );
  assert.equal(
    shouldRunInitWizard(
      { ...values, 'no-interactive': true },
      { input: tty, output: tty, env: {} },
    ),
    false,
  );
  assert.equal(
    shouldRunInitWizard(values, { input: tty, output: tty, env: { CI: 'true' } }),
    false,
  );
  assert.equal(
    shouldRunInitWizard(values, { input: { isTTY: false }, output: tty, env: {} }),
    false,
  );
});

test('init wizard selects profiles, destination, and confirmation', async () => {
  const wizard = scriptedWizard(['2', '', '']);
  const selection = await promptInitOptions({
    distribution,
    project: ROOT,
    question: wizard.question,
    write: wizard.write,
  });
  assert.equal(selection.canceled, false);
  assert.equal(selection.profile, 'full');
  assert.deepEqual(selection.skillIds, []);
  assert.deepEqual(
    selection.selectedSkillIds,
    ['ars', 'noctis', 'implement', 'code-review', 'verify'],
  );
  assert.equal(selection.skillsDirectory, DEFAULT_SKILLS_DIRECTORY);
  assert.match(wizard.output(), /Installation plan:/);
  assert.deepEqual(wizard.remaining(), []);
});

test('init wizard supports custom Skills and an explicit project-relative directory', async () => {
  const wizard = scriptedWizard(['custom', '3,verify,3', '.custom/skills', 'yes']);
  const selection = await promptInitOptions({
    distribution,
    project: ROOT,
    question: wizard.question,
    write: wizard.write,
  });
  assert.equal(selection.canceled, false);
  assert.equal(selection.profile, undefined);
  assert.deepEqual(selection.skillIds, ['implement', 'verify']);
  assert.equal(selection.skillsDirectory, '.custom/skills');
  assert.deepEqual(wizard.remaining(), []);
});

test('init wizard honors an explicit directory and cancellation', async () => {
  const wizard = scriptedWizard(['core', 'no']);
  const selection = await promptInitOptions({
    distribution,
    project: ROOT,
    skillsDirectory: '.codex/skills',
    skillsDirectoryExplicit: true,
    question: wizard.question,
    write: wizard.write,
  });
  assert.equal(selection.canceled, true);
  assert.equal(selection.profile, 'core');
  assert.equal(selection.skillsDirectory, '.codex/skills');
  assert.deepEqual(wizard.remaining(), []);
});

test('core init installs deterministic runtime payload and record', async (t) => {
  const { installation } = await context(t);
  const result = await installSkills({
    distribution,
    installation,
    skills: coreSkills(),
  });

  assert.deepEqual(result.actions.map((action) => action.status), ['installed', 'installed']);
  assert.equal(await readFile(path.join(installation.skillsRoot, 'ars', 'SKILL.md'), 'utf8')
    .then((value) => value.includes('name: ars')), true);
  await assert.rejects(readFile(path.join(installation.skillsRoot, 'implement', 'SKILL.md')));
  await assert.rejects(readFile(path.join(installation.skillsRoot, 'ars', 'tests', 'test_ars.py')));
  const rawRecord = await readFile(installation.recordPath, 'utf8');
  const record = JSON.parse(rawRecord);
  assert.equal(record.schema, 'ars-noctis.install/v1');
  assert.deepEqual(Object.keys(record.skills), ['ars', 'noctis']);
  assert.equal(rawRecord.includes(installation.project), false);
  assert.equal(rawRecord.includes('installed_at'), false);
});

test('init and update are idempotent', async (t) => {
  const { installation } = await context(t);
  await installSkills({ distribution, installation, skills: coreSkills() });
  const second = await installSkills({ distribution, installation, skills: coreSkills() });
  assert.deepEqual(second.actions.map((action) => action.status), ['unchanged', 'unchanged']);

  const updated = await updateSkills({ distribution, installation });
  assert.equal(updated.command, 'update');
  assert.deepEqual(updated.actions.map((action) => action.status), ['unchanged', 'unchanged']);
});

test('concurrent installs serialize record and target promotion', async (t) => {
  const { installation } = await context(t);
  await Promise.all(
    distribution.skills.map((skill) => installSkills({
      distribution,
      installation,
      skills: [skill],
    })),
  );

  const record = await readInstallRecord(installation, distribution, { required: true });
  assert.deepEqual(Object.keys(record.skills).sort(), distribution.skills.map((skill) => skill.id).sort());
  for (const skill of distribution.skills) {
    assert.equal(
      (await readFile(path.join(installation.skillsRoot, skill.id, 'SKILL.md'), 'utf8'))
        .includes(`name: ${skill.id}`),
      true,
    );
  }
  await assert.rejects(readFile(path.join(installation.skillsRoot, '.ars-noctis-lock', 'owner.json')));
});

test('concurrent installs of one skill do not roll back another promotion', async (t) => {
  const { installation } = await context(t);
  const verify = selectSkills(distribution, { skillIds: ['verify'] });
  const results = await Promise.all(
    Array.from({ length: 4 }, () => installSkills({
      distribution,
      installation,
      skills: verify,
    })),
  );

  assert.equal(results.flatMap((result) => result.actions).filter((item) => item.status === 'installed').length, 1);
  assert.equal(
    (await readFile(path.join(installation.skillsRoot, 'verify', 'SKILL.md'), 'utf8'))
      .includes('name: verify'),
    true,
  );
});

test('concurrent CLI processes preserve every installation record entry', async (t) => {
  const { project, installation } = await context(t);
  const skillIds = ['implement', 'code-review', 'verify'];
  await Promise.all(
    skillIds.map((id) => runCli(['init', project, '--skill', id, '--json'])),
  );

  const record = await readInstallRecord(installation, distribution, { required: true });
  assert.deepEqual(Object.keys(record.skills).sort(), [...skillIds].sort());
});

test('full profile installs every currently declared skill', async (t) => {
  const { installation } = await context(t);
  const skills = selectSkills(distribution, { profile: 'full' });
  const result = await installSkills({ distribution, installation, skills });
  assert.deepEqual(
    result.actions.map((action) => action.skill),
    ['ars', 'noctis', 'implement', 'code-review', 'verify'],
  );
  const snapshot = await installationSnapshot({ distribution, installation });
  assert.equal(snapshot.skills.every((skill) => skill.installed), true);
});

test('an empty placeholder directory is installable', async (t) => {
  const { installation } = await context(t);
  await mkdir(path.join(installation.skillsRoot, 'code-review'), { recursive: true });
  const result = await installSkills({
    distribution,
    installation,
    skills: selectSkills(distribution, { skillIds: ['code-review'] }),
  });
  assert.equal(result.actions[0].status, 'installed');
  assert.equal(
    (await readFile(path.join(installation.skillsRoot, 'code-review', 'SKILL.md'), 'utf8'))
      .includes('name: code-review'),
    true,
  );
});

test('preflight conflict prevents partial profile installation', async (t) => {
  const { installation } = await context(t);
  const conflict = path.join(installation.skillsRoot, 'code-review');
  await mkdir(conflict, { recursive: true });
  await writeFile(path.join(conflict, 'mine.txt'), 'user-owned\n');

  await assert.rejects(
    installSkills({
      distribution,
      installation,
      skills: selectSkills(distribution, { profile: 'full' }),
    }),
    (error) => error.code === 'install_conflict' && error.message.includes('code-review'),
  );
  await assert.rejects(readFile(path.join(installation.skillsRoot, 'ars', 'SKILL.md')));
  assert.equal(await readFile(path.join(conflict, 'mine.txt'), 'utf8'), 'user-owned\n');
});

test('managed local changes require explicit backed-up replacement', async (t) => {
  const { installation } = await context(t);
  await installSkills({ distribution, installation, skills: coreSkills() });
  const localFile = path.join(installation.skillsRoot, 'noctis', 'local.txt');
  await writeFile(localFile, 'local change\n');

  await assert.rejects(
    updateSkills({ distribution, installation }),
    (error) => error.code === 'install_conflict'
      && error.details.files.includes('local.txt'),
  );
  const replaced = await updateSkills({
    distribution,
    installation,
    replaceModified: true,
  });
  const action = replaced.actions.find((item) => item.skill === 'noctis');
  assert.equal(action.status, 'replaced');
  assert.equal(replaced.backups.length, 1);
  assert.equal(
    await readFile(path.join(installation.project, replaced.backups[0], 'local.txt'), 'utf8'),
    'local change\n',
  );
});

test('dry run reports without creating installation state', async (t) => {
  const { installation } = await context(t);
  const result = await installSkills({
    distribution,
    installation,
    skills: coreSkills(),
    dryRun: true,
  });
  assert.equal(result.dry_run, true);
  await assert.rejects(readFile(installation.recordPath));
});

test('remove only deletes clean managed skills and preserves modified backups', async (t) => {
  const { installation } = await context(t);
  const verify = selectSkills(distribution, { skillIds: ['verify'] });
  await installSkills({ distribution, installation, skills: verify });
  const clean = await removeSkills({
    distribution,
    installation,
    skillIds: ['verify'],
  });
  assert.equal(clean.actions[0].status, 'removed');
  await assert.rejects(readFile(path.join(installation.skillsRoot, 'verify', 'SKILL.md')));

  await installSkills({ distribution, installation, skills: verify });
  await writeFile(path.join(installation.skillsRoot, 'verify', 'local.txt'), 'keep me\n');
  await assert.rejects(
    removeSkills({ distribution, installation, skillIds: ['verify'] }),
    (error) => error.code === 'install_conflict',
  );
  const backedUp = await removeSkills({
    distribution,
    installation,
    skillIds: ['verify'],
    replaceModified: true,
  });
  assert.equal(backedUp.actions[0].status, 'backed-up');
  assert.equal(
    await readFile(path.join(installation.project, backedUp.backups[0], 'local.txt'), 'utf8'),
    'keep me\n',
  );
});

test('skills directory cannot escape the project', async (t) => {
  const project = await projectFor(t);
  await assert.rejects(
    resolveInstallation(project, '../outside'),
    (error) => error.code === 'usage' || error.code === 'unsafe_path',
  );
  await assert.rejects(
    resolveInstallation(project, path.resolve(project, 'absolute')),
    (error) => error.code === 'usage',
  );
});

test('linked skills ancestors are rejected', async (t) => {
  const project = await projectFor(t);
  const outside = await projectFor(t);
  try {
    await symlink(outside, path.join(project, '.agents'), process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    if (error.code === 'EPERM') {
      t.skip('creating a directory link is not permitted on this host');
      return;
    }
    throw error;
  }
  await assert.rejects(
    resolveInstallation(project),
    (error) => error.code === 'unsafe_path',
  );
});

test('linked transaction directories are rejected before writing outside the project', async (t) => {
  const { installation } = await context(t);
  const outside = await projectFor(t);
  await mkdir(installation.skillsRoot, { recursive: true });
  try {
    await symlink(
      outside,
      path.join(installation.skillsRoot, '.ars-noctis-tmp'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );
  } catch (error) {
    if (error.code === 'EPERM') {
      t.skip('creating a directory link is not permitted on this host');
      return;
    }
    throw error;
  }

  await assert.rejects(
    installSkills({
      distribution,
      installation,
      skills: selectSkills(distribution, { skillIds: ['verify'] }),
    }),
    (error) => error.code === 'unsafe_path',
  );
  assert.deepEqual(await readdir(outside), []);
});

test('doctor separates runtime readiness from installation integrity', async (t) => {
  const { project, installation } = await context(t);
  await installSkills({ distribution, installation, skills: coreSkills() });
  const result = await doctorInstallation({
    distribution,
    installation,
    python: path.join(project, 'missing-python'),
  });
  assert.equal(result.ok, false);
  assert.equal(result.issues.some((issue) => issue.code === 'python_missing'), true);
  assert.equal(result.issues.some((issue) => issue.code === 'modified_skill'), false);
});

test('doctor requirements and checks are driven by the selected skills', async (t) => {
  const { project, installation } = await context(t);
  await installSkills({
    distribution,
    installation,
    skills: selectSkills(distribution, { skillIds: ['verify'] }),
  });
  const result = await doctorInstallation({
    distribution,
    installation,
    python: path.join(project, 'missing-python'),
  });
  assert.equal(result.ok, true);
  assert.equal(result.python, null);
  assert.deepEqual(result.executables, {});
});

test('runtime caches do not count as managed skill modifications', async (t) => {
  const { installation } = await context(t);
  await installSkills({ distribution, installation, skills: coreSkills() });
  const cache = path.join(installation.skillsRoot, 'noctis', 'scripts', '__pycache__');
  await mkdir(cache, { recursive: true });
  await writeFile(path.join(cache, 'runtime.pyc'), 'cache');
  const result = await updateSkills({ distribution, installation });
  assert.equal(result.actions.find((item) => item.skill === 'noctis').status, 'unchanged');
});

test('install record can be read after explicit single-skill installation', async (t) => {
  const { installation } = await context(t);
  await installSkills({
    distribution,
    installation,
    skills: selectSkills(distribution, { skillIds: ['verify'] }),
  });
  const record = await readInstallRecord(installation, distribution, { required: true });
  assert.deepEqual(Object.keys(record.skills), ['verify']);
});

test('prerelease SemVer survives install record and update round trip', async (t) => {
  const { installation } = await context(t);
  const prereleaseDistribution = {
    ...distribution,
    package: { ...distribution.package, version: '0.2.0-beta.1+build.7' },
  };
  assert.equal(isSemVer(prereleaseDistribution.package.version), true);
  assert.equal(isSemVer('0.2.0-01'), false);

  await installSkills({
    distribution: prereleaseDistribution,
    installation,
    skills: selectSkills(prereleaseDistribution, { skillIds: ['verify'] }),
  });
  const record = await readInstallRecord(installation, prereleaseDistribution, { required: true });
  assert.equal(record.skills.verify.version, prereleaseDistribution.package.version);
  const updated = await updateSkills({ distribution: prereleaseDistribution, installation });
  assert.equal(updated.actions[0].status, 'unchanged');
});

test('install record cannot be replaced by a symbolic link', async (t) => {
  const { installation } = await context(t);
  await installSkills({
    distribution,
    installation,
    skills: selectSkills(distribution, { skillIds: ['verify'] }),
  });
  const outside = await projectFor(t);
  const externalRecord = path.join(outside, 'record.json');
  await writeFile(externalRecord, '{}\n');
  await unlink(installation.recordPath);
  try {
    await symlink(externalRecord, installation.recordPath, 'file');
  } catch (error) {
    if (error.code === 'EPERM') {
      t.skip('creating a file link is not permitted on this host');
      return;
    }
    throw error;
  }

  await assert.rejects(
    readInstallRecord(installation, distribution, { required: true }),
    (error) => error.code === 'unsafe_path',
  );
});

test('CLI emits structured success and usage errors', async (t) => {
  const project = await projectFor(t);
  const success = spawnSync(
    process.execPath,
    [BIN, 'init', project, '--skill', 'verify', '--json'],
    { encoding: 'utf8' },
  );
  assert.equal(success.status, 0, success.stderr);
  assert.equal(JSON.parse(success.stdout).actions[0].skill, 'verify');

  const defaultProject = await projectFor(t);
  const nonInteractive = spawnSync(
    process.execPath,
    [BIN, 'init', defaultProject, '--no-interactive', '--json'],
    { encoding: 'utf8' },
  );
  assert.equal(nonInteractive.status, 0, nonInteractive.stderr);
  assert.deepEqual(
    JSON.parse(nonInteractive.stdout).actions.map((action) => action.skill),
    ['ars', 'noctis'],
  );

  const failure = spawnSync(
    process.execPath,
    [BIN, 'init', project, '--skill', 'unknown', '--json'],
    { encoding: 'utf8' },
  );
  assert.equal(failure.status, 2);
  assert.equal(JSON.parse(failure.stderr).code, 'usage');
});
