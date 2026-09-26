#include "harness/core.hpp"
#include <atomic>
#include <boost/asio.hpp>
#include <boost/beast.hpp>
#include <csignal>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <thread>
namespace net = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
namespace ws = beast::websocket;
using tcp = net::ip::tcp;
using namespace harness;

struct App {
  Store store;
  std::string config_path, logs;
  bool dry;
  std::mutex mutex, desktop;
  std::map<std::string, Object> tasks;
  std::vector<std::string> order;

  App(std::string db, std::string config, std::string logdir, bool dry_run)
      : store(db), config_path(config), logs(logdir), dry(dry_run) {}

  Object config() {
    std::lock_guard lock(mutex);
    return effective_config(read_config(config_path));
  }

  std::pair<int, j::value> route(const http::request<http::string_body> &req) {
    std::string path(req.target());
    auto q = path.find('?');
    if (q != std::string::npos)
      path.resize(q);
    if (req.method() == http::verb::options)
      return {204, Object{}};
    bool get = req.method() == http::verb::get,
         post = req.method() == http::verb::post;
    if (get && path == "/")
      return {200, Object{{"name", "Computer-Use Harness"},
                          {"version", "0.3.0"},
                          {"api", "/api/health"}}};
    if (get && path == "/json/version")
      return {200, Object{}};
    if (get && path == "/api/health")
      return {200, Object{{"status", "ok"}, {"version", "0.3.0"}}};
    if (get && path == "/api/apps")
      return {200, native_call("list_apps", {})};
    if (get && path == "/api/config") {
      auto cfg = config();
      return {200, Object{{"vlm_base_url", str(cfg, "vlm_base_url")},
                          {"vlm_model", str(cfg, "vlm_model")},
                          {"vlm_enabled", !str(cfg, "vlm_base_url").empty()}}};
    }
    if (post && path == "/api/config") {
      auto body = j::parse(req.body()).as_object();
      std::lock_guard lock(mutex);
      auto cfg = read_config(config_path);
      for (auto key : {"vlm_base_url", "vlm_model", "vlm_api_key"})
        if (auto p = body.if_contains(key)) {
          if (!p->is_string())
            return {400, Object{{"detail", "Config fields must be strings"}}};
          cfg[key] = *p;
        }
      auto url = str(cfg, "vlm_base_url");
      if (!url.empty() && url.rfind("http://", 0) != 0 &&
          url.rfind("https://", 0) != 0)
        return {400, Object{{"detail", "Expected an HTTP or HTTPS model URL"}}};
      write_config(config_path, cfg);
      return {200, Object{{"saved", true}}};
    }
    if (get && path == "/api/sessions")
      return {200, store.list()};
    if (get && path.rfind("/api/sessions/", 0) == 0) {
      auto value = store.get(path.substr(14));
      return value.is_null()
                 ? std::make_pair(
                       404, j::value(Object{{"detail", "Session not found"}}))
                 : std::make_pair(200, value);
    }
    if (get && path == "/api/tasks") {
      std::lock_guard lock(mutex);
      Array out;
      for (auto it = order.rbegin(); it != order.rend(); ++it) {
        auto t = tasks.at(*it);
        t.erase("steps");
        out.push_back(t);
      }
      return {200, out};
    }
    if (post && path == "/api/tasks") {
      auto body = j::parse(req.body()).as_object();
      auto prompt = str(body, "prompt");
      if (prompt.find_first_not_of(" \r\n\t") == std::string::npos ||
          prompt.size() > 65536)
        return {400, Object{{"detail",
                             "Expected a nonempty prompt up to 65536 bytes"}}};
      auto id = uuid();
      if (auto pid = body.if_contains("target_pid");
          pid && (!pid->is_int64() || pid->as_int64() < 0 ||
                  pid->as_int64() > 1000000))
        return {400, Object{{"detail", "Invalid target application PID"}}};
      Object task{{"id", id},         {"run_id", "run-" + id},
                  {"prompt", prompt}, {"status", "pending"},
                  {"steps", Array{}}, {"created_at", now()},
                  {"elapsed_ms", 0}};
      task["target_pid"] = int(number(body, "target_pid"));
      std::lock_guard lock(mutex);
      tasks[id] = task;
      order.push_back(id);
      return {200, task};
    }
    return {404, Object{{"detail", "Not found"}}};
  }
};

class Stream : public std::enable_shared_from_this<Stream> {
  ws::stream<tcp::socket> socket_;
  beast::flat_buffer buffer_;
  std::deque<std::string> queue_;
  bool finishing_ = false, closed_ = false;
  std::shared_ptr<App> app_;
  std::string id_;

public:
  std::atomic<bool> cancelled{false};
  std::thread worker;

