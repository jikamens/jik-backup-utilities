# Tools for doing encrypted backups to Backblaze B2 using rclone

This repository contains the tools I use to back up my data into the
cloud, specifically into an encrypted [rclone][rclone] remote backed
by a [Backblaze B2][B2] bucket.

## My requirements

Whether or not these tools are right for you depends to a large extent
on what your requirements are. Therefore, I outline my own
requirements here, i.e., the specific problems I solve with my backup
tools.

My computing environment has the following data locations that need to
be backed up:

* a [Linode server][linode] which runs my mail server, my blog, my
  wife's blog, an NNTP server, some databases (MongoDB, MySQL) that I
  care about, and moderation software for several Usenet newsgroups;

* an iMac which my kids keep files on indiscriminately without paying
  any attention to whether they're on the local hard drive or in a
  backed-up location such as Dropbox;

* a Synology NAS which contains our family photo and video archive,
  other important data that we don't want to use, and some data that
  we don't particularly care about; and

* my Linux desktop computer, which has some other MongoDB and MySQL
  databases that I care about, and my home directory that I care a lot
  about.

My requirements for backup are as follows:

* Data that's worthy of being backed up should be backed up twice:
  once to on-site storage for quick restores in case of hardware loss
  or failure, and once to off-site storage in case of catastrophe
  (e.g., our house is burglarized or destroyed).

* I need to be able to exclude files from on-site backups.

* I need to be able to exclude additional files from off-site backups,
  over and above the files excluded from on-site backups.

* Backups need to be incremental. I'm worrying about hundreds of
  gigabytes of data; there's no way in hell I can do complete backups
  every day.

* Previous versions of modified files and deleted files need to be
  preserved for some period of time before they are permanently
  expunged.

* Off-site backups need to be encrypted.

* I need to be able to see what's taking up space in my backups, so
  that I can adjust my exclude rules as needed to stop backing up
  space hogs that don't need to be backed up.

* Backups need to run automatically once they're configured and need
  to let me know if something is going wrong.

* The integrity of backed-up data needs to be verified automatically
  as part of the backup process so that I will have confidence that I
  will be able to restore data from backup when I need to.

* I want to pay as little as possible for storage.

* Most people prefer a user-friendly backup service with a graphical
  user interface built by somebody else. I prefer a command-line
  backup system that I built myself, so that I know exactly what is
  doing, I can change its behavior to suit my needs, I can "look under
  the hood" as needed, and I have confidence that it is doing exactly
  what I want it to.

N.B. That last point is very important. If a graphical UI, turnkey
backup solution is more your style, I recommend you walk away from
this repository and check out the personal and business backup
solutions offered by [Backblaze][backblaze].

## My strategy

### Overview

1. My Linode server backs itself up daily using [rsync][rsync] (with a
   large, hand-crafted exclude list) over SSH into a chroot jail on my
   home desktop, into free space on my Linux desktop. This is all
   configured via Ansible playbooks so it's self-documenting and can
   be reconstructed easily if needed.

2. The family iMac backs itself up automatically via Time Machine to
   an external USB drive, and also backs itself up daily exactly to m
   Linux desktop exactly the same as the Linode server (though with a
   different exclude list, obviously).

3. I consider our Synology NAS to be its own on-site backup, given
   that it's configured to use redundant RAID so I won't lose any data
   if one of its hard drives fails as long as I replace the drive
   before a second one fails.

4. I export my PostgreSQL and MongoDB databases nightly into a format
   on which is easier to do reliable incremental backups than the
   output of mongodump, mongoexport, or mysqldump.

5. The important data on my Linux desktop is backed up nightly using
   rsync onto a separate drive.

6. I wrote a wrapper around Rclone which reads a simple configuration
   file and follows the instructions in it -- including Rclone filter
   rules -- to back up a local directory into an encrypted B2 bucket.
   The script also knows how to explicitly verify files in the backup
   (yes, Rclone claims that it does this, but I am paranoid, and while
   I haven't read all of the Rclone source code to have confidence
   that it is doing what it claims, I have read my own verification
   code, and it is simple enough to be easy to understand).

7. A nightly cron job on my Linux desktop calls several instances of
   the Rclone wrapper script on different configuration files to run
   several backups and verifications in parallel. Some of these
   backups are of directories on my NAS which are mounted on my Linux
   desktop via either CIFS or NFS.

8. I used to hae my B2 bucket configured to preserve deleted files for
   a year before purging them automatically, but now I use
   `backblaze-prune-backups` as described below to implement flexible
   backup expiration rules.

