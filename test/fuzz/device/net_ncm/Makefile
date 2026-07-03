# Focused fuzz harness for the NCM receive path (recv_validate_datagram).
#
# It is self-contained: it #includes src/class/net/ncm_device.c and stubs the
# few usbd/glue symbols, so it does not link the whole device stack.
#
#   make            # build the libFuzzer target: ./net_ncm
#   make regression # build + replay the crafted seed under ASan (no engine)
#   make clean

TOP := ../../../..

CC ?= clang

INC += \
  $(TOP)/src \
  .

CFLAGS += $(addprefix -I,$(INC)) -g -O1 -fsanitize=address

FUZZ_FLAGS := -fsanitize=fuzzer

.PHONY: all regression clean get-deps

all: net_ncm

# No external dependencies (the harness only needs the in-tree NCM driver).
get-deps:

# libFuzzer supplies its own main(), so drop the standalone driver here.
net_ncm: fuzz.c
	$(CC) $(CFLAGS) $(FUZZ_FLAGS) -DNO_MAIN -o $@ $<

# Standalone build with a plain main(): replays the crafted seed and any extra
# corpus files given as arguments. Used as a deterministic regression.
regression: fuzz.c
	$(CC) $(CFLAGS) -o net_ncm_regression $<
	./net_ncm_regression

clean:
	$(RM) -rf net_ncm net_ncm_regression *.dSYM