  Stream(tcp::socket socket, std::shared_ptr<App> app, std::string id)
      : socket_(std::move(socket)), app_(app), id_(id) {}

  void send(Object event) {
    net::post(socket_.get_executor(),
              [self = shared_from_this(), event = std::move(event)]() {
                if (self->closed_)
                  return;
                bool idle = self->queue_.empty();
                self->queue_.push_back(j::serialize(event));
                if (idle)
                  self->write();
              });
  }

  void finish() {
    net::post(socket_.get_executor(), [self = shared_from_this()]() {
      self->finishing_ = true;
      if (self->queue_.empty())
        self->close();
    });
  }

  void close() {
    if (closed_)
      return;
    closed_ = true;
    socket_.async_close(ws::close_code::normal,
                        [self = shared_from_this()](beast::error_code) {});
  }

  void write() {
    socket_.text(true);
    socket_.async_write(
        net::buffer(queue_.front()),
        [self = shared_from_this()](beast::error_code ec, size_t) {
          if (ec) {
            self->cancelled = true;
            self->closed_ = true;
            return;
          }
          self->queue_.pop_front();
          if (!self->queue_.empty())
            self->write();
          else if (self->finishing_)
            self->close();
        });
  }

  void read() {
    socket_.async_read(
        buffer_, [self = shared_from_this()](beast::error_code ec, size_t) {
          if (ec) {
            self->cancelled = true;
            self->closed_ = true;
            return;
          }
          self->buffer_.consume(self->buffer_.size());
          self->read();
        });
  }

  void start(const http::request<http::string_body> &req) {
    socket_.set_option(
        ws::stream_base::timeout::suggested(beast::role_type::server));
    socket_.read_message_max(65536);
    socket_.accept(req);
    read();
    auto self = shared_from_this();
    worker = std::thread([self]() { self->run(); });
  }

  void run() {
    Object task;
    bool claimed = false;
    {
      std::lock_guard lock(app_->mutex);
      auto it = app_->tasks.find(id_);
      if (it != app_->tasks.end() && str(it->second, "status") == "pending") {
        task = it->second;
        it->second["status"] = "running";
        claimed = true;
      }
    }
    if (!claimed) {
      send({{"type", "error"},
            {"message", "Task not found or already started"}});
      finish();
      return;
    }
    double start = now();
    std::string status = "error", error;
    std::unique_lock desktop(app_->desktop, std::try_to_lock);
    try {
      app_->store.create(id_, str(task, "prompt"));
      if (!desktop.owns_lock())
        throw std::runtime_error("Another task is controlling the desktop");
      auto dir = app_->logs + "/" + str(task, "run_id");
      std::filesystem::create_directories(dir);
      std::ofstream log(dir + "/run.log");
      if (!log)
        throw std::runtime_error("Cannot open run log");
      Controller ctrl(app_->dry, int(number(task, "target_pid")));
      Agent agent;
      if (app_->dry)
        agent.pause_ms = 0;
      auto emit = [&](const Object &event) {
        if (cancelled)
          throw std::runtime_error("Task cancelled");
        // Frames are transient UI observations, not history/log entries.
        // PNGs already have separate files in the run directory.
        if (str(event, "type") != "computer_frame") {
          log << j::serialize(event) << '\n';
          log.flush();
        }
        if (str(event, "type") == "step") {
          auto step = event.at("step").as_object();
          app_->store.step(id_, step);
          std::lock_guard lock(app_->mutex);
          app_->tasks.at(id_).at("steps").as_array().push_back(step);
        }
        if (str(event, "type") == "task_failed")
          error = str(event, "detail");
        // Persist final status before delivering the terminal error event.
        if (str(event, "type") != "task_failed")
          send(event);
      };
      send({{"type", "info"},
            {"run_id", str(task, "run_id")},
            {"dry_run", app_->dry}});
      bool ok = agent.run(
          str(task, "prompt"), ctrl, app_->config(), emit,
          [&]() { return cancelled.load(); }, dir);
      status = ok ? "success" : "error";
    } catch (const std::exception &e) {
      error = e.what();
    }
    if (cancelled)
      status = "cancelled";
    int ms = int((now() - start) * 1000);
    try {
      app_->store.complete(id_, status, ms);
    } catch (const std::exception &e) {
      status = "error";
      error = e.what();
    }
    {
      std::lock_guard lock(app_->mutex);
      auto &t = app_->tasks.at(id_);
      t["status"] = status;
      t["elapsed_ms"] = ms;
    }
    if (!cancelled) {
      if (status == "success")
        send({{"type", "complete"}, {"status", status}, {"elapsed_ms", ms}});
      else
        send({{"type", "error"},
              {"message", error.empty() ? "Task failed" : error},
              {"elapsed_ms", ms}});
    }
    finish();
  }
};

