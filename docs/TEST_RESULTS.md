# End-to-End Validation Results

Date: 13 September 2026 (IST)

These results record manual end-to-end validation performed by the candidate against the Docker Compose application. Automated coverage and commands are documented separately in the README.

## 1. Policy decisions and policy changes

Status: **Passed**

- Equal-priority matches resolve deterministically as `DENY > REQUIRE_APPROVAL > ALLOW`.
- A higher-priority rule defeats lower-priority matching rules.
- The worker checks the active policy version before execution.
- When a newly activated policy denies a queued action, the worker cancels the job and does not execute the tool.

## 2. Concurrency, retries, and usage controls

Status: **Passed**

- Concurrent approval and rejection attempts produce exactly one winner.
- The second approval decision receives a conflict response.
- Only one execution job is created.
- Another worker can recover a job after its previous worker lease expires.
- Repeating a request with the same idempotency key and payload returns the original request.
- Reusing an idempotency key with a different payload returns `409 IDEMPOTENCY_KEY_REUSED`.
- Two requests competing for the final budget slot produce one success and one `429` response.

## 3. AI security and replay isolation

Status: **Passed**

- Retrieved content containing prompt injection cannot bypass gateway policy.
- Sending sensitive information to an external destination is denied.
- A denied external message creates no execution job or tool effect.
- Replay evaluates historical request facts under another policy version.
- Replay reports `execution_performed: false`.
- Replay neither changes the original request nor executes its tool.

## Outcome

All three manual validation groups passed. Together they exercise deterministic policy resolution, policy changes before execution, transactional approval races, lease recovery, idempotency, atomic usage enforcement, indirect prompt injection controls, sensitive-data controls, and replay isolation.

## Automated regression result

After the manual validation, the automated suite was expanded to cover additional authentication, authorization, lifecycle, approval expiry, simulation isolation, retry, lease, redaction, configuration, and concurrency boundaries. On 13 September 2026, all **38 tests passed against PostgreSQL**, including six database-concurrency tests. The only test-run warning is a deprecation notice from Starlette's test client dependency and does not affect application behavior.
