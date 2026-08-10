import { createInterface } from 'node:readline/promises';
import path from 'node:path';


export const DEFAULT_SKILLS_DIRECTORY = '.agents/skills';


function ciEnabled(env) {
  if (env.CI === undefined) return false;
  return !['', '0', 'false', 'no'].includes(String(env.CI).trim().toLowerCase());
}


export function shouldRunInitWizard(
  values,
  { input = process.stdin, output = process.stdout, env = process.env } = {},
) {
  return Boolean(
    input.isTTY
      && output.isTTY
      && !ciEnabled(env)
      && !values['no-interactive']
      && !values.json
      && values.profile === undefined
      && (values.skill?.length ?? 0) === 0,
  );
}


function orderedProfiles(distribution) {
  return [
    distribution.defaultProfile,
    ...Object.keys(distribution.profiles).filter(
      (profile) => profile !== distribution.defaultProfile,
    ),
  ];
}


async function selectOne({ question, write, prompt, choices, defaultValue }) {
  while (true) {
    const raw = (await question(prompt)).trim();
    if (raw === '') return defaultValue;
    const numeric = Number(raw);
    if (Number.isInteger(numeric) && numeric >= 1 && numeric <= choices.length) {
      return choices[numeric - 1];
    }
    const named = choices.find((choice) => choice.toLowerCase() === raw.toLowerCase());
    if (named !== undefined) return named;
    write(`Invalid selection. Choose 1-${choices.length} or enter a name.\n`);
  }
}


function parseSkillSelection(raw, skillIds) {
  const value = raw.trim();
  if (value.toLowerCase() === 'all') return [...skillIds];
  const tokens = value.split(',').map((item) => item.trim()).filter(Boolean);
  if (tokens.length === 0) return null;
  const selected = [];
  for (const token of tokens) {
    const numeric = Number(token);
    const id = Number.isInteger(numeric) && numeric >= 1 && numeric <= skillIds.length
      ? skillIds[numeric - 1]
      : skillIds.find((candidate) => candidate.toLowerCase() === token.toLowerCase());
    if (id === undefined) return null;
    if (!selected.includes(id)) selected.push(id);
  }
  return selected;
}


async function selectCustomSkills({ distribution, question, write }) {
  const skillIds = distribution.skills.map((skill) => skill.id);
  write('\nAvailable Skills:\n');
  skillIds.forEach((id, index) => write(`  ${index + 1}) ${id}\n`));
  while (true) {
    const selected = parseSkillSelection(
      await question('Select Skills by number or name (comma-separated, or "all"): '),
      skillIds,
    );
    if (selected !== null) return selected;
    write('Select at least one known Skill.\n');
  }
}


async function confirm({ question, write }) {
  while (true) {
    const answer = (await question('Proceed with installation? [Y/n]: ')).trim().toLowerCase();
    if (answer === '' || answer === 'y' || answer === 'yes') return true;
    if (answer === 'n' || answer === 'no' || answer === 'q' || answer === 'quit') return false;
    write('Enter yes or no.\n');
  }
}


export async function promptInitOptions({
  distribution,
  project,
  skillsDirectory = DEFAULT_SKILLS_DIRECTORY,
  skillsDirectoryExplicit = false,
  question,
  write,
}) {
  const profiles = orderedProfiles(distribution);
  const choices = [...profiles, 'custom'];
  write('Ars-Noctis initialization\n');
  write(`Project: ${path.resolve(project)}\n\n`);
  write('Profiles:\n');
  profiles.forEach((profile, index) => {
    const suffix = profile === distribution.defaultProfile ? ' [default]' : '';
    write(`  ${index + 1}) ${profile}${suffix}: ${distribution.profiles[profile].join(', ')}\n`);
  });
  write(`  ${choices.length}) custom: select individual Skills\n`);

  const profileChoice = await selectOne({
    question,
    write,
    prompt: 'Select a profile [1]: ',
    choices,
    defaultValue: distribution.defaultProfile,
  });
  const custom = profileChoice === 'custom';
  const skillIds = custom
    ? await selectCustomSkills({ distribution, question, write })
    : [...distribution.profiles[profileChoice]];

  let selectedDirectory = skillsDirectory;
  if (!skillsDirectoryExplicit) {
    const answer = (await question(`Skills directory [${skillsDirectory}]: `)).trim();
    if (answer !== '') selectedDirectory = answer;
  }

  write('\nInstallation plan:\n');
  write(`  Skills: ${skillIds.join(', ')}\n`);
  write(`  Destination: ${path.resolve(project, selectedDirectory)}\n`);
  const approved = await confirm({ question, write });
  return {
    canceled: !approved,
    skillsDirectory: selectedDirectory,
    profile: custom ? undefined : profileChoice,
    skillIds: custom ? skillIds : [],
    selectedSkillIds: skillIds,
  };
}


export async function runInitWizard(options) {
  const input = options.input ?? process.stdin;
  const output = options.output ?? process.stdout;
  const terminal = Boolean(input.isTTY && output.isTTY);
  const interface_ = createInterface({ input, output, terminal });
  try {
    return await promptInitOptions({
      ...options,
      question: (prompt) => interface_.question(prompt),
      write: (value) => output.write(value),
    });
  } finally {
    interface_.close();
  }
}
