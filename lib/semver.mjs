const NUMERIC_IDENTIFIER = '0|[1-9][0-9]*';
const NON_NUMERIC_IDENTIFIER = '[0-9]*[A-Za-z-][0-9A-Za-z-]*';
const PRERELEASE_IDENTIFIER = `(?:${NUMERIC_IDENTIFIER}|${NON_NUMERIC_IDENTIFIER})`;
const BUILD_IDENTIFIER = '[0-9A-Za-z-]+';

const SEMVER = new RegExp(
  `^(?:${NUMERIC_IDENTIFIER})\\.(?:${NUMERIC_IDENTIFIER})\\.(?:${NUMERIC_IDENTIFIER})`
  + `(?:-${PRERELEASE_IDENTIFIER}(?:\\.${PRERELEASE_IDENTIFIER})*)?`
  + `(?:\\+${BUILD_IDENTIFIER}(?:\\.${BUILD_IDENTIFIER})*)?$`,
);

export function isSemVer(value) {
  return typeof value === 'string' && SEMVER.test(value);
}
