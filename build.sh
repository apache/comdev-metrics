#!/usr/bin/env bash

# build the site

# Make sure there is a config file
test -r config.yml || cp config.example.yml config.yml

PATH=$PATH:/usr/local/bin # needed for cron jobs

# Provide shortcuts
case "$1" in
    full)
        shift
        # always refresh the repos for the weekly run
        # Although it takes a while, compared with the rest of the run it is fairly insignificant
        uv run asfmetrics --refresh-repos "$@"
        ;;
    bare)
        shift
        uv run asfmetrics --skip-git --skip-mailing-lists "$@"
        ;;
    '') # empty
        echo Expecting "full|bare| or parameters as below:"
        uv run asfmetrics --help
        ;;
    *)
        uv run asfmetrics "$@"
        ;;
esac
