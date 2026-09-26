#include "harness/core.hpp"
#include <algorithm>
#include <set>
#include <thread>

namespace harness {
Object tool_schema() {
  Object tools;
  auto add = [&](std::string name, std::string desc, Object props,
                 Array required = {}) {
    tools[name] = Object{{"name", name},
                         {"description", desc},
                         {"inputSchema", Object{{"type", "object"},
                                                {"properties", props},
                                                {"required", required}}}};
  };
  Object integer{{"type", "integer"}}, text{{"type", "string"}};
  add("list_apps", "List running applications available for targeting", {});
  add("select_app", "Select a running app by PID before sending input",
      {{"pid", integer}}, {"pid"});
  add("screenshot",
      "Capture selected app window; coordinates are window-local logical "
      "points",
      {{"include_image", Object{{"type", "boolean"}}},
       {"region",
        Object{{"type", "object"},
               {"properties", Object{{"left", integer},
                                     {"top", integer},
                                     {"width", integer},
                                     {"height", integer}}},
               {"required", Array{"left", "top", "width", "height"}}}}});
  add("screenshot_with_marks",
      "Capture screenshot with numbered accessibility marks", {});
  add("open_app",
      "Open an application in the background and select it as the input target",
      {{"name", text}}, {"name"});
  add("click", "Click at screen coordinates",
      {{"x", integer},
       {"y", integer},
       {"button",
        Object{{"type", "string"}, {"enum", Array{"left", "right", "middle"}}}},
       {"clicks", integer}},
      {"x", "y"});
  add("left_double", "Double click", {{"x", integer}, {"y", integer}},
      {"x", "y"});
  add("right_single", "Right click", {{"x", integer}, {"y", integer}},
      {"x", "y"});
  add("move_mouse", "Move cursor", {{"x", integer}, {"y", integer}},
      {"x", "y"});
  add("scroll", "Scroll; positive dy moves down",
      {{"x", integer}, {"y", integer}, {"dx", integer}, {"dy", integer}},
      {"x", "y"});
  add("drag", "Drag from start to end",
      {{"x1", integer}, {"y1", integer}, {"x2", integer}, {"y2", integer}},
      {"x1", "y1", "x2", "y2"});
  add("type_text", "Type Unicode text", {{"text", text}}, {"text"});
  Object keys{
      {"keys", Object{{"type", "array"}, {"items", text}, {"minItems", 1}}}};
  add("key_press", "Press shortcut keys together", keys, {"keys"});
  add("hotkey", "Press shortcut keys together", keys, {"keys"});
  add("wait", "Wait up to 10000 ms", {{"ms", integer}});
  add("get_screen_info", "Get display bounds and cursor position", {});
  add("finished", "Report visually confirmed completion", {{"summary", text}});
  add("failed", "Report failure", {{"reason", text}});
  add("call_user", "Ask for human input", {{"question", text}}, {"question"});
  return tools;
}

Object Controller::call(const std::string &name, const Object &args) {
  try {
    auto tools = tool_schema();
    if (!tools.contains(name))
      throw std::invalid_argument("Unknown tool: " + name);
    if (!allowlist.empty() &&
        std::find(allowlist.begin(), allowlist.end(), name) == allowlist.end())
      throw std::invalid_argument("Tool not allowed: " + name);
    const auto &schema =
        tools.at(name).as_object().at("inputSchema").as_object();
    for (auto &required : schema.at("required").as_array())
      if (!args.contains(required.as_string()))
        throw std::invalid_argument("Missing argument: " +
                                    std::string(required.as_string()));
    for (auto &[key, value] : args) {
      auto p = schema.at("properties").as_object().if_contains(key);
      if (!p)
        throw std::invalid_argument("Unknown argument: " + std::string(key));
      auto type = str(p->as_object(), "type");
      if ((type == "integer" && !value.is_int64() && !value.is_uint64()) ||
          (type == "string" && !value.is_string()) ||
          (type == "array" && !value.is_array()) ||
          (type == "object" && !value.is_object()) ||
          (type == "boolean" && !value.is_bool()))
        throw std::invalid_argument("Invalid argument: " + std::string(key));
      if (type == "integer" && (value.to_number<double>() < -1000000 ||
                                value.to_number<double>() > 1000000))
        throw std::invalid_argument("Argument out of range: " +
                                    std::string(key));
    }
    if (name == "key_press" || name == "hotkey") {
      auto &keys = args.at("keys").as_array();
      if (keys.empty() || keys.size() > 8)
        throw std::invalid_argument("Expected 1-8 keys");
      for (auto &k : keys)
        if (!k.is_string())
          throw std::invalid_argument("Keys must be strings");
    }
    if (name == "wait" &&
        (number(args, "ms", 1000) < 0 || number(args, "ms", 1000) > 10000))
      throw std::invalid_argument("ms must be between 0 and 10000");
    if (name == "click") {
      auto b = str(args, "button", "left");
      if (b != "left" && b != "right" && b != "middle")
        throw std::invalid_argument("Invalid mouse button");
      if (number(args, "clicks", 1) < 1 || number(args, "clicks", 1) > 3)
        throw std::invalid_argument("clicks must be between 1 and 3");
    }
    if (name == "finished" || name == "failed" || name == "call_user")
      throw std::invalid_argument(
          "Terminal action is only valid in the agent loop");
    if (name == "select_app" && number(args, "pid") <= 0)
      throw std::invalid_argument("Expected a positive application PID");
    if (dry_run) {
      if (name == "select_app")
        target_pid = int(number(args, "pid"));
      Object result{{"ok", true},
                    {"dry_run", true},
                    {"target_pid", target_pid},
                    {"delivery", "simulated"}};
      if (name == "screenshot" || name == "screenshot_with_marks") {
        result["width"] = 1280;
        result["height"] = 800;
        result["scale"] = 1.0;
        result["image_b64"] = "";
        result["origin_x"] = 0;
        result["origin_y"] = 0;
      }
      return result;
    }
    if (name == "wait") {
      std::this_thread::sleep_for(
          std::chrono::milliseconds(int(number(args, "ms", 1000))));
      return {{"ok", true}};
    }
    auto result = native_call(name, args, target_pid);
    if (flag(result, "ok") && (name == "select_app" || name == "open_app"))
      target_pid = int(number(result, "target_pid"));
    return result;
  } catch (const std::exception &e) {
    return {{"ok", false}, {"error", e.what()}};
  }
}
} // namespace harness
