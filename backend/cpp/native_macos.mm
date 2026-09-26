#include "harness/core.hpp"
#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#include <cmath>
#include <spawn.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
extern char **environ;

namespace harness {
static NSData *decode(const std::string &b64) {
  return [[NSData alloc]
      initWithBase64EncodedString:[NSString stringWithUTF8String:b64.c_str()]
                          options:0];
}

static std::string encode(NSData *data) {
  return std::string([[data base64EncodedStringWithOptions:0] UTF8String]);
}

static CGImageRef image(const std::string &b64) {
  NSBitmapImageRep *rep = [NSBitmapImageRep imageRepWithData:decode(b64)];
  return rep ? CGImageRetain(rep.CGImage) : nullptr;
}

static std::string png(CGImageRef img) {
  auto rep = [[NSBitmapImageRep alloc] initWithCGImage:img];
  return encode([rep representationUsingType:NSBitmapImageFileTypePNG
                                  properties:@{}]);
}

static CFTypeRef attribute(AXUIElementRef e, CFStringRef key) {
  CFTypeRef v = nullptr;
  AXUIElementCopyAttributeValue(e, key, &v);
  return v;
}

static std::string ax_string(AXUIElementRef e, CFStringRef key) {
  auto v = attribute(e, key);
  std::string out;
  if (v && CFGetTypeID(v) == CFStringGetTypeID())
    out = [(__bridge NSString *)v UTF8String];
  if (v)
    CFRelease(v);
  return out;
}

static NSRunningApplication *target_application(int pid) {
  if (pid <= 0)
    throw std::runtime_error("Select a target application, or open one with "
                             "open_app, before controlling it");
  auto app = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
  if (!app || app.terminated)
    throw std::runtime_error("Target application exited; select it again");
  return app;
}

struct TargetWindow {
  CGWindowID id = 0;
  CGRect rect{};
  std::string title;
};

static TargetWindow target_window(int pid) {
  target_application(pid);
  auto windows =
      CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID);
  TargetWindow result;
  if (windows) {
    for (NSDictionary *info in (__bridge NSArray *)windows) {
      if ([info[(__bridge NSString *)kCGWindowOwnerPID] intValue] != pid ||
          [info[(__bridge NSString *)kCGWindowLayer] intValue] != 0 ||
          ![info[(__bridge NSString *)kCGWindowIsOnscreen] boolValue])
        continue;
      CGRect rect{};
      if (!CGRectMakeWithDictionaryRepresentation(
              (__bridge CFDictionaryRef)
                  info[(__bridge NSString *)kCGWindowBounds],
              &rect) ||
          rect.size.width < 40 || rect.size.height < 40)
        continue;
      result.id = [info[(__bridge NSString *)kCGWindowNumber] unsignedIntValue];
      result.rect = rect;
      NSString *title = info[(__bridge NSString *)kCGWindowName];
      result.title = title ? title.UTF8String : "";
      break;
    }
    CFRelease(windows);
  }
  if (!result.id)
    throw std::runtime_error(
        "Target app has no visible window. Restore its window; "
        "minimized/hidden apps cannot be controlled here.");
  return result;
}

static Object application_list() {
  Array apps;
  for (NSRunningApplication *app in
       [[NSWorkspace sharedWorkspace] runningApplications]) {
    if (app.terminated ||
        app.activationPolicy != NSApplicationActivationPolicyRegular)
      continue;
    apps.push_back(
        Object{{"pid", app.processIdentifier},
               {"name", app.localizedName ? app.localizedName.UTF8String
                                          : "Application"},
               {"bundle_id",
                app.bundleIdentifier ? app.bundleIdentifier.UTF8String : ""}});
  }
  return {{"ok", true},
          {"apps", apps},
          {"accessibility", bool(AXIsProcessTrusted())},
          {"screen_recording", bool(CGPreflightScreenCaptureAccess())},
          {"input_mode", "targeted"}};
}

// A private event source prevents physical modifier state from leaking into
// injected events. Every posted event is addressed to the selected process.
struct TargetInput {
  int pid;
  TargetWindow window;
  CGEventSourceRef source = CGEventSourceCreate(kCGEventSourceStatePrivate);

  explicit TargetInput(int target)
      : pid(target), window(target_window(target)) {
    if (!source)
      throw std::runtime_error("Cannot create private input source");
  }

