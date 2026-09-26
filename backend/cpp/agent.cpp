#include "harness/core.hpp"
#include <algorithm>
#include <curl/curl.h>
#include <iomanip>
#include <memory>
#include <regex>
#include <sstream>
#include <thread>

namespace harness {
static Decision from_object(const Object &o) {
  auto name = str(o, "name", str(o, "tool", str(o, "function")));
  if (name.empty())
    throw std::invalid_argument("Missing tool name");
  auto p = o.if_contains("args");
  if (!p)
    p = o.if_contains("arguments");
  if (!p)
    p = o.if_contains("parameters");
  Object args;
  if (p)
    args =
        p->is_string() ? j::parse(p->as_string()).as_object() : p->as_object();
  if (!tool_schema().contains(name))
    throw std::invalid_argument("Unknown model tool: " + name);
  return {name, args};
}

Decision parse_decision(const Object &response) {
  const auto &msg = response.at("choices")
                        .as_array()
                        .at(0)
                        .as_object()
                        .at("message")
                        .as_object();
  if (auto calls = msg.if_contains("tool_calls");
      calls && calls->is_array() && !calls->as_array().empty())
    return from_object(
        calls->as_array().at(0).as_object().at("function").as_object());
  auto content = std::regex_replace(
      str(msg, "content"), std::regex("<think>[\\s\\S]*?</think>"), "");
  // Find balanced JSON objects, respecting escaped quotes and nested argument
  // objects.
  for (size_t start = content.find('{'); start != std::string::npos;
       start = content.find('{', start + 1)) {
    int depth = 0;
    bool quoted = false, escape = false;
    for (size_t i = start; i < content.size(); ++i) {
      char c = content[i];
      if (quoted) {
        if (escape)
          escape = false;
        else if (c == '\\')
          escape = true;
        else if (c == '"')
          quoted = false;
        continue;
      }
      if (c == '"')
        quoted = true;
      else if (c == '{')
        ++depth;
      else if (c == '}' && !--depth) {
        auto candidate = content.substr(start, i - start + 1);
        boost::system::error_code ec;
        auto parsed = j::parse(candidate, ec);
        if (!ec && parsed.is_object())
          return from_object(parsed.as_object());
        break;
      }
    }
  }
  throw std::invalid_argument("Model did not return a valid tool call");
}

static size_t receive(char *ptr, size_t size, size_t nmemb, void *data) {
  auto &out = *static_cast<std::string *>(data);
  size_t bytes = size * nmemb;
  if (out.size() + bytes > 16 * 1024 * 1024)
    return 0;
  out.append(ptr, bytes);
  return bytes;
}

Object request_model(const Object &cfg, const Array &messages, int tokens,
                     const std::function<bool()> &cancelled) {
  static const int initialized = []() {
    return int(curl_global_init(CURL_GLOBAL_DEFAULT));
  }();
  if (initialized)
    throw std::runtime_error("curl initialization failed");
  std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> curl(curl_easy_init(),
                                                           curl_easy_cleanup);
  if (!curl)
    throw std::runtime_error("Cannot initialize HTTP client");
  std::string url = str(cfg, "vlm_base_url");
  while (!url.empty() && url.back() == '/')
    url.pop_back();
  url += "/chat/completions";
  std::string payload = j::serialize(Object{{"model", str(cfg, "vlm_model")},
                                            {"messages", messages},
                                            {"temperature", 0.0},
                                            {"max_tokens", tokens}}),
              response;
  curl_slist *raw = nullptr;
  raw = curl_slist_append(raw, "Content-Type: application/json");
  auto auth = "Authorization: Bearer " + str(cfg, "vlm_api_key");
  raw = curl_slist_append(raw, auth.c_str());
  std::unique_ptr<curl_slist, decltype(&curl_slist_free_all)> headers(
      raw, curl_slist_free_all);
  curl_easy_setopt(curl.get(), CURLOPT_URL, url.c_str());
  curl_easy_setopt(curl.get(), CURLOPT_PROTOCOLS,
                   CURLPROTO_HTTP | CURLPROTO_HTTPS);
  curl_easy_setopt(curl.get(), CURLOPT_HTTPHEADER, raw);
  curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDS, payload.c_str());
  curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDSIZE, long(payload.size()));
  curl_easy_setopt(curl.get(), CURLOPT_WRITEFUNCTION, receive);
  curl_easy_setopt(curl.get(), CURLOPT_WRITEDATA, &response);
  curl_easy_setopt(curl.get(), CURLOPT_CONNECTTIMEOUT, 10L);
  curl_easy_setopt(curl.get(), CURLOPT_TIMEOUT, 120L);
  curl_easy_setopt(curl.get(), CURLOPT_NOSIGNAL, 1L);
  curl_easy_setopt(curl.get(), CURLOPT_NOPROGRESS, 0L);
  curl_easy_setopt(
      curl.get(), CURLOPT_XFERINFOFUNCTION,
      +[](void *ptr, curl_off_t, curl_off_t, curl_off_t, curl_off_t) -> int {
        const auto &f = *static_cast<const std::function<bool()> *>(ptr);
        return f && f() ? 1 : 0;
      });
  curl_easy_setopt(curl.get(), CURLOPT_XFERINFODATA, &cancelled);
  auto rc = curl_easy_perform(curl.get());
  if (rc != CURLE_OK)
    throw std::runtime_error(std::string("Model request failed: ") +
                             curl_easy_strerror(rc));
  long status = 0;
  curl_easy_getinfo(curl.get(), CURLINFO_RESPONSE_CODE, &status);
  if (status < 200 || status >= 300)
    throw std::runtime_error("Model HTTP error " + std::to_string(status));
  return j::parse(response).as_object();
}

