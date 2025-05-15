# Prepend project root to PYTHONPATH. Project root is two levels up from this Makefile (dexes/kuru/Makefile).
# This ensures that 'dexes' can be imported as a top-level package.
export PYTHONPATH := ../../:$(PYTHONPATH)

test:
	pytest tests/

test-file:
ifndef FILE
	$(error FILE is not set. Usage: make test-file FILE=<path_to_test_file>)
endif
	pytest $(FILE)

test-it:
	pytest -s -p no:logging ./tests/it/

test-unit:
	pytest -s -p no:logging ./tests/unit/

test-e2e:
	pytest -s -p no:logging ./tests/e2e/

test-aiohttp:
	pytest -s -p no:logging ./tests/aiohttp/

test-functional:
	pytest -s -p no:logging ./tests/functional/


test-all:
	pytest ./tests/

test-all-verbose:
	pytest -s -p no:logging ./tests/

start-dex-proxy:
	cd ../../ && python3 dex_proxy.py -s -c ./dexes/kuru/kuru.local.config.json -n kuru
	

libsigner-install:
	curl -L --fail-with-body -o ./libsigner.tar.gz --user "gitlab-com-auros-starknet-signing-cpp-ro:gldt-JBMfUTUU6yEt6HKxymfH" https://gitlab.com/api/v4/projects/57964836/packages/generic/starknet-signing-cpp/b952e640/starknet-signing-cpp-x86_64.b952e640.tar.gz \
      && echo 80fda92f221dbcec96a82760ecf2a0f44f4d8c5baf951fc581d48d8f0ed2a892 libsigner.tar.gz >> libsigner-shasums.txt \
      && sha256sum -c libsigner-shasums.txt \
      && tar xf libsigner.tar.gz -C ../../.venv/lib/python3.10/site-packages/ \
      && rm libsigner-shasums.txt \
      && rm libsigner.tar.gz

.PHONY: test test-file test-it test-unit test-e2e test-aiohttp test-functional
