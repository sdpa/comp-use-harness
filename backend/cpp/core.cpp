#include "harness/core.hpp"
#include <boost/uuid/random_generator.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <chrono>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <set>

namespace harness {
std::string str(const Object &o, const std::string &k, std::string fallback) {
  auto p = o.if_contains(k);
  return p && p->is_string() ? std::string(p->as_string()) : fallback;
}

double number(const Object &o, const std::string &k, double fallback) {
  auto p = o.if_contains(k);
  return p && p->is_number() ? p->to_number<double>() : fallback;
}

bool flag(const Object &o, const std::string &k, bool fallback) {
  auto p = o.if_contains(k);
  return p && p->is_bool() ? p->as_bool() : fallback;
}

double now() {
  return std::chrono::duration<double>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::string uuid() {
  return boost::uuids::to_string(boost::uuids::random_generator()());
}

Object read_config(const std::string &path) {
  if (!std::filesystem::exists(path))
    return {};
  std::ifstream f(path);
  if (!f)
    throw std::runtime_error("Cannot read config");
  std::string s((std::istreambuf_iterator<char>(f)), {});
  return j::parse(s).as_object();
}

void write_config(const std::string &path, const Object &cfg) {
  const auto temp = path + ".tmp";
  {
    std::ofstream f(temp);
    if (!f || !(f << j::serialize(cfg)))
      throw std::runtime_error("Cannot write config");
  }
  std::filesystem::permissions(temp, std::filesystem::perms::owner_read |
                                         std::filesystem::perms::owner_write);
  std::filesystem::rename(temp, path);
}

Object effective_config(Object cfg) {
  for (auto key : {"BASE_URL", "MODEL", "API_KEY"}) {
    std::string env = "COMPUTER_USE_VLM_" + std::string(key), name = "vlm_";
    for (char c : std::string(key))
      name += static_cast<char>(std::tolower(c));
    if (str(cfg, name).empty())
      if (auto p = std::getenv(env.c_str()))
        cfg[name] = p;
  }
  if (str(cfg, "vlm_model").empty())
    cfg["vlm_model"] = "qwen2.5-vl:7b";
  if (str(cfg, "vlm_api_key").empty())
    cfg["vlm_api_key"] = "ollama";
  return cfg;
}

Orchestrator::Orchestrator(std::vector<Subtask> ts) {
  for (auto &t : ts)
    tasks[t.id] = std::move(t);
}

std::vector<std::string> Orchestrator::execution_order() const {
  std::map<std::string, int> degree;
  std::map<std::string, std::set<std::string>> edges;
  for (auto &[id, t] : tasks)
    degree[id] = 0;
  for (auto &[id, t] : tasks)
    for (auto &dep : t.depends_on) {
      if (!tasks.count(dep))
        throw std::invalid_argument("Unknown dependency: " + dep);
      if (edges[dep].insert(id).second)
        ++degree[id];
    }
  std::deque<std::string> ready;
  for (auto &[id, d] : degree)
    if (!d)
      ready.push_back(id);
  std::vector<std::string> order;
  while (!ready.empty()) {
    auto id = ready.front();
    ready.pop_front();
    order.push_back(id);
    for (auto &next : edges[id])
      if (!--degree[next])
        ready.push_back(next);
  }
  if (order.size() != tasks.size())
    throw std::invalid_argument("Task graph contains a cycle");
  return order;
}

void Orchestrator::complete_subtask(const std::string &id) {
  tasks.at(id).status = "success";
}

void Orchestrator::fail_subtask(const std::string &id) {
  tasks.at(id).status = "failed";
}

void Orchestrator::replan_subtask(const std::string &id,
                                  const std::string &goal) {
  auto &t = tasks.at(id);
  t.goal = goal;
  t.status = "pending";
  t.notes.clear();
}
} // namespace harness
