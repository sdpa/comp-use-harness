#include "harness/core.hpp"
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <thread>
using namespace harness;
static int checks = 0;

static void check(bool condition, const char *description) {
  ++checks;
  if (!condition)
    throw std::runtime_error(description);
}

template <class F> void throws(F f, const char *description) {
  bool threw = false;
  try {
    f();
  } catch (const std::exception &) {
    threw = true;
  }
  check(threw, description);
}

static Object response(std::string text) {
  return {{"choices", Array{Object{{"message", Object{{"content", text}}}}}}};
}

int main() {
  try {
    Orchestrator graph(
        {{"t1", "Open app", "ui_navigator", {}, "pending", "", ""},
         {"t2", "Click play", "ui_navigator", {"t1", "t1"}, "pending", "", ""},
         {"t3", "Verify playback", "verifier", {"t2"}, "pending", "", ""}});
    check(graph.execution_order() == std::vector<std::string>{"t1", "t2", "t3"},
          "Topological ordering with duplicate dependencies");
    graph.complete_subtask("t1");
    check(graph.tasks.at("t1").status == "success", "Completed status");
    graph.fail_subtask("t2");
    check(graph.tasks.at("t2").status == "failed", "Failed status");
    graph.replan_subtask("t2", "Retry");
    check(graph.tasks.at("t2").status == "pending" &&
              graph.tasks.at("t2").goal == "Retry",
          "Replan resets state");
    graph.tasks.at("t1").depends_on = {"t3"};
    throws([&] { graph.execution_order(); }, "Cycles rejected");
    graph.tasks.at("t1").depends_on = {"missing"};
    throws([&] { graph.execution_order(); }, "Unknown dependencies rejected");
    for (
        auto text :
        {R"({"name":"type_text","args":{"text":"nested { braces } and \"quotes\""}})",
         R"(```json
{"name":"type_text","args":{"text":"nested"}}
```)",
         R"(<think>private analysis</think><tool_call>{"name":"type_text","arguments":"{\"text\":\"hello\"}"}</tool_call>)"})
      check(parse_decision(response(text)).name == "type_text",
            "Wrapped and nested model JSON");
    Object structured =
        j::parse(
            R"({"choices":[{"message":{"tool_calls":[{"function":{"name":"wait","arguments":"{\"ms\":1}"}}]}}]})")
            .as_object();
    check(number(parse_decision(structured).args, "ms") == 1,
          "Structured tool call");
    throws([&] { parse_decision(response("I think we are done")); },
           "Unstructured model text must not imply success");
    throws(
        [&] {
          parse_decision(response(R"({"name":"execute_shell","args":{}})"));
        },
        "Unknown model tool rejected");
    Controller ctrl(true);
    check(flag(ctrl.call("type_text", {{"text", "Hello 世界"}}), "ok"),
          "Unicode dry-run typing");
    check(!flag(ctrl.call("click", {{"x", "bad"}, {"y", 1}}), "ok"),
          "Invalid coordinate type rejected");
    check(!flag(ctrl.call("click", {{"x", 1}}), "ok"),
          "Required argument checked");
    check(!flag(ctrl.call("wait", {{"ms", -1}}), "ok"),
          "Negative wait rejected");
    check(!flag(ctrl.call("wait", {{"ms", 10001}}), "ok"),
          "Unbounded wait rejected");
    check(!flag(ctrl.call("key_press", {{"keys", Array{}}}), "ok"),
          "Empty hotkey rejected");
    ctrl.allowlist = {"screenshot"};
    check(!flag(ctrl.call("type_text", {{"text", "x"}}), "ok"),
          "Allowlist enforced in dry-run");
    ctrl.allowlist.clear();
    check(flag(ctrl.call("select_app", {{"pid", 4321}}), "ok") &&
              ctrl.target_pid == 4321,
          "Controller retains explicit target PID");
    check(!flag(ctrl.call("select_app", {{"pid", -1}}), "ok"),
          "Invalid target PID rejected");
    Controller real;
    check(!flag(real.call("click", {{"x", 10}, {"y", 10}}), "ok"),
          "Live input without a target fails without touching the desktop");
    auto file = (std::filesystem::temp_directory_path() /
                 ("harness-test-" + uuid() + ".db"))
                    .string();
    {
      Store store(file);
      store.create("session", "Apostrophe ' Unicode 世界");
      std::vector<std::thread> workers;
      for (int i = 0; i < 4; ++i)
        workers.emplace_back([&] {
          for (int j = 0; j < 10; ++j)
            store.step("session", {{"type", "keyboard"},
                                   {"label", "Type"},
                                   {"detail", "' 世界"},
                                   {"time", "0.1s"}});
        });
      for (auto &worker : workers)
        worker.join();
      store.complete("session", "success", 123);
      check(store.list().size() == 1, "Session list");
      check(store.get("missing").is_null(), "Missing session");
    }
    {
      Store store(file);
      auto session = store.get("session").as_object();
      check(str(session, "status") == "success" &&
                number(session, "elapsed_ms") == 123,
            "Session survives reopen");
      check(session.at("steps").as_array().size() == 40,
            "Concurrent steps retained");
      check(str(session.at("steps").as_array().front().as_object(), "detail") ==
                "' 世界",
            "SQLite binding retains Unicode and quotes");
    }
    std::filesystem::remove(file);
    // Synthetic 16x16 PNGs exercise native image code without screen capture.
    const std::string black =
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAEElEQVR4nGNgGAWjYBTAAA"
        "ADEAABPywr7AAAAABJRU5ErkJggg==";
    const std::string white =
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFElEQVR4nGP4TyJgGNUwqm"
        "H4agAAr639H708R/EAAAAASUVORK5CYII=";
    check(image_difference(black, black) == 0,
          "Identical screenshot evaluation");
    check(image_difference(black, white) > 250,
          "Changed screenshot evaluation");
    auto grid = image_grid(white);
    check(grid.size() == 16, "All perception crops generated");
    check(number(grid.back().as_object(), "x1") == 16 &&
              number(grid.back().as_object(), "y1") == 16,
          "Grid covers image edges");
    check(!str(grid.front().as_object(), "image_b64").empty(),
          "Crop has encoded PNG");
    Agent agent;
    agent.pause_ms = 0;
    Array events;
    auto emit = [&](const Object &e) { events.push_back(e); };
    check(agent.run("type Preserve My CASE", ctrl, {}, emit),
          "Offline single-action loop");
    check(!agent.run("solve an arbitrary task", ctrl, {}, emit),
          "Unsupported offline task reports failure");
    throws([&] { agent.run("wait", ctrl, {}, emit, [] { return true; }); },
           "Cancellation before action");
    agent.max_steps = 0;
    check(!agent.run("wait", ctrl, {}, emit), "Step budget enforced");
    std::cout << checks << " C++ checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL: " << e.what() << '\n';
    return 1;
  }
}
