#!/usr/bin/perl

# Generates to stdout a list of all files containing in RPMs which
# have not been modified since installation.

use strict;
use warnings;

use Cwd 'abs_path';
use Digest::MD5 qw/md5_hex/;
use Digest::SHA qw/sha256_hex/;
use Fcntl ':mode';
use File::Basename;
use File::Slurp;
use File::Spec::Functions;
use Getopt::Long;

my $whoami = basename $0;
my $usage = "Usage: $whoami [--rsync-filter] [--nomd5 [--noprelink-workaround]]
	[--verbose [...]]\n";

my $nomd5 = '';
my $v = 0;
my $prelink_workaround = 1;
my $rsync_filter = 0;

die $usage if (! GetOptions("nomd5" => sub { $nomd5 = "--nomd5"; },
			    "verbose+" => \$v,
			    "prelink-workaround!" => \$prelink_workaround,
                            "rsync-filter" => \$rsync_filter,
	       ));

$prelink_workaround = 0 if (! $nomd5);

# Find paths in all RPMs.  The find the ones that have changed.  Then
# find the ones that have *not* changed by removing the ones that have
# changed from the complete list.  Finally, remove directories from
# the list of unchanged paths, to arrive at a list of files and
# devices which are identical to what's in their RPMs.

my %all_rpm_paths;

print(STDERR "Finding changed RPM paths\n") if ($v);

my(%changed_rpm_paths, %paths_to_prelink);

if (! $prelink_workaround) {
    open(RPM, "-|", "rpm --verify $nomd5 -a 2>&1") or die;
    while (<RPM>) {
	&parse_rpmv_line($_);
    }
    close(RPM) or die;
}

sub parse_rpmv_line {
    local($_) = @_;

    chomp;
    return if (/^missing/);
    return if (/^Unsatisfied dependencies /);
    # JDK bug, already reported to Sun
    return if (/IntegrateWithGNOME: command not found/);
    # prelink bug, already reported to Red Hat
    return if (m,^prelink: /usr/bin/exiv2: prelinked file was modified$,);
    if (/^prelink: (.*): at least one of file\'s dependencies/) {
	$paths_to_prelink{$1} = 1;
    }
    if (! /^[.S]/) {
	warn "Unrecognized output from rpm --verify: $_\n";
	return;
    }
    my($attrs, $path) = split(/\s+\w?\s+/, $_, 2);
    $changed_rpm_paths{$path} = 1;
}

if (%paths_to_prelink) {
    print(STDERR "Prelinking and re-verifying\n") if ($v);
    system("prelink", keys %paths_to_prelink) and die;
    my $pid = open(RPM, "-|");
    if (! defined($pid)) {
	die;
    }
    elsif (! $pid) {
	exec("rpm", "-qf", keys %paths_to_prelink) || die;
    }
    map { delete $changed_rpm_paths{$_}; } keys %paths_to_prelink;
    my %rpms_to_verify;
    while (<RPM>) {
	chomp;
	$rpms_to_verify{$_} = 1;
    }
    close(RPM) or die;
    $pid = open(RPM, "-|");
    if (! defined($pid)) {
	die;
    }
    elsif (! $pid) {
	exec("rpm", "--verify", keys %rpms_to_verify) || die;
    }
    %paths_to_prelink = ();
    while (<RPM>) {
	&parse_rpmv_line($_);
    }
    close(RPM) or die;
    if (%paths_to_prelink) {
	warn "Prelink failed: ", join(" ", keys %paths_to_prelink), "\n";
    }
}

# Need to do this because some config files are explicitly not
# verified by rpm.

if (! $prelink_workaround) {
    print(STDERR "Finding changed config files\n") if ($v);
}

# There's some magic here that warrants explaining.  We want to read
# all of the dump records into memory, so that we can display
# percentages while we're working.  However, we don't want to wait for
# the entire dump to finish before we start processing the output.
# Therefore, we use select to read the dump as it's generated, and
# only start displaying percentages when it's all done.

open(RPM, "-|", "rpm -q --dump -a") or die;
# Read all into memory so we can display percentage complete
my(@dump_lines) = scalar <RPM>;

my($so_far) = 0;
my $count = 0;
my($pct_done) = 0;

