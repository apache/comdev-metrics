#!/usr/bin/env bash

# build the site

OPT=$1
echo "Started $OPT build at $(date)"

# Make sure there is a config file
test -r config.yml || cp config.example.yml config.yml

PATH=$PATH:/usr/local/bin # needed for cron jobs

# Provide shortcuts
case "$OPT" in
    weekly)
        shift
        # always refresh the repos for the weekly run
        # Although it takes a while, compared with the rest of the run it is fairly insignificant
        uv run asfmetrics --refresh-repos "$@"
        ;;
    daily)
        shift
        uv run asfmetrics --skip-git --skip-mailing-lists "$@"
        ;;
    '') # empty
        echo Expecting "weekly|daily| or parameters as below:"
        uv run asfmetrics --help
        ;;
    *)
        uv run asfmetrics "$@"
        ;;
esac

echo "Ended $OPT build at $(date)"
