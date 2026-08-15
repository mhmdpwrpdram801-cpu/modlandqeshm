// Runs the real recogniser page against a stubbed browser.
//
// The page is the one part of this app that never executes under pytest: it is
// JavaScript inside an HTML file, served to Chrome. That is exactly where the
// retry loop lived, and reading it was the only reason it was ever found. So
// this does for the page what auditor/botsim does for the bot — runs the actual
// shipped source, stubs only the world around it, and asserts behaviour.
//
// The clock is fake (TEST-07): the point is the *schedule* of restarts, and
// waiting sixty-five real seconds to watch it would make the check useless.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const PAGE = join(here, "..", "..", "src", "mlqvoice", "web", "recognizer.html");

function pageScript() {
  const html = readFileSync(PAGE, "utf8");
  const open = html.indexOf("<script>");
  const close = html.indexOf("</script>", open);
  if (open === -1 || close === -1) throw new Error("صفحه اسکریپت ندارد");
  return html.slice(open + "<script>".length, close);
}

/** A browser just real enough for the page, and fully under our thumb. */
function launch() {
  const posts = [];          // every fetch the page makes
  const timers = [];         // pending setTimeout callbacks
  let now = 0;
  let nextId = 1;
  const engines = [];        // every SpeechRecognition the page constructs
  let source = null;         // the EventSource the page opens

  class FakeRecognition {
    constructor() {
      this.started = 0;
      this.stopped = 0;
      engines.push(this);
    }
    start() {
      this.started++;
      if (this.onstart) this.onstart();
    }
    stop() {
      this.stopped++;
    }
  }

  const context = {
    JSON,
    Math,
    Set,
    Date: { now: () => now },
    encodeURIComponent,
    console,
    fetch: (url, opts) => {
      posts.push({ url, body: JSON.parse(opts.body) });
      return Promise.resolve({ ok: true });
    },
    setTimeout: (fn, ms) => {
      const id = nextId++;
      timers.push({ id, fn, at: now + (ms || 0), ms: ms || 0 });
      return id;
    },
    clearTimeout: (id) => {
      const i = timers.findIndex((t) => t.id === id);
      if (i !== -1) timers.splice(i, 1);
    },
    document: {
      getElementById: () => ({ textContent: "", className: "" }),
    },
    EventSource: class {
      constructor(url) {
        this.url = url;
        source = this;
      }
    },
  };
  context.window = context;
  context.SpeechRecognition = FakeRecognition;
  context.addEventListener = () => {};
  vm.createContext(context);
  vm.runInContext(pageScript(), context);

  const api = {
    posts,
    engines,
    /** The delay of the single pending restart, or null when nothing is queued. */
    pendingDelay: () => (timers.length ? timers[timers.length - 1].ms : null),
    /** Run every timer that is due, advancing the clock to its deadline. */
    fire: () => {
      while (timers.length) {
        const t = timers.shift();
        now = Math.max(now, t.at);
        t.fn();
      }
    },
    send: (msg) => source.onmessage({ data: JSON.stringify(msg) }),
    engine: () => engines[engines.length - 1],
    /** One failed session: the engine errors, then ends. */
    fail: (error) => {
      const e = api.engine();
      e.onerror({ error });
      e.onend();
    },
    /** One healthy session that Chrome closed on its own after silence. */
    quietEnd: () => api.engine().onend(),
    statuses: () => posts.filter((p) => p.url.startsWith("/status")).map((p) => p.body),
  };
  source.onopen();
  return api;
}

// -- the checks ----------------------------------------------------------

let failed = 0;
const results = [];

function check(name, fn) {
  try {
    fn();
    results.push(["✅", name, ""]);
  } catch (exc) {
    failed++;
    results.push(["❌", name, exc.message]);
  }
}

function eq(got, want, what) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) throw new Error(`${what}: ${a} ≠ ${b}`);
}

check("سکوتِ عادی هر بار فوراً دوباره شروع می‌شود", () => {
  const b = launch();
  b.send({ cmd: "start", lang: "fa-IR", interim: true });
  const delays = [];
  for (let i = 0; i < 6; i++) {
    b.quietEnd();
    delays.push(b.pendingDelay());
    b.fire();
  }
  eq(delays, [250, 250, 250, 250, 250, 250], "تأخیرها");
});

check("خطای شبکه عقب‌نشینیِ نمایی می‌گیرد", () => {
  const b = launch();
  b.send({ cmd: "start" });
  const delays = [];
  for (let i = 0; i < 7; i++) {
    b.fail("network");
    delays.push(b.pendingDelay());
    b.fire();
  }
  eq(delays, [250, 500, 1000, 2000, 4000, 8000, 10000], "تأخیرها");
});

