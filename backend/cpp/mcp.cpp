#include "harness/core.hpp"
#include <iostream>

namespace harness {
int mcp_main(bool dry) {
  Controller ctrl(dry);
  std::string line;
  while (std::getline(std::cin, line)) {
    j::value id = nullptr;
    Object reply{{"jsonrpc", "2.0"}};
    try {
      auto request = j::parse(line).as_object();
      auto p = request.if_contains("id");
      if (p)
        id = *p;
      auto method = str(request, "method");
      if (!p)
        continue;
      reply["id"] = id;
      Object result;
      if (method == "initialize")
        result = {{"protocolVersion", "2024-11-05"},
                  {"capabilities", Object{{"tools", Object{}}}},
                  {"serverInfo",
                   Object{{"name", "computer-control"}, {"version", "0.3.0"}}}};
      else if (method == "ping")
        result = {};
      else if (method == "tools/list") {
        Array tools;
        for (auto &[name, tool] : tool_schema())
          if (name != "finished" && name != "failed" && name != "call_user")
            tools.push_back(tool);
        result["tools"] = tools;
      } else if (method == "tools/call") {
        auto params = request.at("params").as_object();
        Object args;
        if (auto a = params.if_contains("arguments"))
          args = a->as_object();
        auto output = ctrl.call(str(params, "name"), args);
        result = {{"content", Array{Object{{"type", "text"},
                                           {"text", j::serialize(output)}}}},
                  {"isError", !flag(output, "ok")}};
      } else {
        reply["error"] =
            Object{{"code", -32601}, {"message", "Method not found"}};
        std::cout << j::serialize(reply) << std::endl;
        continue;
      }
      reply["result"] = result;
    } catch (const std::exception &e) {
      reply["id"] = id;
      reply["error"] = Object{{"code", id.is_null() ? -32700 : -32602},
                              {"message", e.what()}};
    }
    std::cout << j::serialize(reply) << std::endl;
  }
  return 0;
}
} // namespace harness
