VERSION = 0.0.1
IMAGE_NAME ?= wonkyto/chore-manager:$(VERSION)
TAILWIND_VERSION = v4.2.4
TAILWIND_BIN = .cache/tailwindcss

UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)
ifeq ($(UNAME_S),Darwin)
  TAILWIND_OS = macos
else
  TAILWIND_OS = linux
endif
ifeq ($(UNAME_M),arm64)
  TAILWIND_ARCH = arm64
else ifeq ($(UNAME_M),aarch64)
  TAILWIND_ARCH = arm64
else
  TAILWIND_ARCH = x64
endif
TAILWIND_URL = https://github.com/tailwindlabs/tailwindcss/releases/download/$(TAILWIND_VERSION)/tailwindcss-$(TAILWIND_OS)-$(TAILWIND_ARCH)

build: css
	docker build --target production -t $(IMAGE_NAME) .
build-pi: css
	docker buildx build --target production --platform linux/arm64 -t $(IMAGE_NAME) -t wonkyto/chore-manager:latest --push .
build-all: css
	docker buildx build --target production --platform linux/amd64,linux/arm64 -t $(IMAGE_NAME) -t wonkyto/chore-manager:latest --push .
lint:
	docker compose run --rm lint
format:
	docker compose run --rm format
run:
	docker compose run --rm --service-ports run
test:
	docker compose run --rm test
pytest:
	docker compose run --rm pytest

$(TAILWIND_BIN):
	@mkdir -p .cache
	curl -fsSL -o $@ $(TAILWIND_URL)
	chmod +x $@

css: $(TAILWIND_BIN)
	$(TAILWIND_BIN) -i src/chore_manager/static/tailwind.input.css -o src/chore_manager/static/app.css --minify

css-watch: $(TAILWIND_BIN)
	$(TAILWIND_BIN) -i src/chore_manager/static/tailwind.input.css -o src/chore_manager/static/app.css --watch

.PHONY: build build-pi build-all lint format run test pytest css css-watch
