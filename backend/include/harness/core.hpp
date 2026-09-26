#pragma once
#include <boost/json.hpp>
#include <functional>
#include <map>
#include <mutex>
#include <sqlite3.h>
#include <string>
#include <vector>

namespace harness {
namespace j = boost::json;
using Object = j::object;
using Array = j::array;
using Emit = std::function<void(const Object &)>;
std::string str(const Object &, const std::string &, std::string fallback = "");
double number(const Object &, const std::string &, double fallback = 0);
bool flag(const Object &, const std::string &, bool fallback = false);
double now();
std::string uuid();
Object read_config(const std::string &);
void write_config(const std::string &, const Object &);
Object effective_config(Object);

struct Decision {
  std::string name;
  Object args;
};

Decision parse_decision(const Object &response);
Object tool_schema();

class Store {
  sqlite3 *db_ = nullptr;
  std::recursive_mutex mutex_;
  Array query(const std::string &, const Array & = {});

public:
  explicit Store(const std::string &path);
  ~Store();
  Store(const Store &) = delete;
  void create(const std::string &id, const std::string &prompt);
  void complete(const std::string &id, const std::string &status, int elapsed);
  void step(const std::string &id, const Object &step);
  Array list();
  j::value get(const std::string &id);
};

class Controller {
public:
  bool dry_run;
  int target_pid = 0;
  std::vector<std::string> allowlist;

  explicit Controller(bool dry = false, int pid = 0)
      : dry_run(dry), target_pid(pid) {}

  Object call(const std::string &name, const Object &args = {});
};

Object native_call(const std::string &, const Object &, int target_pid = 0);
std::string accessibility_text(int target_pid = 0);
Array image_grid(const std::string &);
double image_difference(const std::string &, const std::string &);
void save_image(const std::string &, const std::string &);
Object request_model(const Object &, const Array &, int max_tokens = 512,
                     const std::function<bool()> &cancelled = {});

class Agent {
public:
  int max_steps = 30;
  int pause_ms = 350;
  bool run(const std::string &, Controller &, const Object &, const Emit &,
           const std::function<bool()> &cancelled = {},
           const std::string &run_dir = "");
};

struct Subtask {
  std::string id, goal, type = "ui_navigator";
  std::vector<std::string> depends_on;
  std::string status = "pending", notes, evidence;
};

class Orchestrator {
public:
  std::map<std::string, Subtask> tasks;
  explicit Orchestrator(std::vector<Subtask> tasks = {});
  std::vector<std::string> execution_order() const;
  void complete_subtask(const std::string &id);
  void fail_subtask(const std::string &id);
  void replan_subtask(const std::string &id, const std::string &goal);
};

int mcp_main(bool dry_run);
} // namespace harness
