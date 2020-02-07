#!/usr/bin/perl

use File::Basename;
use Getopt::Long;

# Reads "ls -[R]l", "tar tv", or "rclone ls" output and sorts it by
# size, with directories showing the total size of all the listed
# items contained within them.

my $whoami = basename $0;
my $usage = "Usage: $whoami [--tartv|--lsl|--rclonels] [input-file]\n";


die $usage if (! GetOptions("tartv" => \$tartv,
                            "lsl" => \$lsl,
                            "rclonels" => \$rclonels));
die "Specify only one of --tartv, --lsl, --rclonels\n"
    if (!!$tartv + !!$lsl + !!$rclonels > 1);

if ($tartv) {
    &set_type('tar');
    $type = 'tar';
} elsif ($lsl) {
    &set_type('ls');
    $type = 'ls';
} elsif ($rclonels) {
    &set_type('rclone');
    $type = 'rclone';
}

sub set_type {
    $type = $_[0];
    if ($type eq 'tar') {
        $size_field = 2;
        $num_fields = 6;
    } elsif ($type eq 'ls') {
        $size_field = 4;
        $num_fields = 9;
    } elsif ($type eq 'rclone') {
        $size_field = 0;
        $num_fields = 2;
    }
    else {
        die "Unrecognized type: $type\n";
    }
}

while (<>) {
    next if (/^total /);
    next if (/^\s*$/);
    chomp;
    @f = split;
    if (! $type) {
        if ($f[1] =~ m,/,) {
            &set_type('tar');
        }
        elsif ($f[4] =~ /^\d+$/) {
            &set_type('ls');
        }
        elsif ($f[0] =~ /^\d+$/) {
            &set_type('rclone');
        }
    }
    if ((! $type or $type eq 'ls') and
        (/^(.*):$/ and (@f < 5 or $f[4] !~ /^\d+$/))) {
        &set_type('ls');
	$file_prefix = $1;
	next;
    }
    if (! $type) {
	die "Could not determine input format from '$_'\n";
    }
    @f = split(' ', $_, $num_fields);
    if (@f < $size_field + 1 or $f[$size_field] !~ /^\d+$/) {
	warn "Skipping unrecognized line: '$_'\n";
	next;
    }
    $size = $f[$size_field];
    $file = ($file_prefix ? "$file_prefix/" : "") . $f[-1];
    $file =~ s,/$,,;
    $sizes{$file} = $size;
}

# Populate missing directories all the way to the root.
foreach $file (keys %sizes) {
    while (dirname($file) ne $file and ! defined($sizes{dirname($file)})) {
        $file = dirname $file;
        $sizes{$file} = 0;
    }
}

foreach $file (reverse sort keys %sizes) {
    if (dirname($file) ne $file) {
	$sizes{dirname($file)} += $sizes{$file};
    }
}

foreach $file (sort { ($sizes{$b} <=> $sizes{$a}) || ($a cmp $b) } keys %sizes) {
    print "$sizes{$file}\t$file\n";
}
