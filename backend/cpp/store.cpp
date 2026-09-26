#include "harness/core.hpp"
#include <memory>

namespace harness {
Array Store::query(const std::string &sql, const Array &args) {
  std::lock_guard lock(mutex_);
  sqlite3_stmt *raw = nullptr;
  if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK)
    throw std::runtime_error(sqlite3_errmsg(db_));
  std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> stmt(
      raw, sqlite3_finalize);
  for (size_t i = 0; i < args.size(); ++i) {
    auto &v = args[i];
    int rc;
    if (v.is_null())
      rc = sqlite3_bind_null(raw, int(i + 1));
    else if (v.is_string())
      rc = sqlite3_bind_text(raw, int(i + 1), v.as_string().c_str(),
                             int(v.as_string().size()), SQLITE_TRANSIENT);
    else
      rc = sqlite3_bind_double(raw, int(i + 1), v.to_number<double>());
    if (rc != SQLITE_OK)
      throw std::runtime_error(sqlite3_errmsg(db_));
  }
  Array rows;
  int rc;
  while ((rc = sqlite3_step(raw)) == SQLITE_ROW) {
    Object row;
    for (int c = 0; c < sqlite3_column_count(raw); ++c) {
      const char *name = sqlite3_column_name(raw, c);
      switch (sqlite3_column_type(raw, c)) {
      case SQLITE_NULL:
        row[name] = nullptr;
        break;
      case SQLITE_INTEGER:
        row[name] = sqlite3_column_int64(raw, c);
        break;
      case SQLITE_FLOAT:
        row[name] = sqlite3_column_double(raw, c);
        break;
      default:
        row[name] = std::string(
            reinterpret_cast<const char *>(sqlite3_column_text(raw, c)),
            sqlite3_column_bytes(raw, c));
      }
    }
    rows.push_back(row);
  }
  if (rc != SQLITE_DONE)
    throw std::runtime_error(sqlite3_errmsg(db_));
  return rows;
}

Store::Store(const std::string &path) {
  if (sqlite3_open(path.c_str(), &db_) != SQLITE_OK) {
    std::string error = sqlite3_errmsg(db_);
    sqlite3_close(db_);
    throw std::runtime_error(error);
  }
  sqlite3_busy_timeout(db_, 5000);
  try {
    query("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,prompt TEXT "
          "NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at REAL NOT "
          "NULL,completed_at REAL,elapsed_ms INTEGER)");
    query("CREATE TABLE IF NOT EXISTS subtasks(session_id TEXT NOT NULL,id "
          "TEXT NOT NULL,goal TEXT NOT NULL,subtask_type TEXT NOT NULL DEFAULT "
          "'ui_navigator',status TEXT NOT NULL DEFAULT 'pending',depends_on "
          "TEXT NOT NULL DEFAULT '[]',evidence TEXT DEFAULT '',notes TEXT "
          "DEFAULT '',created_at REAL NOT NULL,PRIMARY KEY(session_id,id))");
    query("CREATE TABLE IF NOT EXISTS steps(session_id TEXT NOT "
          "NULL,subtask_id TEXT,step_index INTEGER NOT NULL,type TEXT NOT "
          "NULL,label TEXT NOT NULL,detail TEXT DEFAULT '',time TEXT DEFAULT "
          "'',created_at REAL NOT NULL)");
    query("CREATE INDEX IF NOT EXISTS idx_steps_session ON steps(session_id)");
    query("CREATE INDEX IF NOT EXISTS idx_subtasks_session ON "
          "subtasks(session_id)");
  } catch (...) {
    sqlite3_close(db_);
    throw;
  }
}

Store::~Store() { sqlite3_close(db_); }

void Store::create(const std::string &id, const std::string &prompt) {
  query("INSERT OR IGNORE INTO sessions(id,prompt,status,created_at) "
        "VALUES(?,?,'running',?)",
        {id, prompt, now()});
}

void Store::complete(const std::string &id, const std::string &status, int ms) {
  query("UPDATE sessions SET status=?,completed_at=?,elapsed_ms=? WHERE id=?",
        {status, now(), ms, id});
}

void Store::step(const std::string &id, const Object &s) {
  query("INSERT INTO "
        "steps(session_id,subtask_id,step_index,type,label,detail,time,created_"
        "at) SELECT ?,NULL,COALESCE(MAX(step_index)+1,0),?,?,?,?,? FROM steps "
        "WHERE session_id=?",
        {id, str(s, "type"), str(s, "label"), str(s, "detail"), str(s, "time"),
         now(), id});
}

Array Store::list() {
  return query("SELECT id,prompt,status,created_at,COALESCE(elapsed_ms,0) AS "
               "elapsed_ms FROM sessions ORDER BY created_at DESC LIMIT 50");
}

j::value Store::get(const std::string &id) {
  std::lock_guard lock(mutex_);
  auto rows = query("SELECT id,prompt,status,created_at,COALESCE(elapsed_ms,0) "
                    "AS elapsed_ms FROM sessions WHERE id=?",
                    {id});
  if (rows.empty())
    return nullptr;
  auto row = rows[0].as_object();
  auto subtasks = query("SELECT id,goal,subtask_type,status,depends_on,notes "
                        "FROM subtasks WHERE session_id=? ORDER BY created_at",
                        {id});
  for (auto &t : subtasks)
    t.as_object()["depends_on"] =
        j::parse(str(t.as_object(), "depends_on", "[]"));
  row["subtasks"] = subtasks;
  row["steps"] = query("SELECT type,label,detail,time,subtask_id FROM steps "
                       "WHERE session_id=? ORDER BY step_index",
                       {id});
  return row;
}
} // namespace harness
