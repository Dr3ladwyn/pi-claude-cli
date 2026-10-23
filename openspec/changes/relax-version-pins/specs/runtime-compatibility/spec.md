## ADDED Requirements

### Requirement: Supported runtime version admission

The bridge SHALL reject Claude CLI below 2.1.285 and Pi below 0.99.1, accept stable versions inside `>=2.1.285 <2.2.0` and `>=0.99.1 <0.100.0` silently, and reject malformed version output before inference or registration.

#### Scenario: Compatible patch

- **WHEN** the executable or host reports the minimum or a later patch in its supported range
- **THEN** initialization succeeds without a version warning

#### Scenario: Older or malformed release

- **WHEN** the executable or host reports an older release or a malformed version
- **THEN** initialization fails with the minimum and supported range in the error

### Requirement: Untested stable release handling

Above-range stable releases SHALL continue with one stderr warning per component per process, including across sessions and registrations. `PI_CLAUDE_CLI_STRICT_VERSION=1` SHALL reject these releases even after a warning, without rejecting in-range releases.

#### Scenario: Repeated newer release

- **WHEN** multiple driver sessions or Pi adapters load versions above their supported range
- **THEN** each component warns once and continues

#### Scenario: Strict mode

- **WHEN** strict mode is enabled and the reported version reaches the exclusive upper bound
- **THEN** initialization fails before inference or registration

### Requirement: Release consistency

Pi peers SHALL match its runtime range, OMP peers SHALL retain `^18.8.6`, and npm, Hermes worker and Python artifacts SHALL share version 0.5.1. SDK 0.3.285 SHALL remain pinned with its paired runtime.

#### Scenario: Prepared distribution

- **WHEN** the package and coordinated worker/Python distributions are built
- **THEN** their metadata agrees on version 0.5.1 and no registry publication is performed