static Array image_message(const std::string &prompt, const std::string &b64) {
  Array content{Object{{"type", "text"}, {"text", prompt}}};
  if (!b64.empty())
    content.push_back(
        Object{{"type", "image_url"},
               {"image_url", Object{{"url", "data:image/png;base64," + b64}}}});
  return content;
}

static Decision heuristic(const std::string &instruction,
                          const Array &history) {
  if (!history.empty())
    return flag(history.back().as_object(), "result_ok") &&
                   (str(history.back().as_object(), "delivery") !=
                        "posted_to_pid" ||
                    flag(history.back().as_object(), "eval_ok"))
               ? Decision{"finished",
                          {{"summary", "Requested single action performed"}}}
               : Decision{"failed", {{"reason", "Requested action failed"}}};
  std::smatch m;
  if (std::regex_match(
          instruction, m,
          std::regex("(?:open|launch|start) ([^\\n]+)", std::regex::icase)))
    return {"open_app", {{"name", m[1].str()}}};
  if (std::regex_match(
          instruction, m,
          std::regex("(?:type|write|input) ([\\s\\S]+)", std::regex::icase)))
    return {"type_text", {{"text", m[1].str()}}};
  if (std::regex_match(instruction,
                       std::regex("(?:take a )?screenshot", std::regex::icase)))
    return {"screenshot", {}};
  if (std::regex_match(instruction, m,
                       std::regex("wait(?: ([0-9]+))?", std::regex::icase)))
    return {"wait", {{"ms", m[1].matched ? std::stoi(m[1].str()) : 1000}}};
  return {"failed",
          {{"reason", "Configure a VLM endpoint for this task. Offline mode "
                      "supports open, type, screenshot, and wait only."}}};
}

