#!/usr/bin/env perl

use File::Slurp;

$max_size = 30000000;

@old_chunks = glob("*");
@new_chunks = ();

$current_name = "";
$table_num = 1;

sub redirect {
    my($name) = @_;

    if ($current_file) {
        if (-f $current_file) {
            $old_data = read_file($current_file);
        }
        else {
            $old_data = '';
        }
        if ($current_output ne $old_data) {
            write_file($current_file, $current_output);
        }
    }

    if ($name) {
        if ($current_name ne $name) {
            $chunk_num = 1;
            $current_name = $name;
        }
    }
    if ($chunk_num > 1) {
        $chunk_suffix = sprintf("-%03d", $chunk_num);
    }
    else {
        $chunk_suffix = "";
    }
    $chunk_num++;
    $current_file = sprintf("%03d-%s%s", $table_num++, $current_name,
                            $chunk_suffix);
    push(@new_chunks, $current_file);
}

redirect("HEADER");
$current_output = '';
$size = 0;

while (<>) {
    if (/^-- Table structure for table `(.*)`/) {
        redirect($1);
        $current_output = '';
        $size = 0;
    }
    if ($size and $size + length > $max_size) {
        redirect();
        $current_output = '';
        $size = 0;
    }
    $current_output .= $_;
    $size += length;
}

redirect("FINISHED");

map($new_chunks{$_}++, @new_chunks);
for (@old_chunks) {
    if (! $new_chunks{$_}) {
        unlink($chunk);
    }
}