while (! $count || @dump_lines) {
    my($changed);

    if (! $count) {
	my $rin = '';
	vec($rin, fileno(RPM), 1) = 1;
	my($rout);
	while (! @dump_lines || select($rout = $rin, undef, undef, 0)) {
	    if (! (my $line = <RPM>)) {
		close(RPM);
		$count = @dump_lines + $so_far;
		last;
	    }
	    else {
		push(@dump_lines, $line);
	    }
	}
    }
    
    last if (! ($_ = shift @dump_lines));

    chomp;
    $so_far++;
    next if (! /(.*) (\d+) (\d+) ([0-9a-f]+) (\d+) (\S+) (\S+) (\d+) (\d+) (\d+) (.*\S)/);
    $all_rpm_paths{$1} = 1;
    my($path, $size, $mtime, $md5sum, $mode, $owner, $group, $isconfig,
       $isdoc, $rdev, $symlink) =
	   ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11 || '');
    next if (! ($prelink_workaround || $isconfig));
    next if ($changed_rpm_paths{$path});
    lstat $path;
    next if (-d _);
    next if (! -e _);
    if (-l _) {
	my $contents = readlink($path);
	if (! $symlink || (readlink($path) ne $symlink)) {
	    $changed = "link contents (rpm $symlink vs. actual $contents)";
	    &changed($isconfig, $changed, $path);
	    next;
	}
    }
    else {
	if (! $prelink_workaround && -s _ != $size) {
	    &changed($isconfig, 'size', $path);
	    next;
	}
	if ((stat(_))[9] != $mtime &&
	    # For some unknown reason, some files have incorrect mtimes but
	    # are otherwise correct, and rpm --verify doesn't report these
	    # files as problematic, perhaps beacuse their mtimes are *earlier*
	    # than the mtimes in the RPM, but that's just a guess.  In any
	    # case, to be paranoid, when mtime turns out to be different,
	    # confirm by checking MD5 checksum as well.
	    ($isconfig || ! S_ISREG((stat(_))[2]) ||
	     (&diff_checksum(scalar read_file($path), $md5sum)))) {
	    &changed($isconfig, 'mtime', $path);
	    next;
	}
	if (getpwuid((stat(_))[4]) ne $owner) {
	    &changed($isconfig, 'owner', $path);
	    next;
	}
	if (getgrgid((stat(_))[5]) ne $group) {
	    &changed($isconfig, 'group', $path);
	    next;
	}
	if ((stat(_))[2] != oct($mode)) {
	    &changed($isconfig, 'mode', $path);
	    next;
	}
	if (! $nomd5) {
	    if (&diff_checksum(scalar read_file($path), $md5sum)) {
		&changed($isconfig, 'md5', $path);
		next;
	    }
	}
    }
}
continue {
    if ($count && $v) {
	my $new_pct = int($so_far / $count * 100);
	if ($new_pct != $pct_done) {
	    print(STDERR "$new_pct% done\n");
	    $pct_done = $new_pct;
	}
    }
}

sub changed {
    my($isconfig, $changed, $path) = @_;
    print(STDERR "Found changed ", ($isconfig ? "config " : ""),
		  "file ($changed): $path\n") if ($v > 1);
    $changed_rpm_paths{$path} = 1;
}

sub diff_checksum {
    my($data, $old_sum) = @_;
    if (! defined $old_sum) {
	return $data ? 1 : 0;
    }
    if (length($old_sum) == 64) {
	sha256_hex($data) ne $old_sum;
    }
    else {
	md5_hex($data) ne $old_sum;
    }
}

print(STDERR "Finding unchanged RPM paths\n") if ($v);

map { delete $all_rpm_paths{$_}; } keys %changed_rpm_paths;

print(STDERR "Extracting non-directories from exclude path list\n") if ($v);

my(@unchanged);

map {
    if (-l $_ || (-e _ && ! -d _)) {
        push(@unchanged, catfile(abs_path(dirname($_)), basename($_)));
    }
} keys %all_rpm_paths;

@unchanged = sort depth_first @unchanged;

if ($rsync_filter) {
    print(STDERR "Collapsing into rsync filter\n") if ($v);
    my(%unchanged);
    my(%dir_has_changed);
    my(%directives);
    foreach my $unchanged (@unchanged) {
        my $dir = dirname($unchanged);
        push(@{$unchanged{$dir}}, basename($unchanged));
        while ($dir ne '/') {
            $dir = dirname($dir);
            $unchanged{$dir} = [] if (! $unchanged{$dir});
        }
    }
    foreach my $curdir (sort depth_first keys %unchanged) {
        $dir_has_changed{$curdir} = 0
            if (! defined($dir_has_changed{$curdir}));
        my(@unchanged_in_dir) = @{$unchanged{$curdir}};
        opendir(DIR, $curdir) or die;
        my(@all_in_dir) = grep((! /^\.\.?$/), readdir(DIR));
        closedir(DIR) or die;
        my(@subdirs) = grep((-d catfile($curdir, $_)), @all_in_dir);
        foreach my $subdir (@subdirs) {
            if (! defined($dir_has_changed{catfile($curdir, $subdir)})) {
                $dir_has_changed{$curdir} = 1;
                last;
            }
        }
        @all_in_dir = grep((! -d catfile($curdir, $_)), @all_in_dir);
        @all_in_dir = grep((! /^\.\#|^#.*#$|~$/), @all_in_dir);
        my(%changed_in_dir);
        map($changed_in_dir{$_}++, @all_in_dir);
        map(delete($changed_in_dir{$_}), @unchanged_in_dir);
        my(@changed_in_dir) = sort keys %changed_in_dir;
        if (@changed_in_dir) {
            my $dir = $curdir;
            while (1) {
                $dir_has_changed{$dir} = 1;
                $dir = dirname($dir);
                last if ($dir eq '/');
            }
        }
        if (! $dir_has_changed{$curdir}) {
            $directives{$curdir} = [
                &filter_line('-', catfile($curdir, '**'))];
            foreach my $subdir (@subdirs) {
                delete $directives{catfile($curdir, $subdir)};
            }
            next;
        }
        if (! @subdirs and @changed_in_dir + 1 < @unchanged_in_dir) {
            $directives{$curdir} = [
                map(&filter_line('+', catfile($curdir, $_)), @changed_in_dir),
                &filter_line('-', catfile($curdir, '*'))];
        }
        else {
            $directives{$curdir} = [map(
                &filter_line('-', catfile($curdir, $_)), @unchanged_in_dir)];
        }
    }
    foreach my $dir (sort depth_first keys %directives) {
        map(print($_), @{$directives{$dir}});
    }
}
else {
    map(print($_, "\n"), @unchanged);
}

sub filter_line {
    my($prefix, $path) = @_;
    $path =~ s/\[/\\[/g;
    return "$prefix $path\n";
}

sub depth_first {
    if (substr($a, 0, length($b) + 1) eq "$b/") {
        return -1;
    }
    if (substr($b, 0, length($a) + 1) eq "$a/") {
        return 1;
    }
    return $a cmp $b;
}
    
exit;