  ~TargetInput() { CFRelease(source); }

  CGPoint point(double x, double y) const {
    if (!std::isfinite(x) || !std::isfinite(y) || x < 0 || y < 0 ||
        x >= window.rect.size.width || y >= window.rect.size.height)
      throw std::invalid_argument(
          "Coordinates are outside the selected app window");
    return CGPointMake(window.rect.origin.x + x, window.rect.origin.y + y);
  }

  void post(CGEventRef event) const {
    if (!event)
      throw std::runtime_error("Cannot create input event");
    CGEventSetIntegerValueField(event, kCGMouseEventWindowUnderMousePointer,
                                window.id);
    CGEventSetIntegerValueField(
        event, kCGMouseEventWindowUnderMousePointerThatCanHandleThisEvent,
        window.id);
    CGEventPostToPid(pid, event);
    CFRelease(event);
  }

  void mouse(CGEventType type, CGPoint point, CGMouseButton button,
             int count = 1) const {
    auto event = CGEventCreateMouseEvent(source, type, point, button);
    if (!event)
      throw std::runtime_error("Cannot create mouse event");
    CGEventSetFlags(event, 0);
    CGEventSetIntegerValueField(event, kCGMouseEventClickState, count);
    post(event);
  }
};

static bool press_accessible(int pid, CGPoint point) {
  auto root = AXUIElementCreateApplication(pid);
  AXUIElementSetMessagingTimeout(root, 1.0);
  AXUIElementRef element = nullptr;
  auto status =
      AXUIElementCopyElementAtPosition(root, point.x, point.y, &element);
  CFRelease(root);
  if (status != kAXErrorSuccess || !element)
    return false;
  pid_t owner = 0;
  AXUIElementGetPid(element, &owner);
  CFArrayRef actions = nullptr;
  AXUIElementCopyActionNames(element, &actions);
  const bool can_press =
      owner == pid && actions &&
      CFArrayContainsValue(actions, CFRangeMake(0, CFArrayGetCount(actions)),
                           kAXPressAction);
  if (actions)
    CFRelease(actions);
  if (!can_press) {
    CFRelease(element);
    return false;
  }
  status = AXUIElementPerformAction(element, kAXPressAction);
  CFRelease(element);
  if (status != kAXErrorSuccess)
    throw std::runtime_error("Target accessibility action failed; no global "
                             "input fallback was attempted");
  return true;
}

static Array elements(int target_pid) {
  Array result;
  if (!AXIsProcessTrusted())
    return result;
  @autoreleasepool {
    if (target_pid <= 0)
      return result;
    auto app = target_application(target_pid);
    auto window = target_window(target_pid);
    AXUIElementRef root = AXUIElementCreateApplication(app.processIdentifier);
    AXUIElementSetMessagingTimeout(root, 0.1);
    const auto deadline = now() + 1.5;
    std::function<void(AXUIElementRef, int)> visit = [&](AXUIElementRef e,
                                                         int depth) {
      if (depth > 10 || result.size() >= 80 || now() > deadline)
        return;
      auto role = ax_string(e, kAXRoleAttribute),
           title = ax_string(e, kAXTitleAttribute);
      if (title.empty())
        title = ax_string(e, kAXDescriptionAttribute);
      CGPoint pos{};
      CGSize size{};
      auto p = attribute(e, kAXPositionAttribute),
           s = attribute(e, kAXSizeAttribute);
      if (p && s && CFGetTypeID(p) == AXValueGetTypeID() &&
          CFGetTypeID(s) == AXValueGetTypeID() &&
          AXValueGetValue((AXValueRef)p, kAXValueTypeCGPoint, &pos) &&
          AXValueGetValue((AXValueRef)s, kAXValueTypeCGSize, &size) &&
          size.width > 0 && size.height > 0 && !title.empty())
        result.push_back(
            Object{{"id", result.size() + 1},
                   {"role", role},
                   {"title", title},
                   {"x", pos.x + size.width / 2 - window.rect.origin.x},
                   {"y", pos.y + size.height / 2 - window.rect.origin.y}});
      if (p)
        CFRelease(p);
      if (s)
        CFRelease(s);
      auto children = attribute(e, kAXChildrenAttribute);
      if (children && CFGetTypeID(children) == CFArrayGetTypeID())
        for (CFIndex i = 0;
             i < CFArrayGetCount((CFArrayRef)children) && now() < deadline; ++i)
          visit((AXUIElementRef)CFArrayGetValueAtIndex((CFArrayRef)children, i),
                depth + 1);
      if (children)
        CFRelease(children);
    };
    visit(root, 0);
    CFRelease(root);
  }
  return result;
}

