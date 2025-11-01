# Common test targets for dex-proxy modules
.PHONY: help test-functional test-functional-junitxml test-functional-ci
.PHONY: test-functional-outside test-functional-verbose test-functional-internal
.PHONY: logs-test-xprocess docker-make-test-functional

define docker-build-tests-impl
	cp ../.dockerignore ../.dockerignore.bak && \
	cp ../.dockerignore-tests ../.dockerignore && \
	docker build --ssh default --build-arg DEX_NAME=$(1) -f ../DockerfileTests.dockerfile -t dex-proxy-$(1)-tests .. && \
	mv ../.dockerignore.bak ../.dockerignore
endef

define docker-make-test-functional-impl
	docker run --rm --network host dex-proxy-$(1)-tests make test-functional
endef

define docker-make-test-functional-ci-impl
	docker run --rm --network host -v "$$(pwd)/test_reports:/app/$(1)/test_reports" \
		-v "$$(pwd)/test_reports/.pytest_cache:/app/$(1)/.pytest_cache" dex-proxy-$(1)-tests \
		make test-functional-ci
endef


help:
	@echo "Available targets:"
	@echo "  test-functional             - Run functional test suite (no -s)"
	@echo "  test-functional-junitxml    - Run functional test suite with saving junitxml report"
	@echo "  test-functional-ci          - Run functional test suite with saving junitxml report and pytest log file"
	@echo "  test-functional-outside     - Run functional test suite against externally started dex_proxy"
	@echo "  test-functional-verbose     - Run functional test suite (-s -p no:logging)"
	@echo "  test-functional-internal    - Run functional test suite with --internal-proxy=True"
	@echo "  logs-test-xprocess          - View logs from xprocess"
	@echo "  docker-build-tests          - Build docker image for tests"
	@echo "  docker-make-test-functional - Run tests in Docker container with host networking"

test-functional:
	pytest tests/functional

test-functional-junitxml:
	pytest tests/functional --junitxml=./test_reports/report.xml

test-functional-ci:
	pytest tests/functional --junitxml=./test_reports/report.xml --log-file=./test_reports/pytest.log

test-functional-outside:
	pytest tests/functional/ --outside-proxy-host=localhost --outside-proxy-port=1958

test-functional-verbose:
	pytest -s -p no:logging tests/functional

test-functional-internal:
	pytest -s -p no:logging --internal-proxy=True tests/functional

logs-test-xprocess:
	less ./.pytest_cache/d/.xprocess/dex_proxy_process/xprocess.log
