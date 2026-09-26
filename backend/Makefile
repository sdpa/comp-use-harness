CXX = clang++
CLANG_FORMAT ?= xcrun clang-format
BOOST_PREFIX ?= /opt/homebrew
CPPFLAGS += -Iinclude -isystem $(BOOST_PREFIX)/include
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Wpedantic -MMD -MP
LDLIBS += -lsqlite3 -lcurl -framework AppKit -framework ApplicationServices
BUILD := build
CORE := core store controller agent json native_macos
OBJECTS := $(addprefix $(BUILD)/,$(addsuffix .o,$(CORE)))
CPP_SOURCES := $(wildcard cpp/*.cpp tests/*.cpp)
OBJCXX_SOURCES := $(wildcard cpp/*.mm)
FORMAT_SOURCES := $(CPP_SOURCES) $(OBJCXX_SOURCES) $(wildcard include/harness/*.hpp)
LINT_FLAGS := -std=c++17 -Wall -Wextra -Wpedantic -Werror
.PHONY: all test clean format format-check lint check
all: $(BUILD)/harness $(BUILD)/harness-cli
format:
	$(CLANG_FORMAT) --style=file -i $(FORMAT_SOURCES)
format-check:
	$(CLANG_FORMAT) --style=file --dry-run --Werror $(FORMAT_SOURCES)
# Compiler diagnostics plus path-sensitive Clang static analysis. Both fail on errors.
# Run per translation unit, without generating build or analyzer artifacts.
lint:
	@set -e; for source in $(CPP_SOURCES); do \
		echo "Linting $$source"; \
		$(CXX) $(CPPFLAGS) $(LINT_FLAGS) -fsyntax-only "$$source"; \
		$(CXX) $(CPPFLAGS) $(LINT_FLAGS) --analyze -Xanalyzer -analyzer-werror -Xanalyzer -analyzer-output=text "$$source"; \
	done
	@set -e; for source in $(OBJCXX_SOURCES); do \
		echo "Linting $$source"; \
		$(CXX) $(CPPFLAGS) $(LINT_FLAGS) -fobjc-arc -fsyntax-only "$$source"; \
		$(CXX) $(CPPFLAGS) $(LINT_FLAGS) -fobjc-arc --analyze -Xanalyzer -analyzer-werror -Xanalyzer -analyzer-output=text "$$source"; \
	done
check: format-check lint
$(BUILD):
	mkdir -p $@
$(BUILD)/%.o: cpp/%.cpp | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@
$(BUILD)/native_macos.o: cpp/native_macos.mm | $(BUILD)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -fobjc-arc -c $< -o $@
$(BUILD)/harness: $(OBJECTS) $(BUILD)/server.o $(BUILD)/mcp.o
	$(CXX) $^ $(LDLIBS) -o $@
$(BUILD)/harness-cli: $(OBJECTS) $(BUILD)/cli.o
	$(CXX) $^ $(LDLIBS) -ledit -o $@
$(BUILD)/tests: $(OBJECTS) tests/test_core.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) tests/test_core.cpp $(OBJECTS) $(LDLIBS) -o $@
test: $(BUILD)/harness $(BUILD)/harness-cli $(BUILD)/tests
	./$(BUILD)/tests
	node tests/integration.mjs
	node tests/cli.mjs
clean:
	rm -rf $(BUILD)
-include $(wildcard $(BUILD)/*.d)