bool Agent::run(const std::string &instruction, Controller &ctrl,
                const Object &cfg, const Emit &emit,
                const std::function<bool()> &cancelled,
                const std::string &run_dir) {
  const double start = now();
  Array history;
  int reflections = 0;
  bool enabled = !str(cfg, "vlm_base_url").empty();
  auto check = [&]() {
    if (cancelled && cancelled())
      throw std::runtime_error("Task cancelled");
  };
  auto step = [&](std::string type, std::string label, std::string detail,
                  bool reflection = false) {
    std::ostringstream time;
    time << std::fixed << std::setprecision(1) << now() - start << "s";
    emit({{"type", "step"},
          {"step", Object{{"type", type},
                          {"label", label},
                          {"detail", detail},
                          {"time", time.str()},
                          {"is_reflection", reflection}}}});
  };
  auto fail = [&](std::string reason) {
    emit({{"type", "task_failed"}, {"subtask_id", ""}, {"detail", reason}});
    return false;
  };
  emit({{"type", "info"},
        {"input_mode", "targeted"},
        {"target_pid", ctrl.target_pid},
        {"dry_run", ctrl.dry_run},
        {"vlm_enabled", enabled},
        {"message", enabled ? "VLM enabled (" + str(cfg, "vlm_model") + ")"
                            : "Offline single-action mode"}});
  auto frame = [&](const Object &shot, int sequence, const std::string &phase) {
    emit({{"type", "computer_frame"},
          {"sequence", sequence},
          {"phase", phase},
          {"captured_at", now()},
          {"width", number(shot, "width")},
          {"height", number(shot, "height")},
          {"origin_x", number(shot, "origin_x")},
          {"origin_y", number(shot, "origin_y")},
          {"target_pid", ctrl.target_pid},
          {"window_title", str(shot, "window_title")},
          {"image_b64", str(shot, "image_b64")},
          {"dry_run", ctrl.dry_run},
          {"error", str(shot, "error")}});
  };
  for (int index = 0; index < max_steps; ++index) {
    check();
    auto pre = ctrl.call("screenshot");
    frame(pre, index * 2, "observing");
    if (enabled && ctrl.target_pid > 0 && !ctrl.dry_run && !flag(pre, "ok"))
      return fail(str(pre, "error", "Screen capture failed"));
    auto b64 = str(pre, "image_b64");
    if (!run_dir.empty())
      save_image(b64,
                 run_dir + "/step-" + std::to_string(index + 1) + "-pre.png");
    Decision decision;
    if (enabled) {
      std::string perception;
      for (auto &cell : image_grid(b64)) {
        check();
        auto &c = cell.as_object();
        auto label = str(c, "label") +
                     " [x:" + std::to_string(int(number(c, "x"))) + "-" +
                     std::to_string(int(number(c, "x1"))) +
                     ", y:" + std::to_string(int(number(c, "y"))) + "-" +
                     std::to_string(int(number(c, "y1"))) + "]";
        auto response = request_model(
            cfg,
            {Object{{"role", "user"},
                    {"content",
                     image_message("Describe only UI elements literally "
                                   "visible in this crop, in 15 words: " +
                                       label,
                                   str(c, "image_b64"))}}},
            80, cancelled);
        perception += label + ": " +
                      str(response.at("choices")
                              .as_array()
                              .at(0)
                              .as_object()
                              .at("message")
                              .as_object(),
                          "content") +
                      "\n";
      }
      if (!perception.empty())
        step("analyze", "Perceiving screen", perception.substr(0, 300));
      Array recent;
      for (size_t i = history.size() > 8 ? history.size() - 8 : 0;
           i < history.size(); ++i)
        recent.push_back(history[i]);
      auto system =
          "You control a macOS desktop. Complete the task by observing the "
          "selected application's window and calling exactly one tool per "
          "turn. Coordinates are "
          "window-local logical points matching the supplied screenshot. Input "
          "is routed to the selected PID, not the global desktop. "
          "Use list_apps/select_app or open_app if no target is selected. "
          "Never assume an input event was handled merely because it was "
          "posted. "
          "Background input support varies by app. If ignored, call call_user; "
          "there is no global input fallback. Only call finished when the FULL "
          "task is "
          "visually confirmed. On no visible effect try a different approach. "
          "Return ONLY JSON: {\"name\":\"tool_name\",\"args\":{...}}. "
          "Available tools: " +
          j::serialize(tool_schema());
      auto context =
          "TASK: " + instruction + "\nHistory: " + j::serialize(recent) +
          "\nScreen grid: " + perception + "\nAccessibility elements: " +
          (ctrl.dry_run ? "[]" : accessibility_text(ctrl.target_pid)) +
          "\nSelected PID: " + std::to_string(ctrl.target_pid) +
          (reflections ? "\nPrevious action had no visible effect. Try a "
                         "different approach."
                       : "");
      decision = parse_decision(request_model(
          cfg,
          {Object{{"role", "system"}, {"content", system}},
           Object{{"role", "user"}, {"content", image_message(context, b64)}}},
          512, cancelled));
    } else
      decision = heuristic(instruction, history);
    check();
    if (decision.name == "finished") {
      step("verify", "Task complete",
           str(decision.args, "summary", instruction));
      return true;
    }
    if (decision.name == "failed")
      return fail(str(decision.args, "reason", "Task failed"));
    if (decision.name == "call_user") {
      emit({{"type", "call_user"},
            {"question", str(decision.args, "question")}});
      return fail("User input required");
    }
    Object cursor{{"type", "computer_cursor"},
                  {"action", decision.name},
                  {"sequence", index},
                  {"dry_run", ctrl.dry_run}};
    const bool pointing =
        decision.args.contains("x") && decision.args.contains("y");
    const bool dragging = decision.name == "drag";
    if (pointing || dragging) {
      cursor["x"] = number(decision.args, dragging ? "x1" : "x");
      cursor["y"] = number(decision.args, dragging ? "y1" : "y");
      cursor["phase"] = "acting";
      cursor["target_pid"] = ctrl.target_pid;
      cursor["global_x"] = number(pre, "origin_x") + number(cursor, "x");
      cursor["global_y"] = number(pre, "origin_y") + number(cursor, "y");
      emit(cursor);
    }
    auto result = ctrl.call(decision.name, decision.args);
    if (pointing || dragging) {
      cursor["phase"] = flag(result, "ok") ? "settled" : "failed";
      if (dragging && flag(result, "ok")) {
        cursor["x"] = number(decision.args, "x2");
        cursor["y"] = number(decision.args, "y2");
        cursor["global_x"] = number(pre, "origin_x") + number(cursor, "x");
        cursor["global_y"] = number(pre, "origin_y") + number(cursor, "y");
      }
      if (auto actual = result.if_contains("cursor")) {
        cursor["global_x"] = number(actual->as_object(), "x");
        cursor["global_y"] = number(actual->as_object(), "y");
      }
      emit(cursor);
    }
    if (flag(result, "ok") &&
        (decision.name == "open_app" || decision.name == "select_app"))
      emit({{"type", "computer_target"},
            {"target_pid", ctrl.target_pid},
            {"app", str(result, "app")}});
    auto type =
        decision.name == "screenshot" ? "screenshot"
        : decision.name == "wait"     ? "analyze"
        : (decision.name == "open_app" || decision.name == "type_text" ||
           decision.name == "key_press" || decision.name == "hotkey")
            ? "keyboard"
            : "mouse";
    step(type, decision.name,
         flag(result, "ok") ? j::serialize(decision.args)
                            : str(result, "error"),
         reflections > 0);
    for (int elapsed = 0; elapsed < pause_ms; elapsed += 50) {
      check();
      std::this_thread::sleep_for(
          std::chrono::milliseconds(std::min(50, pause_ms - elapsed)));
    }
    auto post = ctrl.call("screenshot");
    frame(post, index * 2 + 1, "observed");
    if (!run_dir.empty())
      save_image(str(post, "image_b64"),
                 run_dir + "/step-" + std::to_string(index + 1) + "-post.png");
    bool ok = flag(result, "ok");
    if (ok &&
        ((type == std::string("mouse") && decision.name != "move_mouse") ||
         str(result, "delivery") == "posted_to_pid"))
      ok = image_difference(b64, str(post, "image_b64")) >= 4;
    history.push_back(Object{{"step", index + 1},
                             {"action", decision.name},
                             {"args", decision.args},
                             {"result_ok", flag(result, "ok")},
                             {"eval_ok", ok},
                             {"delivery", str(result, "delivery")}});
    if (decision.name == "list_apps" || decision.name == "select_app" ||
        decision.name == "open_app")
      history.back().as_object()["result"] = result;
    if (history.size() >= 3) {
      bool repeated = true;
      for (size_t i = history.size() - 3; i < history.size(); ++i) {
        auto &h = history[i].as_object();
        repeated &=
            str(h, "action") == decision.name && h.at("args") == decision.args;
      }
      if (repeated)
        ok = false;
    }
    if (!ok) {
      if (++reflections >= 3)
        return fail("Action had no visible effect three times in a row");
      step("analyze", "Reflection " + std::to_string(reflections) + "/3",
           "Try a different action", true);
    } else
      reflections = 0;
  }
  return fail("Exceeded " + std::to_string(max_steps) +
              " steps without completing the task");
}
} // namespace harness
