#!/usr/bin/env bash
#
# Miscellaneous tests for the command language.

#### Command block
{ which ls; }
## stdout: /bin/ls

#### Permission denied
touch $TMP/text-file
$TMP/text-file
## status: 126

#### Not a dir
$TMP/not-a-dir/text-file
## status: 127

#### Name too long
./0123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789
## status: 127
## OK dash status: 2
## OK bash status: 126

#### External programs don't have _OVM in environment
# bug fix for leakage
env | grep _OVM
echo status=$?
## stdout: status=1