Some of the code I'm providing here should be usable out-of-the-box
with essentially no modifications. However, some of it is intended
more as an example than as running code, and you'll probably need to
either use it as inspiration for writing your own stuff, or slice and
dice it a bit to get it working. While I'm happy to provide this code
to people who can benefit from it, I do not have the time or energy to
help you get this code working for other you. This is not intended to
be plug-and-play; rather it's intended to be an assist for people who
can read this code and know what to do with it themselves.

### A note about cron

As described above and in more detail below, all of my automated
backup stuff is driven by cron. Cron captures the output of jobs that
it runs and emails them to the owner of the job. It's important to
ensure that email on your machine is configured in such a way that
these emails will be delivered successfully rather than lost into a
black hole. Otherwise, you won't know if your backup scripts are
generating errors and failing!

In addition to ensuring that your computer is configured to deliver
email sent by cron, you also need to ensure that cron is sending
emails to the correct address. This means putting a MAILTO setting
into the crontab files and/or putting an alias for root in
/etc/aliases, unless you're the kind of person who actually reads
root's email spool in /var/mail.

### Using Jailkit for safe rsync / SSH backups

Several of my machines back themselves up every night automatically
using rsync over SSH to my Linux desktop. I want these backups to be
automated and unattended, which means that the SSH key needed for
these backups needs to be stored without a passphrase on these
machines. However, I don't want to increase my home network's attack
surface by allowing anyone who manages to break into one of these
machines to use the unprotected SSH key to log into my Linux desktop.
I solve this problem by creating a dedicated user on my Linux desktop
for each of these backups and isolating that user inside a minimal
chroot jail, such that if someone does manage to get access to that
SSH key, all they'll be able to gain access to is the backups stored
inside that jail.

If you didn't understand the preceding paragraph, you should probably
stop reading this and go buy yourself an off-the-shelf backup product. ;-)

I use Jailkit for constructing chroot jails on my Linux desktop, i.e.,
the target host for the backups.

You will find the following files here which illustrate how this is
done:

* [`install_jailkit.yml`](install_jailkit.yml) is the Ansible playbook
  I use to install Jailkit on the backup target host.

* [`jk_init_fixer.py`](jk_init_fixer.py) is a script called by
  `install_jailkit.yml` to fix `/etc/jailkit/jk_init.ini` after it is
  installed to remove references to nonexistent library paths.

* [`jailkit_backup.yml`](jailkit_backup.yml) shows how to set up the
  target environment for the backup on the backup target host, and the
  SSH key for the backup on backup source host. Note that in this
  file:

    * `bkuptarget.example.com` is the name of the backup target host

    * `bkupsource.example.com` is the name of the backup source host

    * `/mnt/backup` is the directory on the backup target host in which
      you want to store backups

    * this playbook assumes that home directories are in /home on your
      system, root's home directory is /root, and filesystems are
      controlled by /etc/fstab

* [`rsync-backup.sh`](rsync-backup.sh) is the script run on the backup
  source host to use rsync to do the backup to the target host. You
  will probably want to add to and/or modify the exclude list.

* [`unchanged-rpm-files.pl`](unchanged-rpm-files.pl) is a script
  called by rsync-backup.sh to determine which RPM-controlled files on
  the source host are unmodified from the versions in the RPMs and add
  those files automatically to the exclude list for the backup. If You
  are using a Linux or Unix variant that uses a different package
  format such as deb or Pacman, then you may want to write your own
  version of this script. Alternatively, you can just remove the
  invocation of it from rsync-backup.sh, but then you will probably
  want to add more paths to the hard-coded exclude list so you don't
  waste space backing up OS files that don't need to be backed up (or
  what the heck, you can just back them up and not worry about it,
  since the bandwidth and storage space are probably less valuable
  than your time).

### Exporting MongoDB databases to an incremental-backup-friendly format

The [`mongo-incremental-export.py`][mongo-incremental-export.py]
script takes one or more [MongoDB connection strings][mongourl] as
arguments and exports the specified databases into subdirectories of
the current directory named after the databases. Every document in
every collection in the database is exported into a separate file.
Subsequent runs only export the documents that have been modified.
Restoring a database from this data should be a simple,
straightforward reverse of this export process, though I haven't
bothered to write that script yet since I haven't actually needed to
do such a restore. Some notes about this:

* The script stores a "checksums" file in each collection subdirectory
  of the database directory. These files are used to make the script
  itself run faster, and they should be excluded from backups since
  they're not needed for restores and are not particularly
  incremental-backup-friendly.

