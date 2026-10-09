# Whisper functional checks

## Polling and incident confirmation

Poll every 1800 seconds (30 minutes); shared failure grace is 3600 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

The Zabbix functional worker runs every 30 minutes with a 20-second deadline.
`Whisper ASR capabilities` sends only Wyoming `describe` and requires an
installed ASR program/model advertising Hungarian, Romanian and English.
`Whisper HTTP decoder contract` reads `/capabilities`; that bridge endpoint
constructs 100 ms of silent PCM WAV in memory and exercises the same PyAV
decoder/resampler as `/transcribe`, then returns the versioned HTTP contract.
It never sends audio to Wyoming, runs inference, stores audio or touches user jobs.
Requests/responses are bounded and failures contain no returned body/error text.

No credentials, Kubernetes API permissions or NetworkPolicy expansion are needed.
The existing collector egress permits cluster service traffic and Whisper has no
selecting ingress NetworkPolicy. Both requests use the internal Whisper Service.
Deploy the bridge ConfigMap together with the monitor. The pod template includes a bridge-contract annotation so GitOps rolls Whisper
to load the changed script. Sync the ConfigMap before that rollout and verify
the new endpoint before accepting the bridge check.
The old bridge lacks `/capabilities` and deliberately fails the new check.

Wyoming failure means its protocol/capability response is unavailable, malformed,
or lacks an installed multilingual ASR model. Bridge failure means the endpoint
contract or WAV decoder is unavailable; inspect the `whisper-http` container.
Check `whisper` logs/GPU scheduling separately for inference incidents.

This baseline does **not** prove the model was loaded into GPU memory, GPU health,
model size, recognition quality or successful end-to-end transcription. Live
Wyoming metadata advertises the generic `whisper.cpp` model, even though the
Deployment sets `WHISPER_MODEL=small`. Its `installed` flag is advertisement,
not an inference test. Silence inference was intentionally omitted: it can
occupy the single HTTP bridge/GPU and its output is not a reliable speech assertion.
The single-threaded bridge can also time out during legitimate long transcription;
the standard execution-based alert debounce limits transient alerts.

Protocol framing and schema reference:
[Wyoming event implementation](https://github.com/rhasspy/wyoming/blob/master/wyoming/event.py)
and [ASR information schema](https://github.com/rhasspy/wyoming/blob/master/wyoming/info.py).
Deployed metadata was confirmed by a read-only `Describe` through the running
bridge's Wyoming library; no transcription was submitted. The new endpoint was
validated locally, not deployed by this PR.