check("عقب‌نشینی از سقف بالاتر نمی‌رود", () => {
  const b = launch();
  b.send({ cmd: "start" });
  for (let i = 0; i < 10; i++) {
    b.fail("network");
    if (b.pendingDelay() !== null && b.pendingDelay() > 10000) {
      throw new Error(`تأخیر ${b.pendingDelay()} از سقف رد شد`);
    }
    b.fire();
  }
});

check("بعد از سقفِ تلاش تسلیم می‌شود و دیگر نمی‌کوبد", () => {
  const b = launch();
  b.send({ cmd: "start" });
  for (let i = 0; i < 13; i++) {
    b.fail("network");
    b.fire();
  }
  b.fail("network");
  eq(b.pendingDelay(), null, "بعد از تسلیم شدن هنوز تلاشی در صف است");
});

check("و تسلیم شدنش را بلند می‌گوید", () => {
  const b = launch();
  b.send({ cmd: "start" });
  for (let i = 0; i < 14; i++) {
    b.fail("network");
    b.fire();
  }
  const said = b.statuses().some((s) => s.state === "error" && s.detail === "unreachable");
  if (!said) throw new Error("هیچ وضعیتی با detail=unreachable فرستاده نشد");
});

check("تعدادِ تلاش پیش از تسلیم شدن ۱۲ است، نه بی‌نهایت و نه ۱", () => {
  const b = launch();
  b.send({ cmd: "start" });
  let restarts = 0;
  for (let i = 0; i < 40; i++) {
    b.fail("network");
    if (b.pendingDelay() === null) break;
    restarts++;
    b.fire();
  }
  eq(restarts, 12, "تعدادِ تلاشِ دوباره");
});

check("یک نشستِ سالم شمارنده را صفر می‌کند", () => {
  // The whole point of separating the two cases: a blip must not leave the app
  // sluggish for the rest of the session.
  const b = launch();
  b.send({ cmd: "start" });
  for (let i = 0; i < 4; i++) {
    b.fail("network");
    b.fire();
  }
  b.quietEnd();
  eq(b.pendingDelay(), 250, "تأخیر بعد از نشستِ سالم");
});

check("زدنِ دوباره‌ی کلید از صفر شروع می‌کند", () => {
  const b = launch();
  b.send({ cmd: "start" });
  for (let i = 0; i < 5; i++) {
    b.fail("network");
    b.fire();
  }
  b.send({ cmd: "stop" });
  b.send({ cmd: "start" });
  b.fail("network");
  eq(b.pendingDelay(), 250, "تأخیر بعد از شروعِ دوباره");
});

check("توقف از سمتِ برنامه تلاشِ در صف را لغو می‌کند", () => {
  const b = launch();
  b.send({ cmd: "start" });
  b.fail("network");
  b.send({ cmd: "stop" });
  b.engine().onend();
  eq(b.pendingDelay(), null, "بعد از stop هنوز تلاشی در صف است");
});

check("«اجازه داده نشد» اصلاً تلاشِ دوباره نمی‌کند", () => {
  // Retrying a permission the user refused is pure noise; only they can fix it.
  const b = launch();
  b.send({ cmd: "start" });
  b.fail("not-allowed");
  eq(b.pendingDelay(), null, "بعد از not-allowed تلاشِ دوباره در صف است");
});

check("خطای شبکه یک بار به برنامه گزارش می‌شود", () => {
  const b = launch();
  b.send({ cmd: "start" });
  b.fail("network");
  const errs = b.statuses().filter((s) => s.state === "error" && s.detail === "network");
  eq(errs.length, 1, "تعدادِ گزارشِ خطا");
});

check("«صدایی نیامد» خطا حساب نمی‌شود", () => {
  // It is what silence looks like, and reporting it would paint the box red
  // every time the user pauses to think.
  const b = launch();
  b.send({ cmd: "start" });
  b.fail("no-speech");
  eq(b.statuses().filter((s) => s.state === "error").length, 0, "گزارشِ خطا");
  eq(b.pendingDelay(), 250, "تأخیر");
});

check("متنِ نهایی و حدسِ زنده جدا فرستاده می‌شوند", () => {
  const b = launch();
  b.send({ cmd: "start" });
  b.engine().onresult({
    resultIndex: 0,
    results: [
      Object.assign([{ transcript: "سلام" }], { 0: { transcript: "سلام" }, isFinal: true }),
      Object.assign([{ transcript: "چطور" }], { 0: { transcript: "چطور" }, isFinal: false }),
    ],
  });
  const sent = b.posts.filter((p) => p.url.startsWith("/result")).map((p) => p.body);
  eq(sent, [{ text: "سلام", final: true }, { text: "چطور", final: false }], "نتیجه‌ها");
});

// -- report --------------------------------------------------------------

for (const [mark, name, why] of results) {
  console.log(`  ${mark} ${name}${why ? `\n       ${why}` : ""}`);
}
console.log(`\n  ${results.length - failed}/${results.length} بررسیِ صفحه‌ی تشخیص پاس شد`);
process.exit(failed ? 1 : 0);
