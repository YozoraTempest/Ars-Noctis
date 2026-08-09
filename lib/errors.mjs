export class ArsNoctisError extends Error {
  constructor(message, { code = 'operation_failed', details = undefined } = {}) {
    super(message);
    this.name = 'ArsNoctisError';
    this.code = code;
    this.details = details;
  }
}

export function fail(message, options = {}) {
  throw new ArsNoctisError(message, options);
}