* The script puts the exported document files in a directory hierarchy
  that is several levels deep to prevent directories from having too
  many files in them.

* This script is not scalable to extremely large databases, but that's
  OK, because if you've got databases that large, you probably have a
  better way to back them up than this silly little thing. It's
  certainly good enough for the relatively small databases I work
  with.

* The script could be made more scalable by adding configuration code
  to allow it to be told that some collections are write-once, i.e.,
  it's not necessary for the script to revisit documents that have
  already been exported, and/or that some collections have timestamp
  fields that can be used to determine which documents have been
  modified since the incremental export. If you want to do this, I
  will happily accept patches to the code. ;-)

Note that I include all of `/var/lib/mongodb` in my on-site backups
done via rsync, since rsync is smart about scanning these files for
changed blocks and only copying them over into the backup. This
incremental export is only used for the off-site backups done via
Rclone to B2. This is necessary (as I understand it) because Rclone
isn't as good as rsync is at doing block-based incremental backups.

I run this script on the databases I want to export in a cron job that
runs every night prior to my Rclone backup job.

### Exporting MySQL databases to an incremental-backup-friendly format

The [mysql-dump-splitter.pl](mysql-dump-splitter.pl) script plays a
role similar to mongo-incremental-export.py, but for MySQL databases.
Basically, it reads mysqldump output on stdin or from a file specified
on the command line and splits it into separate files in the current
directory, such that each table in the dump is in a separate file.
These files are numbered and can easily be recombined with cat to
recreate the original dump file which can be executed as a SQL script
to recreate the database.

The splitting makes it more likely -- albeit not guaranteed -- that
Rclone will be able to back up the data incrementally.

I run mysqldump and feed the output into this script from a nightly
cron job that runs before my Rclone backup job.

Just like for MongoDB, I actually back up all of `/var/lib/mysql` in
my on-site backups; the purpose of this split backup is for more
efficient off-site backup.

### Wrapper script around rclone

The script [rclone-backup](rclone-backup) is my wrapper around Rclone.
It can use any source or destination type supported by Rclone, so
although I'm using local directories as the source and a crypt remote
backed by a B2 bucket as the destination, you should be able to use
this script with other source and destination types if you want.

The configuration files read by this script look like this:

        [default]
        source=source-directory-or-rclone-location
        destination=target-directory-or-rclone-location
        archive_specials=yes|no
        copy_links=yes|no

        [filters]
        list rclone filters here, as documented at
        https://rclone.org/filtering/

        [test-filters]
        list rclone filters here, as documented at https://rclone.org/filtering/ (see below for what these are for)

The `archive_specials` setting is a hack to work around the fact that
Rclone doesn't know how to handle special files (e.g., devices and
named pipes). When it's set to a true-ish value (the default), before
rclone-backup does the sync it finds all of the special files in the
source and saves a tar file containing them called
"special-files.tar.gz" at the root of the source directory.

The `copy_links` setting tells rclone-backup whether to tell rclone to
attempt to copy symbolic links. It defaults to false if not specified.
It can also be specified on the command line as `--copy-links`.

In addition to reading the configuration file to find out what to do,
rclone-backup also takes the following command-line options:

* `--help` -- print a usage message and exit
* `--verbose` -- be more verbose itself and also tell rclone to be verbose
* `--quiet` -- tell rclone to be quiet
* `--dryrun` -- show what would be done without actually doing it
* `--copy-links` -- try to copy symbolic links rather than skipping them
* `--rclone-config=`_file_ -- use the specified rclone configuration
  file instead of the default `~/.rclone.conf`
* `--ls` -- call `rclone ls` on the source directory instead of doing
  a sync
* `--verify=`_verify-condition_ -- verify the backup as described
  below instead of doing a sync

#### Using test filters to reduce overhead when auditing space consumption in backups