int main(int argc, char **argv) {
  std::signal(SIGPIPE, SIG_IGN);
  try {
    std::filesystem::path root = std::filesystem::path(__FILE__)
                                     .parent_path()
                                     .parent_path()
                                     .parent_path();
    // Paths are selected relative to the executable, so launching from
    // frontend/ works too.
    auto executable = std::filesystem::weakly_canonical(argv[0]);
    root = executable.parent_path().parent_path().parent_path();
    std::string db = (root / "sessions.db").string(),
                config = (root / "backend/vlm_config.json").string(),
                logs = (root / "backend/logs").string();
    int port = 7123;
    bool dry = false, mcp = false;
    for (int i = 1; i < argc; ++i) {
      std::string arg = argv[i];
      auto value = [&]() {
        if (i + 1 >= argc)
          throw std::invalid_argument("Missing value for " + arg);
        return std::string(argv[++i]);
      };
      if (arg == "--port")
        port = std::stoi(value());
      else if (arg == "--db")
        db = value();
      else if (arg == "--config")
        config = value();
      else if (arg == "--logs")
        logs = value();
      else if (arg == "--dry-run")
        dry = true;
      else if (arg == "--mcp")
        mcp = true;
      else if (arg == "--help") {
        std::cout << "harness [--port 7123] [--db PATH] [--config PATH] "
                     "[--logs PATH] [--dry-run] [--mcp]\n";
        return 0;
      } else
        throw std::invalid_argument("Unknown option: " + arg);
    }
    if (mcp)
      return mcp_main(dry);
    if (port < 1 || port > 65535)
      throw std::invalid_argument("Invalid port");
    auto app = std::make_shared<App>(db, config, logs, dry);
    net::io_context accept_io;
    tcp::acceptor acceptor(accept_io, {net::ip::make_address("127.0.0.1"),
                                       static_cast<unsigned short>(port)});
    std::cout << "C++ backend listening on http://127.0.0.1:" << port
              << (dry ? " (dry run)" : "") << std::endl;
    for (;;) {
      auto io = std::make_shared<net::io_context>();
      tcp::socket socket(*io);
      acceptor.accept(socket);
      std::thread([io, socket = std::move(socket), app]() mutable {
        try {
          beast::flat_buffer buffer;
          http::request_parser<http::string_body> parser;
          parser.body_limit(1024 * 1024);
          http::read(socket, buffer, parser);
          auto req = parser.release();
          std::string path(req.target());
          const std::string prefix = "/api/tasks/", suffix = "/stream";
          if (ws::is_upgrade(req) && path.rfind(prefix, 0) == 0 &&
              path.size() > prefix.size() + suffix.size() &&
              path.compare(path.size() - suffix.size(), suffix.size(),
                           suffix) == 0) {
            auto stream = std::make_shared<Stream>(
                std::move(socket), app,
                path.substr(prefix.size(),
                            path.size() - prefix.size() - suffix.size()));
            stream->start(req);
            io->run();
            stream->cancelled = true;
            if (stream->worker.joinable())
              stream->worker.join();
            return;
          }
          int code;
          j::value body;
          try {
            auto response = app->route(req);
            code = response.first;
            body = response.second;
          } catch (const std::invalid_argument &) {
            code = 400;
            body = Object{{"detail", "Invalid request"}};
          } catch (const boost::system::system_error &) {
            code = 400;
            body = Object{{"detail", "Invalid JSON request"}};
          } catch (const std::exception &e) {
            code = 500;
            body = Object{{"detail", e.what()}};
          }
          http::response<http::string_body> res{static_cast<http::status>(code),
                                                req.version()};
          res.set(http::field::content_type, "application/json");
          res.set(http::field::access_control_allow_origin, "*");
          res.set(http::field::access_control_allow_methods,
                  "GET, POST, OPTIONS");
          res.set(http::field::access_control_allow_headers, "Content-Type");
          res.keep_alive(false);
          if (code != 204)
            res.body() = j::serialize(body);
          res.prepare_payload();
          http::write(socket, res);
        } catch (const std::exception &e) {
          std::cerr << "Connection: " << e.what() << '\n';
        }
      }).detach();
    }
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
