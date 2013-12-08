#! /bin/bash

set -eux

echo 'hey stdout'
echo 'hey stderr' 1>&2
sleep 5
echo 'done'
