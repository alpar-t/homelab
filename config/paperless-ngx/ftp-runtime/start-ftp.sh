#!/bin/sh
set -eu

: "${FTP_USER_NAME:?FTP_USER_NAME is required}"
: "${FTP_USER_PASS:?FTP_USER_PASS is required}"
: "${FTP_USER_HOME:?FTP_USER_HOME is required}"

user_id="${FTP_USER_UID:-1000}"
group_id="${FTP_USER_GID:-1000}"
public_host="${PUBLICHOST:-127.0.0.1}"
passive_ports="${FTP_PASSIVE_PORTS:-30000:30009}"
max_clients="${FTP_MAX_CLIENTS:-5}"
max_connections="${FTP_MAX_CONNECTIONS:-5}"
password_file=/etc/pure-ftpd/passwd/pureftpd.passwd
database_file=/etc/pure-ftpd/pureftpd.pdb

mkdir -p /etc/pure-ftpd/passwd "$FTP_USER_HOME"

# Follow upstream's password-file input path. The file is private and removed
# immediately; the password never appears in a process argument or log.
umask 077
password_input=$(mktemp)
trap 'rm -f "$password_input"' EXIT
printf '%s\n%s\n' "$FTP_USER_PASS" "$FTP_USER_PASS" > "$password_input"
pure-pw useradd "$FTP_USER_NAME" -f "$password_file" \
    -d "$FTP_USER_HOME" -u "$user_id" -g "$group_id" < "$password_input"
pure-pw mkdb "$database_file" -f "$password_file"
echo "PureDB user ready"
rm -f "$password_input"
trap - EXIT
chown "$user_id:$group_id" "$FTP_USER_HOME"

set -- -l "puredb:$database_file" -E -j -R \
    -P "$public_host" -p "$passive_ports" \
    -c "$max_clients" -C "$max_connections"

# The deployment currently supplies '-d -d'. Treat it as option words, as
# upstream's run.sh does, while leaving the password out of shell arguments.
if [ -n "${ADDED_FLAGS:-}" ]; then
    # Intentional splitting of trusted deployment flags.
    set -- "$@" $ADDED_FLAGS
fi

echo "Starting Pure-FTPd"
exec /usr/sbin/pure-ftpd "$@"
