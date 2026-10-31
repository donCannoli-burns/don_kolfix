"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = function(target, all) {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: !0 });
}, __copyProps = function(to, from, except, desc) {
  if (from && typeof from == "object" || typeof from == "function")
    for (var keys = __getOwnPropNames(from), i = 0, n = keys.length, key; i < n; i++)
      key = keys[i], !__hasOwnProp.call(to, key) && key !== except && __defProp(to, key, { get: function(k) {
        return from[k];
      }.bind(null, key), enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  return to;
};
var __toCommonJS = function(mod) {
  return __copyProps(__defProp({}, "__esModule", { value: !0 }), mod);
};

// src/don-report.ts
var don_report_exports = {};
__export(don_report_exports, {
  default: function() {
    return main;
  }
});
module.exports = __toCommonJS(don_report_exports);
var import_kolmafia = require("kolmafia");

// src/report-contract.ts
var TOKEN = /^[a-z][a-z0-9_]{0,39}$/, SUBJECT = /^[a-z][a-z0-9_]*\/[1-9][0-9]*$/;
var DATE = /^[0-9]{8}$/;
function validScope(s) {
  return !!s && /^[0-9]{1,12}$/.test(s.playerId) && DATE.test(s.day) && Number.isSafeInteger(s.life) && s.life >= 0;
}
function nodeAddress(s, n) {
  if (!validScope(s) || !n || !TOKEN.test(n.domain) || !SUBJECT.test(n.subject) || !TOKEN.test(n.metric))
    throw new Error("DON_REPORT_INVALID_ADDRESS");
  return "donstate:v1:".concat(s.playerId, ":").concat(s.day, ":").concat(s.life, ":").concat(n.domain, ":").concat(n.subject, ":").concat(n.metric);
}
var DON_REPORT_ROUTES = {
  item_value: {
    owner: "accountval",
    domain: "economy",
    requiresPriceConsent: !0
  },
  item_new: {
    owner: "philter",
    domain: "inventory",
    requiresPriceConsent: !1
  },
  skills_current: {
    owner: "greenbox",
    domain: "skills",
    requiresPriceConsent: !1
  },
  organ_state: {
    owner: "consume",
    domain: "organs",
    requiresPriceConsent: !1
  },
  relay_state: {
    owner: "chit",
    domain: "relay",
    requiresPriceConsent: !1
  },
  spading_state: {
    owner: "excavator",
    domain: "events",
    requiresPriceConsent: !1
  }
};
function parseDonReportCommand(input) {
  if (typeof input != "string" || input.length > 256 || /[\r\n;|&#]/.test(input))
    throw new Error("DON_REPORT_INVALID_COMMAND");
  var args = input.trim().split(/\s+/).filter(Boolean), name = args.shift();
  if (!name || !(name in DON_REPORT_ROUTES))
    throw new Error("DON_REPORT_UNKNOWN_COMMAND");
  var opts = args.filter(function(a) {
    return a.startsWith("-");
  });
  if (opts.some(function(a) {
    return !["--quiet", "--diff", "--print"].includes(a);
  }))
    throw new Error("DON_REPORT_UNKNOWN_OPTION");
  return {
    route: name,
    arguments: args.filter(function(a) {
      return !a.startsWith("-");
    }),
    quiet: opts.includes("--quiet"),
    diff: opts.includes("--diff"),
    print: opts.includes("--print")
  };
}

// src/don-report.ts
function _slicedToArray(arr, i) {
  return _arrayWithHoles(arr) || _iterableToArrayLimit(arr, i) || _unsupportedIterableToArray(arr, i) || _nonIterableRest();
}
function _nonIterableRest() {
  throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
}
function _iterableToArrayLimit(arr, i) {
  var _i = arr == null ? null : typeof Symbol != "undefined" && arr[Symbol.iterator] || arr["@@iterator"];
  if (_i != null) {
    var _arr = [], _n = !0, _d = !1, _s, _e;
    try {
      for (_i = _i.call(arr); !(_n = (_s = _i.next()).done) && (_arr.push(_s.value), !(i && _arr.length === i)); _n = !0)
        ;
    } catch (err) {
      _d = !0, _e = err;
    } finally {
      try {
        !_n && _i.return != null && _i.return();
      } finally {
        if (_d)
          throw _e;
      }
    }
    return _arr;
  }
}
function _arrayWithHoles(arr) {
  if (Array.isArray(arr))
    return arr;
}
function _createForOfIteratorHelper(o, allowArrayLike) {
  var it = typeof Symbol != "undefined" && o[Symbol.iterator] || o["@@iterator"];
  if (!it) {
    if (Array.isArray(o) || (it = _unsupportedIterableToArray(o)) || allowArrayLike && o && typeof o.length == "number") {
      it && (o = it);
      var i = 0, F = function() {
      };
      return { s: F, n: function() {
        return i >= o.length ? { done: !0 } : { done: !1, value: o[i++] };
      }, e: function(_e2) {
        throw _e2;
      }, f: F };
    }
    throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
  }
  var normalCompletion = !0, didErr = !1, err;
  return { s: function() {
    it = it.call(o);
  }, n: function() {
    var step = it.next();
    return normalCompletion = step.done, step;
  }, e: function(_e3) {
    didErr = !0, err = _e3;
  }, f: function() {
    try {
      !normalCompletion && it.return != null && it.return();
    } finally {
      if (didErr)
        throw err;
    }
  } };
}
function _unsupportedIterableToArray(o, minLen) {
  if (!!o) {
    if (typeof o == "string")
      return _arrayLikeToArray(o, minLen);
    var n = Object.prototype.toString.call(o).slice(8, -1);
    if (n === "Object" && o.constructor && (n = o.constructor.name), n === "Map" || n === "Set")
      return Array.from(o);
    if (n === "Arguments" || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n))
      return _arrayLikeToArray(o, minLen);
  }
}
function _arrayLikeToArray(arr, len) {
  (len == null || len > arr.length) && (len = arr.length);
  for (var i = 0, arr2 = new Array(len); i < len; i++)
    arr2[i] = arr[i];
  return arr2;
}
function emit(scope2, node, value, quiet) {
  var address = nodeAddress(scope2, node);
  quiet || (0, import_kolmafia.print)("".concat(address, " = ").concat(value === null ? "known_unknown" : value));
}
function scope() {
  return {
    playerId: String((0, import_kolmafia.myId)()),
    day: (0, import_kolmafia.todayToString)(),
    life: (0, import_kolmafia.myAscensions)()
  };
}
function usage() {
  (0, import_kolmafia.print)("Don Report v1 \u2014 local cached state, NO journal or writer", "blue"), (0, import_kolmafia.print)("call kolfix/don_report.js item_new [--quiet|--print|--diff]"), (0, import_kolmafia.print)("call kolfix/don_report.js item_value 1000000 [--quiet]"), (0, import_kolmafia.print)("call kolfix/don_report.js skills_current [--quiet]"), (0, import_kolmafia.print)("call kolfix/don_report.js organ_state [--quiet]"), (0, import_kolmafia.print)("call kolfix/don_report.js relay_state"), (0, import_kolmafia.print)("call kolfix/don_report.js spading_state");
}
function main() {
  var command = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : "";
  if (!command.trim() || command.trim() === "help") {
    usage();
    return;
  }
  var args;
  try {
    args = parseDonReportCommand(command);
  } catch (_error) {
    (0, import_kolmafia.print)("Invalid Don Report command; use 'call kolfix/don_report.js help'.", "red");
    return;
  }
  var owner = DON_REPORT_ROUTES[args.route].owner, s = scope(), quiet = args.quiet && !args.print;
  if (args.diff && (0, import_kolmafia.print)("DIFF UNKNOWN: No verified prior report receipt is loaded. No comparison claimed.", "orange"), args.route === "skills_current") {
    if (args.arguments.length !== 0) {
      (0, import_kolmafia.print)("skills_current takes no positional arguments.", "red");
      return;
    }
    var n = 0, _iterator = _createForOfIteratorHelper(import_kolmafia.Skill.all()), _step;
    try {
      for (_iterator.s(); !(_step = _iterator.n()).done; ) {
        var skill = _step.value;
        !(0, import_kolmafia.haveSkill)(skill) || (emit(s, {
          domain: "skills",
          subject: "skill/".concat((0, import_kolmafia.toInt)(skill)),
          metric: "current"
        }, !0, quiet), quiet || (0, import_kolmafia.print)("  ".concat(skill)), n++);
      }
    } catch (err) {
      _iterator.e(err);
    } finally {
      _iterator.f();
    }
    (0, import_kolmafia.print)("Source ".concat(owner, "; ").concat(n, " currently available skills. Permanent status requires separate evidence."));
    return;
  }
  if (args.route === "organ_state") {
    if (args.arguments.length !== 0) {
      (0, import_kolmafia.print)("organ_state takes no positional arguments.", "red");
      return;
    }
    for (var values = [["liver_used", (0, import_kolmafia.myInebriety)()], ["stomach_used", (0, import_kolmafia.myFullness)()], ["spleen_used", (0, import_kolmafia.mySpleenUse)()]], _i = 0, _values = values; _i < _values.length; _i++) {
      var _values$_i = _slicedToArray(_values[_i], 2), metric = _values$_i[0], value = _values$_i[1];
      emit(s, {
        domain: "organs",
        subject: "organ/1",
        metric: metric
      }, value, quiet);
    }
    (0, import_kolmafia.print)("Source consume; observed cached organ use. No diet was planned or executed.");
    return;
  }
  if (args.route === "relay_state") {
    var enabled = (0, import_kolmafia.getProperty)("donReport_relayCaptureEnabled");
    emit(s, {
      domain: "relay",
      subject: "relay/1",
      metric: "capture_enabled"
    }, enabled === "" ? null : enabled === "true", quiet), (0, import_kolmafia.print)("ChIT's original relay override remains untouched; capture defaults OFF.");
    return;
  }
  if (args.route === "spading_state") {
    var active = (0, import_kolmafia.getProperty)("spadingScript");
    (0, import_kolmafia.print)("spadingScript = ".concat(active === "" ? "(unset)" : active)), (0, import_kolmafia.print)("Event bridge not activated; Excavator and shared spadingData are untouched.");
    return;
  }
  if (args.route === "item_value") {
    if (args.arguments.length > 1 || args.arguments.length === 1 && !/^(0|[1-9][0-9]*)$/.test(args.arguments[0])) {
      (0, import_kolmafia.print)("Usage: item_value [minimum-meat] [--quiet|--diff|--print]", "red");
      return;
    }
    (0, import_kolmafia.print)("KNOWN_UNKNOWN: Market value needs an explicitly approved Accountval price collector."), (0, import_kolmafia.print)("Threshold = ".concat(args.arguments[0] || "0", " Meat. No market request made."));
    return;
  }
  if (args.route === "item_new") {
    if (args.arguments.length !== 0) {
      (0, import_kolmafia.print)("item_new takes no positional arguments.", "red");
      return;
    }
    (0, import_kolmafia.print)("KNOWN_UNKNOWN: Newly acquired items require verified prior/current inventory receipts."), (0, import_kolmafia.print)("Philter cleanup was NOT invoked. No items were moved or sold.");
    return;
  }
  (0, import_kolmafia.print)("Route ".concat(args.route, " -> ").concat(owner, " not implemented. No action taken."), "orange");
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {});
