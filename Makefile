CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror -ffp-contract=off
CORE = csrc/graph.c csrc/signature.c csrc/risk.c
PYTHON ?= python3

.PHONY: ext test test-c test-c-asan clean

ext:
	$(PYTHON) setup.py build_ext --inplace

test: ext test-c
	$(PYTHON) -m pytest

test-c: build/test_core
	./build/test_core

test-c-asan: $(CORE) csrc/test_core.c csrc/sd_core.h
	mkdir -p build
	$(CC) -std=c11 -g -O1 -Wall -Wextra -fsanitize=address,undefined -fno-omit-frame-pointer \
		-Icsrc -o build/test_core_asan csrc/test_core.c $(CORE)
	./build/test_core_asan

build/test_core: $(CORE) csrc/test_core.c csrc/sd_core.h
	mkdir -p build
	$(CC) $(CFLAGS) -Icsrc -o $@ csrc/test_core.c $(CORE)

clean:
	rm -rf build smartdiff_li/_core*.so smartdiff_li/_core*.pyd
