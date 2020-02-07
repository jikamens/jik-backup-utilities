#!/bin/bash -e

PATH=/usr/local/bin:$PATH

# Set "V" to "true" for verbose output.
V=false
NFLAG=

while [ "$*" ]; do
    case "$1" in
	-v|--verbose)
	    shift
	    V=true
	    ;;
	-n|--dry-run|--dryrun)
	    shift
	    NFLAG=--dry-run
	    ;;
	-*)
	    echo "Bad arg: $1" 1>&2
	    exit 1
	    ;;
	*)
	    echo "Extra arguments: $*" 1>&2
	    exit 1
	    ;;
    esac
done

# Set the following three variables to the username, hostname and
# directory in which you want to store the remote backup. If you are
# running the script automatically, e.g., in a cron job or in
# /etc/cron.daily, then you need to make sure that ssh has the ability
# to log in as this user on this host without a password, e.g., by
# creating an SSH key with no passphrase whose public key is in the
# .ssh/authorized_keys file for the user and whose private key is
# listed in root's .ssh/config on your VPS.
# 
# For additional security you may wish the remote user to run inside a
# chroot environment, but setting that up is complicated and beyond
# the scope of this posting.

REMOTE_USER=bkupuser
REMOTE_HOST=bkuptarget.example.com
REMOTE_DIR=backup
IDENTITY_FILE=/root/.ssh/id_backup

# Search for "CONFIG:" below to find additional configuration you may
# wish to change.

export RSYNC_RSH="ssh -i $IDENTITY_FILE"

D=/tmp/backup.$$
mkdir $D

cp /dev/null $D/filter

$V && echo "Creating filter"

cat >> $D/filter <<EOF
- .spamtrain.lock
- .#*
- #*#
- *~
- dead.letter
- procmail.log
- /d/mail-backup/***
- /etc/udev/hwdb.bin
- /home/jane/.tmda/logs/*
- /home/jane/.tmda/pending/*
- /home/*/Mail/bogospam*
- /home/*/Mail/notspam*
- /home/john/.cpan
- /home/john/rpmbuild/BUILD
- /home/john/rpmbuild/BUILDROOT
- /home/john/build
- /home/john/public_html/wordpress/wp-content/cache/*
- /home/john/tmp
- /home/mtm/Mail/from*
- /home/mtm/Mail/msgid.cache*
- /home/ngp/Mail/allmail*
- /home/ngp/Mail/from*
- /home/ngp/Mail/msgid.cache*
- /home/rhj/stmp/admin/tmp.rhj
- /root/.cpan
- /root/rpmbuild/BUILD
- /root/rpmbuild/BUILDROOT
- /swapfile
- /tmp
- /usr/lib/locale/locale-archive
- /usr/libexec/webmin
- /usr/src/redhat/BUILD
- /usr/src/redhat/BUILDROOT
- /var/cache/*
- /var/lib/fail2ban
- /var/lib/imap
- /var/lib/mlocate
- /var/lib/news/history.*
- /var/lib/php/session
- /var/lib/webalizer/dns_cache.db
- /var/lib/yum
- /usr/local/share/man
+ /var/log/rpmpkgs
- /var/log/*
- /var/named/chroot
- /var/run
+ /var/spool/at/***
+ /var/spool/cron/***
- /var/spool/imap/**/Deleted Items
- /var/spool/imap/**/Deleted Messages
- /var/spool/imap/**/Trash
- /var/spool/imap/**/despam
- /var/spool/imap/**/isspam
- /var/spool/imap/**/*maybespam
- /var/spool/imap/**/spamcop
- /var/spool/imap/**/*spamtrain
- /var/spool/imap/**/cyrus.squat
- /var/spool/imap/**/cyrus.index
- /var/spool/imap/**/cyrus.cache
- /var/spool/imap/stage./***
- /var/spool/imap/j/user/johntest/***
+ /var/spool/imap/***
- /var/spool/*
- /var/tmp
- /var/www/blog.example.com/wp-content/themes/swatch/cache/*
EOF

unchanged-rpm-files.pl --rsync-filter --nomd5 $($V && echo "--verbose") \
    >> $D/filter

$V && echo "Adding core files to filter"

locate '*/core' '*/core.[0-9]*' |
while read file; do
    if [ ! -f "$file" ]; then
        continue
    fi
    echo "Excluding core file: $file" 1>&2
    echo "- $file" >> $D/filter
done

if $V; then
    echo "Running backup"
    VFLAG=--verbose
fi

rsync --archive --delete --delete-excluded --compress $VFLAG $NFLAG \
    --one-file-system --filter ". $D/filter" \
    / $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/

$V && echo "Cleaning up"

rm -rf $D
