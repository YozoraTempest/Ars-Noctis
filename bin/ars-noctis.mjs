#!/usr/bin/env node

const nodeMajor = Number(process.versions.node.split('.')[0]);
if (!Number.isInteger(nodeMajor) || nodeMajor < 22) {
  process.stderr.write(`Ars-Noctis requires Node.js 22 or newer; found ${process.versions.node}.\n`);
  process.exitCode = 1;
} else {
  const { main } = await import('../lib/cli.mjs');
  process.exitCode = await main(process.argv.slice(2));
}