std::string accessibility_text(int target_pid) {
  return j::serialize(elements(target_pid));
}

Object native_call(const std::string &name, const Object &args,
                   int target_pid) {
  @autoreleasepool {
    if (name == "list_apps")
      return application_list();
    if (name == "select_app") {
      int pid = int(number(args, "pid"));
      auto app = target_application(pid);
      return {{"ok", true},
              {"target_pid", pid},
              {"app", app.localizedName ? app.localizedName.UTF8String
                                        : "Application"}};
    }
    if (name == "get_screen_info") {
      CGDirectDisplayID ids[16];
      uint32_t count = 0;
      CGGetActiveDisplayList(16, ids, &count);
      Array displays;
      for (uint32_t i = 0; i < count; ++i) {
        auto r = CGDisplayBounds(ids[i]);
        displays.push_back(Object{{"width", r.size.width},
                                  {"height", r.size.height},
                                  {"left", r.origin.x},
                                  {"top", r.origin.y}});
      }
      auto e = CGEventCreate(nullptr);
      auto p = CGEventGetLocation(e);
      CFRelease(e);
      return {{"ok", true},
              {"displays", displays},
              {"cursor_pos", Object{{"x", p.x}, {"y", p.y}}}};
    }
    if (name == "screenshot" || name == "screenshot_with_marks") {
      auto window = target_window(target_pid);
      if (!CGPreflightScreenCaptureAccess())
        throw std::runtime_error("Grant Screen Recording permission to the "
                                 "backend's terminal in System Settings");
      // The system capture utility remains supported on SDKs where
      // CGWindowListCreateImage was removed.
      std::string path = std::string(NSTemporaryDirectory().UTF8String) +
                         "harness-" + uuid() + ".png";
      auto window_id = std::to_string(window.id);
      char *argv[] = {const_cast<char *>("/usr/sbin/screencapture"),
                      const_cast<char *>("-x"),
                      const_cast<char *>("-o"),
                      const_cast<char *>("-l"),
                      const_cast<char *>(window_id.c_str()),
                      const_cast<char *>(path.c_str()),
                      nullptr};
      pid_t pid;
      int rc = posix_spawn(&pid, argv[0], nullptr, nullptr, argv, environ),
          status = 0;
      if (!rc) {
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
        }
      }
      NSData *data = [NSData
          dataWithContentsOfFile:[NSString stringWithUTF8String:path.c_str()]];
      unlink(path.c_str());
      if (rc || !WIFEXITED(status) || WEXITSTATUS(status) || !data)
        throw std::runtime_error("Screen capture failed");
      auto source = [NSBitmapImageRep imageRepWithData:data];
      auto display = window.rect;
      size_t width = size_t(display.size.width),
             height = size_t(display.size.height);
      auto space = CGColorSpaceCreateDeviceRGB();
      auto ctx = CGBitmapContextCreate(nullptr, width, height, 8, width * 4,
                                       space, kCGImageAlphaPremultipliedLast);
      CGColorSpaceRelease(space);
      if (!ctx)
        throw std::runtime_error("Cannot allocate screenshot");
      CGContextDrawImage(ctx, CGRectMake(0, 0, width, height), source.CGImage);
      Array marks;
      if (name == "screenshot_with_marks") {
        marks = elements(target_pid);
        auto graphics = [NSGraphicsContext graphicsContextWithCGContext:ctx
                                                                flipped:NO];
        [NSGraphicsContext saveGraphicsState];
        [NSGraphicsContext setCurrentContext:graphics];
        for (auto &v : marks) {
          auto &m = v.as_object();
          double x = number(m, "x"), y = height - number(m, "y");
          [[NSColor redColor] setFill];
          [[NSBezierPath
              bezierPathWithOvalInRect:NSMakeRect(x - 9, y - 9, 18, 18)] fill];
          auto label = [NSString stringWithFormat:@"%d", int(number(m, "id"))];
          [label drawAtPoint:NSMakePoint(x - 5, y - 7)
              withAttributes:@{
                NSForegroundColorAttributeName : [NSColor whiteColor],
                NSFontAttributeName : [NSFont boldSystemFontOfSize:10]
              }];
        }
        [NSGraphicsContext restoreGraphicsState];
      }
      auto shot = CGBitmapContextCreateImage(ctx);
      CGContextRelease(ctx);
      if (auto r = args.if_contains("region")) {
        auto &o = r->as_object();
        CGRect crop = CGRectMake(number(o, "left", -1), number(o, "top", -1),
                                 number(o, "width"), number(o, "height"));
        if (crop.size.width <= 0 || crop.size.height <= 0 ||
            !CGRectContainsRect(CGRectMake(0, 0, width, height), crop)) {
          CGImageRelease(shot);
          throw std::invalid_argument("Invalid screenshot region");
        }
        auto cropped = CGImageCreateWithImageInRect(shot, crop);
        CGImageRelease(shot);
        shot = cropped;
        width = CGImageGetWidth(shot);
        height = CGImageGetHeight(shot);
      }
      Object out{{"ok", true},           {"width", width},
                 {"height", height},     {"out_width", width},
                 {"out_height", height}, {"scale", 1.0}};
      out["origin_x"] = window.rect.origin.x;
      out["origin_y"] = window.rect.origin.y;
      out["target_pid"] = target_pid;
      out["window_id"] = window.id;
      out["window_title"] = window.title;
      if (auto region = args.if_contains("region")) {
        out["origin_x"] =
            window.rect.origin.x + number(region->as_object(), "left");
        out["origin_y"] =
            window.rect.origin.y + number(region->as_object(), "top");
      }
      if (flag(args, "include_image", true))
        out["image_b64"] = png(shot);
      CGImageRelease(shot);
      if (name == "screenshot_with_marks")
        out["marks"] = marks;
      return out;
    }
    if (name == "open_app") {
      std::string app = str(args, "name");
      if (app.empty())
        throw std::invalid_argument("Application name is empty");
      static const std::map<std::string, std::string> aliases = {
          {"chrome", "Google Chrome"},
          {"vscode", "Visual Studio Code"},
          {"code", "Visual Studio Code"},
          {"itunes", "Music"},
          {"zoom", "zoom.us"},
          {"iterm2", "iTerm"}};
      auto lower = app;
      std::transform(lower.begin(), lower.end(), lower.begin(),
                     [](unsigned char c) { return std::tolower(c); });
      if (auto it = aliases.find(lower); it != aliases.end())
        app = it->second;
      char *argv[] = {const_cast<char *>("/usr/bin/open"),
                      const_cast<char *>("-g"), const_cast<char *>("-a"),
                      const_cast<char *>(app.c_str()), nullptr};
      pid_t pid;
      int status = 0;
      if (posix_spawn(&pid, argv[0], nullptr, nullptr, argv, environ))
        throw std::runtime_error("Cannot launch application");
      while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
      };
      if (!WIFEXITED(status) || WEXITSTATUS(status))
        throw std::runtime_error("Application could not be opened: " + app);
      NSString *requested =
          [[NSString stringWithUTF8String:app.c_str()] lastPathComponent];
      requested = [requested stringByDeletingPathExtension];
      for (int attempt = 0; attempt < 30; ++attempt) {
        for (NSRunningApplication *candidate in
             [[NSWorkspace sharedWorkspace] runningApplications]) {
          auto filename = [[candidate.bundleURL lastPathComponent]
              stringByDeletingPathExtension];
          if (!candidate.terminated &&
              ((candidate.localizedName &&
                [candidate.localizedName caseInsensitiveCompare:requested] ==
                    NSOrderedSame) ||
               (filename &&
                [filename caseInsensitiveCompare:requested] == NSOrderedSame)))
            return {{"ok", true},
                    {"app", app},
                    {"target_pid", candidate.processIdentifier}};
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
      throw std::runtime_error("App launched but could not resolve its PID; "
                               "select it in the target app picker");
    }
    target_application(target_pid);
    if (!AXIsProcessTrusted())
      throw std::runtime_error("Grant Accessibility permission to the "
                               "backend's terminal in System Settings");
    TargetInput input(target_pid);
    Object posted{{"ok", true},
                  {"target_pid", target_pid},
                  {"delivery", "posted_to_pid"},
                  {"verified", false}};
    if (name == "type_text") {
      NSString *text =
          [NSString stringWithUTF8String:str(args, "text").c_str()];
      if (!text)
        throw std::invalid_argument("Invalid UTF-8 text");
      // Keep surrogate pairs together and avoid the per-event Unicode length
      // limit.
      for (NSUInteger i = 0; i < text.length;) {
        NSUInteger n = std::min<NSUInteger>(20, text.length - i);
        if (i + n < text.length &&
            CFStringIsSurrogateHighCharacter([text characterAtIndex:i + n - 1]))
          --n;
        UniChar chars[20];
        [text getCharacters:chars range:NSMakeRange(i, n)];
        for (bool down : {true, false}) {
          auto e = CGEventCreateKeyboardEvent(input.source, 0, down);
          CGEventKeyboardSetUnicodeString(e, n, chars);
          CGEventSetFlags(e, 0);
          input.post(e);
        }
        i += n;
      }
      return posted;
    }
    if (name == "key_press" || name == "hotkey") {
      static const std::map<std::string, CGKeyCode> codes = {
          {"a", 0},        {"s", 1},          {"d", 2},       {"f", 3},
          {"h", 4},        {"g", 5},          {"z", 6},       {"x", 7},
          {"c", 8},        {"v", 9},          {"b", 11},      {"q", 12},
          {"w", 13},       {"e", 14},         {"r", 15},      {"y", 16},
          {"t", 17},       {"1", 18},         {"2", 19},      {"3", 20},
          {"4", 21},       {"6", 22},         {"5", 23},      {"=", 24},
          {"9", 25},       {"7", 26},         {"-", 27},      {"8", 28},
          {"0", 29},       {"]", 30},         {"o", 31},      {"u", 32},
          {"[", 33},       {"i", 34},         {"p", 35},      {"return", 36},
          {"enter", 36},   {"l", 37},         {"j", 38},      {"'", 39},
          {"k", 40},       {";", 41},         {"\\", 42},     {",", 43},
          {"/", 44},       {"n", 45},         {"m", 46},      {".", 47},
          {"tab", 48},     {"space", 49},     {"`", 50},      {"backspace", 51},
          {"escape", 53},  {"esc", 53},       {"cmd", 55},    {"command", 55},
          {"shift", 56},   {"alt", 58},       {"option", 58}, {"ctrl", 59},
          {"control", 59}, {"delete", 117},   {"home", 115},  {"end", 119},
          {"pageup", 116}, {"pagedown", 121}, {"left", 123},  {"right", 124},
          {"down", 125},   {"up", 126},       {"f1", 122},    {"f2", 120},
          {"f3", 99},      {"f4", 118},       {"f5", 96},     {"f6", 97},
          {"f7", 98},      {"f8", 100},       {"f9", 101},    {"f10", 109},
          {"f11", 103},    {"f12", 111}};
      std::vector<CGKeyCode> keys;
      CGEventFlags flags = 0;
      for (auto &k : args.at("keys").as_array()) {
        auto it = codes.find(std::string(k.as_string()));
        if (it == codes.end())
          throw std::invalid_argument("Unsupported key: " +
                                      std::string(k.as_string()));
        keys.push_back(it->second);
        switch (it->second) {
        case 55:
          flags |= kCGEventFlagMaskCommand;
          break;
        case 56:
          flags |= kCGEventFlagMaskShift;
          break;
        case 58:
          flags |= kCGEventFlagMaskAlternate;
          break;
        case 59:
          flags |= kCGEventFlagMaskControl;
          break;
        }
      }
      for (auto k : keys) {
        auto e = CGEventCreateKeyboardEvent(input.source, k, true);
        CGEventSetFlags(e, flags);
        input.post(e);
      }
      for (auto it = keys.rbegin(); it != keys.rend(); ++it) {
        auto e = CGEventCreateKeyboardEvent(input.source, *it, false);
        CGEventSetFlags(e, 0);
        input.post(e);
      }
      return posted;
    }
    CGPoint p{};
    if (name == "drag") {
      auto start = input.point(number(args, "x1"), number(args, "y1")),
           end = input.point(number(args, "x2"), number(args, "y2"));
      p = end;
      input.mouse(kCGEventMouseMoved, start, kCGMouseButtonLeft);
      input.mouse(kCGEventLeftMouseDown, start, kCGMouseButtonLeft);
      for (int i = 1; i <= 20; ++i) {
        input.mouse(kCGEventLeftMouseDragged,
                    CGPointMake(start.x + (end.x - start.x) * i / 20,
                                start.y + (end.y - start.y) * i / 20),
                    kCGMouseButtonLeft);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
      }
      input.mouse(kCGEventLeftMouseUp, end, kCGMouseButtonLeft);
    } else {
      p = input.point(number(args, "x"), number(args, "y"));
      if (name == "click" && str(args, "button", "left") == "left" &&
          number(args, "clicks", 1) == 1 && press_accessible(target_pid, p)) {
        posted["delivery"] = "accessibility_press";
        posted["cursor"] = Object{{"x", p.x}, {"y", p.y}};
        return posted;
      }
      input.mouse(kCGEventMouseMoved, p, kCGMouseButtonLeft);
      if (name == "scroll") {
        auto e = CGEventCreateScrollWheelEvent(
            input.source, kCGScrollEventUnitPixel, 2, -int(number(args, "dy")),
            -int(number(args, "dx")));
        CGEventSetLocation(e, p);
        CGEventSetFlags(e, 0);
        input.post(e);
      } else if (name != "move_mouse") {
        auto button =
            (name == "right_single" || str(args, "button") == "right")
                ? kCGMouseButtonRight
                : (str(args, "button") == "middle" ? kCGMouseButtonCenter
                                                   : kCGMouseButtonLeft);
        int count = name == "left_double" ? 2 : int(number(args, "clicks", 1));
        for (int i = 1; i <= count; ++i) {
          input.mouse(button == kCGMouseButtonLeft    ? kCGEventLeftMouseDown
                      : button == kCGMouseButtonRight ? kCGEventRightMouseDown
                                                      : kCGEventOtherMouseDown,
                      p, button, i);
          input.mouse(button == kCGMouseButtonLeft    ? kCGEventLeftMouseUp
                      : button == kCGMouseButtonRight ? kCGEventRightMouseUp
                                                      : kCGEventOtherMouseUp,
                      p, button, i);
        }
      }
    }
    posted["cursor"] = Object{{"x", p.x}, {"y", p.y}};
    return posted;
  }
}

