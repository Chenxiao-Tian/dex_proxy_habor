# Include common test targets
include ../common-make.mk

# Module-specific overrides or additional targets can be added below
.PHONY: docker-build-tests docker-make-test-functional

docker-build-tests:
	$(call docker-build-tests-impl,drft)

docker-make-test-functional:
	$(call docker-make-test-functional-impl,drft)

docker-make-test-functional-ci:
	$(call docker-make-test-functional-ci-impl,drft)
