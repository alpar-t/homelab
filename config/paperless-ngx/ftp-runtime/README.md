# Paperless FTP runtime candidate

The deployed FTP sidecar uses `stilliard/pure-ftpd:trixie-1.0.50`. Its seven
critical Trivy IDs are in Perl and MariaDB packages. The Paperless Deployment
uses Pure-FTPd's local `pure-pw` database, not SQL authentication. The deployed
server and `pure-pw` binaries have no dynamic dependency on either package
family. The upstream 1.0.54 release adds PureDB and other security hardening,
so this candidate upgrades the server as well as slimming the runtime.

The build verifies the signed upstream 1.0.54 tag resolves to commit
`3fe02789c4f0e5756f3f612e32edee9aa5d49455` and compiles PureDB and TLS
support. Only the server and `pure-pw` binaries move into the Alpine 3.23
runtime. It implements the environment variables used by the current
deployment and keeps the passive port range. CI checks linked libraries and
starts a disposable server, logs in through `pure-pw`, uploads over passive FTP
and verifies bytes on disk. The workflow publishes the runtime stage only after
this check passes.

Compiling application binaries without a distribution package record can make
Trivy miss a future Pure-FTPd application advisory. The image labels and
Dockerfile keep the exact upstream source commit, and the build checks that
the signed 1.0.54 tag still resolves to it. Release review must still check
Pure-FTPd advisories directly.
A zero-critical scan would establish only that the runtime packages have no
known critical findings in the current Trivy database.

Before deployment, resolve and scan the exact published `linux/amd64` digest
with `scripts/resolve-container-image.py` and the shared Trivy cache. Probe it
in an isolated no-token Pod with an emptyDir home and disposable credentials;
verify startup, login, passive upload, file ownership and logs. Keep the real
Paperless consume PVC and scanner password out of this probe. Then take the
normal Paperless media/consume backup before an ArgoCD rollout. Confirm the FTP
sidecar and Paperless are Ready, and check a controlled scanner upload reaches
the consume queue and is processed once.
