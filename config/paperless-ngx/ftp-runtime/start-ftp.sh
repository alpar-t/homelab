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
if [ -f "$password_file" ]; then
    pure-pw mkdb "$database_file" -f "$password_file"
fi

# pure-pw reads the password twice from stdin. Keep it out of argv and logs.
printf '%s\n%s\n' "$FTP_USER_PASS" "$FTP_USER_PASS" |
    pure-pw useradd "$FTP_USER_NAME" -f "$password_file" -m \
      -d "$FTP_USER_HOME" -u "$user_id" -g "$group_id"
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

exec /usr/sbin/pure-ftpd "$@"
