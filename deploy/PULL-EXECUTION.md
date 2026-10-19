# Outbound Local Execution

The remote gateway persists authenticated API submissions in its private
`execution-queue` volume. The Mac initiates HTTPS requests to claim them. This
mode does not require an inbound ZeroTier connection to the Mac. Model login
credentials stay on the Mac; the gateway only knows its separate bridge token.

The canonical paper, model configuration, comments, revision logs and source Git
history remain in the existing local workspace. Four transport slots relay reads
and short API submissions; the existing project job lock still allows only one
AI writer per paper. This is not four concurrent model calls. Existing model
selection is preserved: the transport does not silently enable expensive models.

## Delivery Guarantees

- Requests are atomically persisted before queue acknowledgement.
- Stable request IDs reject reuse with different payloads.
- A worker records dispatch before calling the local API, then stores the response
  before acknowledging the gateway. Lost acknowledgements reuse this response.
- A crash between dispatch and receipt is explicitly unconfirmed and never
  automatically replayed. This avoids duplicate paid model calls; it is not an
  exactly-once guarantee across arbitrary failures.
- Queued explicit AI jobs carry the source revision and are rejected before model
  use if the paper has changed. Existing patch validation, compilation and Git
  history remain responsible for publication.
- Queued reads expire after 90 seconds; unclaimed writes expire after 24 hours.
  Gateway write receipts remain 24 hours. Local write receipts remain at least
  seven days and are pruned at worker startup. Canonical job/version logs are not
  deleted by queue cleanup. Claimed ambiguous tasks are not silently reassigned.
- Gateway queue capacity is 1,000 records; request bodies are limited to 128 MiB.
  This is a transport resource guard, not source-text truncation.

## Install And Recover

Follow `../docs/INSTALL.md` and start the Node.js gateway directly with
`TEAM_QUEUE_DIR` pointing to its persistent private directory. Do not run a
second independent workspace database against the same team entry point.
Run `node deploy/install-pull-worker.mjs` on the Mac. Its LaunchAgent is
`com.autopaperreview.pull-worker`; logs are in the existing private logs directory.
Its lock prevents simultaneous worker processes on the same Mac.

The browser displays executor connectivity and unconfirmed queue counts. Pending
submissions continue after the browser closes. Refresh and inspect comments and
revision logs before resubmitting. The queue is team-scoped, not per-person access
control. A new browser requires only team login, not native model credentials.

If the temporary public URL changes, update `access.origin` in the existing
private bridge configuration and restart the worker. Back up the queue volume
alongside the existing local workspace. Never place either in the public `dist`.

Verification must distinguish local synthetic tests from deployment acceptance.
Tests use fake local responses, not paid models or the formal manuscript. Confirm
public queue heartbeat and a real read through the outbound worker before claiming
the remote deployment works. An offline gateway or powered-off Mac still cannot
execute models; queueing preserves the request, not instantaneous execution.
