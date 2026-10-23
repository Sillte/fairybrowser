# AGENTS

This repository is a personal project for exploring Python-based
editor plugin development and software architecture.

Follow the applicable `SPECIFICATION.md` and `DESIGN_POLICY.md` files when modifying the codebase.

## Documentation

- `README.md`: project overview and user-facing documentation.
- `DESIGN_POLICY.md`: design principles and architectural decisions.
- `SPECIFICATION.md`: public contracts and observable behavior.
- `AGENTS.md`: instructions for AI agents working in this repository.

A `DESIGN_POLICY.md` and a `SPECIFICATION.md` apply to its directory and descendants.
More specific policies refine broader policies.

Avoid documenting information that can be reliably recovered from the code or other sources of truth.

## Architecture

- Preserve dependency direction and responsibility boundaries.
- Prefer simple designs over unnecessary abstractions.
- Keep implementation details behind public APIs.
- Avoid unnecessary global state and import-time side effects.

## Testing

- Test public behavior, not implementation details.
- Prefer simple, behavior-oriented tests.
- Avoid unnecessary mocks.
- Prefer synchronization primitives such as `threading.Event` over `sleep` for asynchronous tests.
- Inspect nearby tests before writing new tests.
- Follow existing test conventions and avoid duplicating coverage.
- Do not add tests merely to increase coverage.
- Do not accept multiple exception types unless the public contract explicitly
  allows those alternatives.