(**NOTE:** The current version of rclone has the "ncdu" command, which
provides an ncurses interface for exploring the space taken up by the
various files and directories in a remote. Instead of using
`tar-ls-du.pl` as shown below, you may wish to consider doing
something like "`rclone --filter-from <(grep '^[-+]'`
_configuration-file_`) --fast-list ncdu ` _backup-source-directory_".)

The story behind `[test-filters]` in the configuration file revolves
around how one makes sure that one isn't backing up large data that
doesn't need to be backed up, wasting bandwidth, storage space and
(potentially) money. To do this properly, you also need another script
of mine called [`tar-ls-du.pl`](tar-ls-du.pl) (the name is an
historical artifact; when I originally wrote this script it only
supported `ls -l` and `tar tvf` output, but now it also supports
`rclone ls`).

I will illustrate this by way of example.

If you have an rclone-backup configuration file as shown above with a
`[filters]` section indicating which files to include in or exclude from
the backup, then you might run this to find out what's going to take
up the most space in the backup:

><pre>
>rclone --filter-from <(grep '^[-+]' <em>configuration-file</em>) \
>    ls <em>backup-source-directory</em> | \
>tar-ls-du.pl --rclone | sort -n
></pre>

The output produced by this command shows how much space is taken up
by the files and directories that will be included in the backup, with
the space taken up by subdirectories and files in directories included
in their parents' totals.

Now, suppose you're reviewing this output looking for space hogs, and
you see some stuff in the output that yes, it's taking up a lot of
space, but yes, you know that and you want it to be in the backup
anyway, and you don't want to have to keep skipping over it every time
you're doing one of these space audits. You can then put filters to
include this stuff in the `[test-filters]` section of the
configuration file, and those files will no longer be listed in the
audit output.

If you're backing up to B2, then big files and directories aren't all
you have to worry about when auditing your backups to reduce waste.
You also have to worry about smaller files that are modified
frequently, because rclone will preserve previous versions of those
files and not clean them up until you tell it to or your bucket policy
says to purge the old versions. Files that change frequently could
therefore cost you a lot in storage costs even if they aren't terribly
large.

Here's an example of how I would audit for that when setting up a
backup:

><pre>
>rclone --max-age 7d --filter-from <(grep '^[-+]' <em>configuration-file</em>) \
>ls <em>backup-source-directory</em> | tar-ls-du.pl --rclone | sort -n
></pre>

This will audit only files modified within the past seven days. Of
course you can use a longer or shorter time window if you'd like.

#### Verifying backups

As noted above, if you specify "`--verify`" to rclone-backup with a
verify condition, then it will verify that the contents of the backup
destination match the source, by downloading the backed up files from
the destination and comparing them to the source files. The exact form
the verification will take depends on what you specify as the argument
to `--verify`. You can specify multiple verify conditions to enforce
them all In particular:

* "`all`" -- every single file in the backup is verified. Clearly,
  this can take a lot of time and bandwidth if there's a lot of data,
  not to mention money if your backup destination charges for
  downloads as, e.g., S3 and B2 do. So think carefully before using
  this.
* "`data=`_number_" -- up to that many bytes of data in the backup
  will be verified. You can prefix the number by "<" to enforce a hard
  limit (otherwise, the final verified file may push the verify over
  the specified number of bytes) and/or suffix the number by "%" to
  indicate that the specified number should be interpreted as a
  percentage of the total number of bytes of all files in the backup.
* "`files=`_number_" -- up to that many files in the backup will be
  verified. You can suffix the number by "%" to indicate that it's a
  percentage of the total number of files in the backup.
* "`age=`_rclone-age-spec_" -- only files up to the specified age
  (using the same syntax as rclone's "`--max-age`" argument) will be
  verified.

### Nightly backup cron job

The file [z-rclone-backup-cron](z-rclone-backup-cron) is installed in
/etc/cron.daily on my Linux desktop (the name starts with "z" to
ensure that it runs after all of the other daily login tasks). In
addition, `rclone-backup` configuration files for each of the
directories I want to back up to B2 are in the directory
`/etc/rclone-backups`. The script does the following:

* Count the number of backups it is going to run.
* Calculate the amount of data we want to verify from each backup,
  starting with the 1GB of free data downloads that B2 allows per day,
  and dividing by the number of backups.
* Launch a separate background process for each backup, which first
  runs and then verifies the backups.
* Wait until all of the background processes exit.
* If the backup is successful and the `CANARY` variable is set in
  `/etc/default/rclone-backups`, then fetch the specified canary URL
  (see [Coal Mine][coalmine]).

Just to give you some idea of how I'm using this, here are some of the
backups in my `/etc/rclone-backups` directory:

* my wife's CloudStation drive folder from a mounted NAS filesystem.
* a local "isos" directory containing CD and DVD images that I don't
  want to lose because I may not be able to obtain them again.
* the local directories containing the backup sent from my Linode
  server and the family iMac
* the local directory containing the local backup of my desktop (i.e.,
  as noted above, the desktop backs up itself nightly via rsync to an
  internal drive that is separate from the drive being backed up, to
  protect against hard drive failure, and then that backup is what's
  being backed up to B2 by the nightly rclone job)
* my music archive, mounted from the NAS
* the family photo / video archive, mounted from the NAS

Note that all of these backup sources are stable, i.e., none of them
is being actively modified while the nightly rclone backups are
running. This is important to avoid false errors during the backup
verification step.

## Additional scripts for working with backups

Also included here are a number of additional scripts that help with
administering, restoring, and cleaning up backups. Some of these
scripts import two Python modules, [`b2api.py`](b2api.py) and
[`rcloneutils.py`](rcloneutils.py), which you therefore need to put
into a directory in Python's search path where the scripts can find
them.

### `backblaze-prune-backups`: Flexible backup expiration

This script rummages through the encrypted data in my B2 backup
bucket, decrypts the paths of the files backed up in the bucket,
applies path-matching rules to determine the backup retention policy
for every file, and applies that backup retention policy, pruning
deleted files that the policy says should no longer be saved. See the
usage message for the script and the comment in the `policies` section
near the top which explains how retention policies are defined.

Note that a lot of the logic in this script is there to cope with the
fact that my backups are encrypted and therefore paths in the backups
have to be decrypted in order to apply path-matching rules to them.
The script could be modified to bypass the path decryption logic and
just apply the expiration logic for backups in which the paths are not
encrypted, but I haven't bothered to do this since my backups are
encrypted. Perhaps I'll get around to it eventually, or I'll happily
accept a pull request if someone else does.

### `backblaze-recover-backup`: Recover from backup catastrophe

I threw together this script when one of my backups got wiped out by
`rclone-backup` because I was backing up a mounted filesystem and the
backup ran when the filesystem wasn't mounted, causing `rclone-backup`
to think that every file had been deleted and therefore deleting them
all in B2 as well. The only purpose of this script is to go through
all the files in the local directory and undelete any of them that
exist in deleted form in the backup directory.

As above, this script is designed to work with B2 backups with
encrypted file paths but could easily be adjusted to work for backups
with plaintext file paths.

### `rclone-encrypted-cleanup`: Permanently purge files from backup

This script can be used to purge specific files, or all files
underneath a specific directory, from a remote backup. It's useful if
you've discovered that something huge was backed up that shouldn't
have been and you don't want to keep paying to store the deleted file
until `backblaze-prune-backups` gets around to pruning it.

By default the script only cleans up the deleted versions of files,
but you can specify `--purge` to tell it to purge undeleted versions
as well.

As above, this is designed to work with encrypted file paths etc.

### `rclone-encrypted-du`: Calculate space usage in encrypted backup

This feeds the contents of an encrypted remote through the
`tar-ls-du.pl` script described above. You can generate any of three
different output files: a file showing usage for all files both
deleted and undeleted files, one showing just undeleted, and one
showing just deleted. This is useful because you mway want to look at
just undeleted files to determine if you're backing up the right
things, or just at deleted files to determine if you're enforcing the
right expiration policies with `backblaze-prune-backups`.

You can use `rclone ncdu` on an encrypted remote, so that's useful if
you're just interested in looking at undeleted files, but it won't
work with deleted files in a B2 bucket backing an encrypted remote,
so for that you ueed something like this script.

### `rclone-encrypted-restore`: Restore historical backups

This lets you specify an encrypted remote, path within it, and target
directory, and restores either all historical revisions of files
within that path or the revision that was extant at a particular
specified time.

This is obviously limited to revisions that have been preserved, so if
you use `backblaze-prune-backups` then you may not be able to restore
exactly what the files looked like at a specific time.

As above, this is designed to work with encrypted file paths etc.

## A note about offline backups

Off-site backups are not the same as _offline_ backups.

When all of your backups are online, you're vulnerable to an attacker
who gains access to your computer deleting (or encrypting, if it's
RansomWare) not only your canonical data, but also your backups. This
is not necessarily something that a "mass-market" attacker would
bother doing, but if someone is out to get you specifically, they may
very well do this.

For this reason, it's usually wise to periodically write your backups
to offline media such as DVDs or BluRay discs. How to do this is left
as an exercise to the reader.

[B2]: https://www.backblaze.com/b2/cloud-storage.html
[backblaze]: https://backblaze.com/
[coalmine]: https://github.com/quantopian/coal-mine
[rclone]: https://rclone.org/
[linode]: https://www.linode.com/products/standard
[mongourl]: https://docs.mongodb.com/manual/reference/connection-string/
[rsync]: https://rsync.samba.org/
