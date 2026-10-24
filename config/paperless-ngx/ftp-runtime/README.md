# Paperless FTP runtime candidate

The deployed FTP sidecar uses `stilliard/pure-ftpd:trixie-1.0.50`. Its seven
critical Trivy IDs are in Perl and MariaDB packages. The Paperless Deployment
uses Pure-FTPd's local `pure-pw` database, not SQL authentication. The upstream
server and `pure-pw` binaries have no dynamic dependency on either package
family in the running image.

This image copies those same version 1.0.50 binaries from a verified upstream
digest into a minimal Debian Trixie runtime with their linked libraries. It
implements the environment variables used by the current deployment and keeps
the passive port range. CI checks the linked libraries and starts a disposable
server, logs in through `pure-pw`, uploads over passive FTP and verifies bytes
on disk. The workflow publishes the runtime stage only after this check passes.

Copying application binaries without their Debian package records can make
Trivy miss a future Pure-FTPd application advisory. The build keeps the exact
upstream source digest in the Dockerfile and the 1.0.50 version assertion, but
release review must still check Pure-FTPd advisories directly. A zero-critical
scan would establish only that the runtime packages have no known critical
findings in the current Trivy database.

Before deployment, resolve and scan the exact published `linux/amd64` digest
with `scripts/resolve-container-image.py` and the shared Trivy cache. Probe it
in an isolated no-token Pod with an emptyDir home and disposable credentials;
verify startup, login, passive upload, file ownership and logs. Keep the real
Paperless consume PVC and scanner password out of this probe. Then take the
normal Paperless media/consume backup before an ArgoCD rollout. Confirm the FTP
sidecar and Paperless are Ready, and check a controlled scanner upload reaches
the consume queue and is processed once.
