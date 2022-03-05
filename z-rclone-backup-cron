#!/bin/bash

set -o pipefail
(
if [ -f /etc/default/rclone-backups ]; then
    . /etc/default/rclone-backups
fi

LF=/var/run/rclone-backups.lock
BD=/etc/rclone-backups
SD=/var/lib/rclone-backups
BACKUPS=$BD/*.conf
# Uncomment this to print commands instead of executing them.
#DRYRUN=echo

mkdir -p $SD

# We get 1GB of downloads free per day. Divide that by the number of
# rclone configurations we are doing and allocate that much to each
# configuration for backup verification.

verify_total=$((1024 * 1024 * 1024))
number_of_backups=$(ls $BACKUPS | wc -l)
verify_each=$((verify_total / number_of_backups))

filter_rclone_output() {
    set +e
    # No way to suppress these (https://github.com/ncw/rclone/issues/1646) and
    # they're harmless.
    grep -v "Can't transfer non file/directory"
    # It shouldn't be treated as an error when rclone generates no output.
    true
}
    
backup() {
    local cf tf sf stamp age
    set -e
    set -o pipefail
    cf="$1"; shift
    tf="${cf##*/}"
    sf="$SD/${tf%.conf}.stamp"
    if [ -f $sf ]; then
        stamp=$(stat -c %Y $sf)
    fi
    $DRYRUN rclone-backup --quiet $cf 2> >(filter_rclone_output) |
        sed -e "s/^/$tf:/"
    if [ -n "$stamp" ]; then
        age=$(($(date +%s) - stamp))s
    else
        age=1d
    fi
    $DRYRUN rclone-backup --verify "data=<$verify_each" \
        --verify "age=$age" $cf 2> >(filter_rclone_output) | \
        sed -e "s/^/$tf:/"
    stamp=$(rclone-backup --newest $cf 2> >(filter_rclone_output) |
            sed -n -e 's/.*(@\([0-9]*\)).*/\1/p')
    $DRYRUN touch --date "@$stamp" $sf
}

echo $$ > $LF.$$
if ! ln $LF.$$ $LF; then
    echo "Can't create $LF" 1>&2
    rm -f $LF.$$
    exit 1
fi
rm -f $LF.$$
trap "rm -f $LF" EXIT

num_children=0

for file in $BACKUPS; do
    backup "$file" &
    ((++num_children))
done

ok=true
while ((num_children > 0)); do
    if ! wait -n; then
        ok=false
    fi
    ((num_children--))
done

if $ok; then
    if [ -n "$CANARY" ]; then
        if ! curl --silent "$CANARY" &>/dev/null; then
            echo "curl --silent \"$CANARY\" failed" 1>&2
            exit 1
        fi
    fi
    exit 0
else
    exit 1
fi

# In case the log file is so large that postfix refuses to email it
) 2>&1 | tee /tmp/rclone-backup-cron.log
