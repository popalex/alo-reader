#!/bin/sh
# Install the pnpm that web/package.json pins in "packageManager", with npm.
#
# Node 25 and later ship without corepack, which is how the Docker image, the dev
# container and CI used to get pnpm. npm comes with every Node, and reading the
# version from package.json keeps one place to change it (Dependabot bumps it there).
# The value can carry a "+sha512..." suffix; npm takes only the version.
set -eu
cd "$(dirname "$0")/.."
version=$(node -p "require('./package.json').packageManager.split('@')[1].split('+')[0]")
npm install --global --no-fund --no-audit --no-update-notifier "pnpm@$version"
