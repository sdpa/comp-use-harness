#include "harness/core.hpp"
#include <csignal>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mach-o/dyld.h>
#include <readline/history.h>
#include <readline/readline.h>
#include <sstream>
#include <unistd.h>

using namespace harness;
namespace fs = std::filesystem;
static volatile sig_atomic_t interrupted = 0;

static void interrupt(int) { interrupted = 1; }

// Terminal output is untrusted (model text, app titles, and saved sessions).
static std::string plain(const std::string &s) {
  std::string out;
  for (unsigned char c : s)
    if (c >= 32 && c != 127)
      out += char(c);
    else if (c == '\n' || c == '\t')
      out += char(c);
  return out;
}

static int pid_value(const std::string &s) {
  size_t used = 0;
  int pid = std::stoi(s, &used);
  if (used != s.size() || pid < 0 || pid > 1000000)
    throw std::invalid_argument("PID must be an integer from 0 to 1000000");
  return pid;
}

int main(int argc, char **argv) {
  try {
    char executable[4096];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0)
      throw std::runtime_error("Executable path too long");
    auto root = fs::weakly_canonical(executable)
                    .parent_path()
                    .parent_path()
                    .parent_path();
    std::string db = (root / "sessions.db").string();
    std::string config = (root / "backend/vlm_config.json").string();
    std::string logs = (root / "backend/logs").string();
    std::string prompt;
    bool dry = false, json = false, once = false;
    int pid = 0;
    for (int i = 1; i < argc; ++i) {
      std::string arg = argv[i];
      auto value = [&]() {
        if (++i >= argc)
          throw std::invalid_argument("Missing value for " + arg);
        return std::string(argv[i]);
      };
      if (arg == "--dry-run")
        dry = true;
      else if (arg == "--json")
        json = true;
      else if (arg == "--target")
        pid = pid_value(value());
      else if (arg == "--db")
        db = value();
      else if (arg == "--config")
        config = value();
      else if (arg == "--logs")
        logs = value();
      else if (arg == "-p" || arg == "--prompt") {
        prompt = value();
        once = true;
      } else if (arg == "--help" || arg == "-h") {
        std::cout
            << "CompUse — terminal computer-use agent\n\n"
               "harness-cli [--dry-run] [--target PID] [-p PROMPT] [--json]\n"
               "            [--db PATH] [--config PATH] [--logs PATH]\n\n"
               "Interactive commands: /help /apps /target PID /model [NAME]\n"
               "/history /show ID /new /quit\n"
               "Ctrl+C cancels a running task; Ctrl+D exits the prompt.\n"
               "--json requires -p and emits newline-delimited events.\n";
        return 0;
      } else
        throw std::invalid_argument("Unknown option: " + arg);
    }
    if (json && !once)
      throw std::invalid_argument("--json requires -p PROMPT");
    if (once && prompt.empty())
      throw std::invalid_argument("Prompt cannot be empty");
    Store store(db);
    Controller controller(dry, pid);
    const bool terminal = isatty(STDIN_FILENO) && isatty(STDOUT_FILENO);
    const bool color = terminal && !std::getenv("NO_COLOR") && !json;
    auto heading = [&](const std::string &text) {
      std::cout << (color ? "\033[1;35m" : "") << plain(text)
                << (color ? "\033[0m" : "") << '\n';
    };
    auto output = [&](const Object &event) {
      if (json) {
        std::cout << j::serialize(event) << std::endl;
        return;
      }
      auto type = str(event, "type");
      if (type == "step") {
        const auto &s = event.at("step").as_object();
        std::cout << "  • " << plain(str(s, "label")) << "  "
                  << plain(str(s, "time")) << '\n';
        if (!str(s, "detail").empty())
          std::cout << "    " << plain(str(s, "detail")) << '\n';
      } else if (type == "info")
        std::cout << "  " << plain(str(event, "message")) << '\n';
      else if (type == "call_user")
        heading("  Input needed: " + str(event, "question"));
      else if (type == "task_failed")
        heading("  " + str(event, "detail"));
      else if (type == "complete")
        heading("  " + str(event, "status") + " · " + str(event, "session_id"));
      std::cout.flush();
    };
    std::string context;
    if (!once) {
      heading("\n  CompUse  /  computer-use agent");
      std::cout
          << "  " << (dry ? "DRY RUN" : "Live app-targeted input")
          << " · /help for commands · Ctrl+C stops a task\n"
          << "  Terminal interface; no Electron preview or cursor overlay.\n\n";
    }
    int exit_code = 0;
    do {
      if (!once) {
        if (terminal) {
          char *line = readline("compuse › ");
          if (!line)
            break;
          prompt = line;
          free(line);
          if (!prompt.empty())
            add_history(prompt.c_str());
        } else if (!std::getline(std::cin, prompt))
          break;
        if (prompt.empty())
          continue;
        if (prompt[0] == '/') {
          std::istringstream command(prompt);
          std::string name, arg;
          command >> name;
          std::getline(command >> std::ws, arg);
          try {
            if (name == "/quit" || name == "/exit")
              break;
            if (name == "/help") {
              std::cout
                  << "/apps          List running apps and permission "
                     "readiness\n"
                     "/target PID    Select app (0 clears selection)\n"
                     "/model [NAME]  Show model/endpoint, or save model name\n"
                     "/history       List recent tasks\n/show ID       Read a "
                     "saved task\n"
                     "/new           Clear conversation context and target\n"
                     "/quit          Exit\n"
                     "Enter a task or follow-up. App state and recent task "
                     "context carry forward.\n"
                     "Configure endpoint/key via COMPUTER_USE_VLM_BASE_URL and "
                     "COMPUTER_USE_VLM_API_KEY.\n";
            } else if (name == "/apps") {
              std::cout << plain(j::serialize(controller.call("list_apps")))
                        << '\n';
            } else if (name == "/target") {
              int selected = pid_value(arg);
              if (!selected)
                controller.target_pid = 0;
              else {
                auto result =
                    controller.call("select_app", {{"pid", selected}});
                if (!flag(result, "ok"))
                  throw std::runtime_error(str(result, "error"));
              }
              heading("Target PID: " + std::to_string(controller.target_pid));
            } else if (name == "/model") {
              auto cfg = read_config(config);
              if (!arg.empty()) {
                cfg["vlm_model"] = arg;
                write_config(config, cfg);
              }
              cfg = effective_config(cfg);
              std::cout << plain(str(cfg, "vlm_model", "offline")) << " · "
                        << plain(str(cfg, "vlm_base_url")) << '\n';
            } else if (name == "/history") {
              for (const auto &v : store.list()) {
                const auto &s = v.as_object();
                std::cout << plain(str(s, "id")) << "  "
                          << plain(str(s, "status")) << "  "
                          << plain(str(s, "prompt")) << '\n';
              }
            } else if (name == "/show") {
              auto saved = store.get(arg);
              if (saved.is_null())
                throw std::runtime_error("Session not found");
              std::cout << plain(j::serialize(saved)) << '\n';
            } else if (name == "/new") {
              context.clear();
              controller.target_pid = 0;
              heading("New conversation");
            } else
              throw std::invalid_argument("Unknown command; use /help");
          } catch (const std::exception &e) {
            std::cerr << plain(e.what()) << '\n';
          }
          continue;
        }
      }
      interrupted = 0;
      auto previous_handler = std::signal(SIGINT, interrupt);
      const auto id = uuid();
      const auto start = now();
      std::string status = "error", summary;
      store.create(id, prompt);
      try {
        const auto dir = fs::path(logs) / ("run-" + id);
        fs::create_directories(dir);
        std::ofstream log(dir / "run.log");
        if (!log)
          throw std::runtime_error("Cannot write task log");
        Agent agent;
        if (dry)
          agent.pause_ms = 0;
        auto cfg = effective_config(read_config(config));
        // Offline mode accepts only exact single actions.
        auto instruction = context.empty() || str(cfg, "vlm_base_url").empty()
                               ? prompt
                               : "Previous conversation (context only):\n" +
                                     context + "\nCurrent request:\n" + prompt;
        bool ok = agent.run(
            instruction, controller, cfg,
            [&](const Object &event) {
              auto type = str(event, "type");
              if (type == "computer_frame")
                return;
              log << j::serialize(event) << '\n';
              log.flush();
              if (type == "step") {
                const auto &s = event.at("step").as_object();
                store.step(id, s);
                if (str(s, "type") == "verify")
                  summary = str(s, "detail");
              }
              if (type == "call_user")
                summary = "Agent asked: " + str(event, "question");
              output(event);
            },
            [] { return interrupted != 0; }, dir.string());
        status = ok ? "success" : "error";
      } catch (const std::exception &e) {
        if (!interrupted)
          output({{"type", "task_failed"}, {"detail", e.what()}});
      }
      if (interrupted)
        status = "cancelled";
      std::signal(SIGINT, previous_handler);
      store.complete(id, status, int((now() - start) * 1000));
      output({{"type", "complete"}, {"status", status}, {"session_id", id}});
      context +=
          "User: " + prompt + "\nOutcome: " + status + " " + summary + "\n";
      if (context.size() > 12000)
        context.erase(0, context.size() - 12000);
      exit_code = status == "success" ? 0 : status == "cancelled" ? 130 : 1;
    } while (!once);
    return once ? exit_code : 0;
  } catch (const std::exception &e) {
    std::cerr << plain(e.what()) << '\n';
    return 1;
  }
}
