# Gate Makefile, sibling-repo pattern (see 7dtd-server-container): every
# script CI lints is discovered from the tree, and `make test` runs every
# scripts/test_*.sh the day it lands instead of when someone lists it.
SHELL := /bin/bash

ROOT := $(CURDIR)
SB := $(ROOT)/scripts/sb

# Every shell script in the repo (sorted for stable output).
SCRIPTS := scripts/sb scripts/docker-gui.sh $(sort $(wildcard scripts/test_*.sh))
# Every CLI test suite; `test` runs them all.
TESTS := $(sort $(wildcard scripts/test_*.sh))

.DEFAULT_GOAL := test
.PHONY: help lint test doctor fetch-base fetch-server-base
.PHONY: create create-server launch launch-server run stop wipe destroy list env

help:
	@echo "make lint    bash -n + shellcheck over every script"
	@echo "make test    lint + every scripts/test_*.sh (no game needed)"
	@echo "make doctor  sb doctor (base/Proton/reflink readiness)"
	@echo "sb help      full instance CLI"

lint:
	bash -n $(SCRIPTS)
	shellcheck $(SCRIPTS)

test: lint
	set -e; for t in $(TESTS); do echo "== $$t"; bash $$t; done

# --- passthrough conveniences (full CLI: scripts/sb help) ------------------

doctor:
	@$(SB) doctor

fetch-base:
	@$(SB) fetch-base

fetch-server-base:
	@$(SB) fetch-server-base

create:
	@test -n "$(NAME)" || { echo "usage: make create NAME=<instance>"; exit 2; }
	@$(SB) create $(NAME)

create-server:
	@test -n "$(NAME)" || { echo "usage: make create-server NAME=<server>"; exit 2; }
	@$(SB) create-server $(NAME)

run:
	@test -n "$(NAME)" || { echo "usage: make run MODE=<client|server|both> NAME=<instance> [ARGS='-- -connect=...']"; exit 2; }
	@$(SB) run $(if $(MODE),$(MODE),client) $(NAME) $(ARGS)

launch:
	@test -n "$(NAME)" || { echo "usage: make launch NAME=<instance> [ARGS='-- -connect=...']"; exit 2; }
	@$(SB) launch $(NAME) $(ARGS)

launch-server:
	@test -n "$(NAME)" || { echo "usage: make launch-server NAME=<server>"; exit 2; }
	@$(SB) launch-server $(NAME)

stop:
	@test -n "$(NAME)" || { echo "usage: make stop NAME=<instance>"; exit 2; }
	@$(SB) stop $(NAME)

wipe:
	@test -n "$(NAME)" || { echo "usage: make wipe NAME=<instance>"; exit 2; }
	@$(SB) wipe $(NAME)

destroy:
	@test -n "$(NAME)" || { echo "usage: make destroy NAME=<instance>"; exit 2; }
	@$(SB) destroy $(NAME)

list:
	@$(SB) list

env:
	@test -n "$(NAME)" || { echo "usage: make env NAME=<instance>"; exit 2; }
	@$(SB) env $(NAME)
