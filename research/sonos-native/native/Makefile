CC ?= cc
CFLAGS ?= -O2 -std=c99 -Wall -Wextra -Werror
LDLIBS = -pthread
UNAME := $(shell uname -s)
ifeq ($(UNAME),Darwin)
LIB = build/libsonos_native.dylib
SHARED = -dynamiclib
else
LIB = build/libsonos_native.so
SHARED = -shared -fPIC
LDLIBS += -lrt
endif
all: $(LIB)
build:
	mkdir -p build
$(LIB): sonos_packet.c sonos_packet.h sonos_sender.c sonos_sender.h | build
	$(CC) $(CFLAGS) $(SHARED) sonos_packet.c sonos_sender.c $(LDLIBS) -o $@
build/test_packet: sonos_packet.c sonos_packet.h test_packet.c | build
	$(CC) $(CFLAGS) sonos_packet.c test_packet.c -o $@
build/test_sender: sonos_packet.c sonos_packet.h sonos_sender.c sonos_sender.h test_sender.c | build
	$(CC) $(CFLAGS) sonos_packet.c sonos_sender.c test_sender.c $(LDLIBS) -o $@
test: build/test_packet build/test_sender
	./build/test_packet
	./build/test_sender
.PHONY: all test
