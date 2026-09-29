#!/usr/bin/env bash

# build the site

# Make sure there is a config file
test -r config.yml || cp config.example.yml config.yml

# Provide shortcuts
case "$1" in
    full)
        shift
        uv run asfmetrics "$@"
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
