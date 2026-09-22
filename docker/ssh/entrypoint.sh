#!/bin/sh
set -e

service postgresql start

exec /usr/sbin/sshd -D