Array image_grid(const std::string &b64) {
  @autoreleasepool {
    Array grid;
    auto img = image(b64);
    if (!img)
      return grid;
    int w = int(CGImageGetWidth(img)), h = int(CGImageGetHeight(img));
    for (int r = 0; r < 4; ++r)
      for (int c = 0; c < 4; ++c) {
        int x = c * w / 4, y = r * h / 4, x1 = (c + 1) * w / 4,
            y1 = (r + 1) * h / 4;
        auto crop =
            CGImageCreateWithImageInRect(img, CGRectMake(x, y, x1 - x, y1 - y));
        grid.push_back(Object{{"label", "R" + std::to_string(r + 1) + "C" +
                                            std::to_string(c + 1)},
                              {"x", x},
                              {"y", y},
                              {"x1", x1},
                              {"y1", y1},
                              {"image_b64", png(crop)}});
        CGImageRelease(crop);
      }
    CGImageRelease(img);
    return grid;
  }
}

double image_difference(const std::string &a, const std::string &b) {
  @autoreleasepool {
    if (a.empty() || b.empty())
      return 255;
    unsigned char pixels[2][1024]{};
    int index = 0;
    for (auto &s : {a, b}) {
      auto img = image(s);
      if (!img)
        return 255;
      auto space = CGColorSpaceCreateDeviceGray();
      auto ctx = CGBitmapContextCreate(pixels[index++], 32, 32, 8, 32, space,
                                       kCGImageAlphaNone);
      CGColorSpaceRelease(space);
      CGContextDrawImage(ctx, CGRectMake(0, 0, 32, 32), img);
      CGContextRelease(ctx);
      CGImageRelease(img);
    }
    double diff = 0;
    for (int i = 0; i < 1024; ++i)
      diff += std::abs(int(pixels[0][i]) - int(pixels[1][i]));
    return diff / 1024;
  }
}

void save_image(const std::string &b64, const std::string &path) {
  @autoreleasepool {
    if (!b64.empty() &&
        ![decode(b64) writeToFile:[NSString stringWithUTF8String:path.c_str()]
                       atomically:YES])
      throw std::runtime_error("Cannot save screenshot");
  }
}
} // namespace harness
