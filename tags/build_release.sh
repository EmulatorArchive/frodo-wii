#!/bin/sh

if [ $# -lt 1 ]; then
    echo "Usage: build_release.sh DIR"

    exit 1
fi

DIR=`basename $1`

find $DIR | xargs chmod a+r
find $DIR -type d | xargs chmod a+x
find $DIR -type f -and -name "shcov" | xargs chmod a+x
find $DIR -type f -and -name "shlcov" | xargs chmod a+x

# Exclude generated stuff and svn things
tar --exclude="*~" --exclude="*.pyc" --exclude="*.pyo" --exclude=".svn*" -czf $DIR.tar.gz $DIR
