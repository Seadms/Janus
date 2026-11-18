import { clock, createTrace, formatValue } from "./trace.js";

const get = id => document.getElementById(id);
const formData = form => Object.fromEntries(new FormData(form));
const localTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" });
const devicePath = id => "/api/devices/" + encodeURIComponent(id);
const isNumeric = field => ["number", "integer"].includes(field.type);
const roles = { viewer: "Viewer", operator: "Operator", administrator: "Administrator" };

async function api(path, method = "GET", data) {
  const response = await fetch(path, {
    method, cache: "no-store",
    ...(data === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
  });
  if (response.status === 401 && path !== "/api/session") location.reload();
  const result = await response.json();
  if (!response.ok) {
    const message = Array.isArray(result.detail) ? result.detail.map(error => error.msg).join(" ") : result.detail;
    throw new Error(message || "Request failed.");
  }
  return result;
}

function node(tag, text = "", className = "") {
  const item = document.createElement(tag);
  item.textContent = text;
  item.className = className;
  return item;
}

function button(label, click, style = "secondary") {
  const action = node("button", label, style);
  action.type = "button";
  action.addEventListener("click", click);
  return action;
}

function feedback(id, text = "", error = false) {
  const output = get(id);
  output.textContent = text;
  output.hidden = !text;
  output.classList.toggle("error", error);
}

function list(id, items, empty) {
  const target = get(id);
  target.replaceChildren();
  if (!items.length) {
    target.append(node("p", empty, "placeholder"));
    return;
  }
  const rows = node("ul", "", "records");
  for (const { title, detail, actions = [] } of items) {
    const row = node("li");
    const text = node("div");
    text.append(node("strong", title));
    if (detail) text.append(node("small", detail));
    row.append(text);
    if (actions.length) {
      const controls = node("div", "", "actions");
      controls.append(...actions);
      row.append(controls);
    }
    rows.append(row);
  }
  target.append(rows);
}

function confirmAction(title, description, label) {
  const dialog = get("confirm-dialog");
  get("confirm-title").textContent = title;
  get("confirm-description").textContent = description;
  get("confirm-action").textContent = label;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}

function localInput(ms) {
  const date = new Date(ms);
  return new Date(ms - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
}

export async function createWorkspace({ connect, refresh }) {
  const response = await fetch("/api/session", { cache: "no-store" });
  const enabled = response.status !== 404;
  const session = enabled && response.ok ? await response.json() : {};
  let user = session.user ?? null;
  let view = "live";
  let tab = "users";
  let device;
  let schema;
  let devices = [];
  let serial = 0;
  let historyRequest = 0;
  let historyObservers = [];
  let editingRule;
  let commandResult;
  let sending = false;
  let canCommand = false;
  const recentAcks = new Map();
  const alerts = new Map();

  function open() {
    get("login").hidden = !enabled || Boolean(user);
    get("workspace").hidden = enabled && !user;
    get("logout").hidden = !user || session.open_preview;
    for (const link of document.querySelectorAll("[data-session]")) link.hidden = !user;
    for (const link of document.querySelectorAll("[data-admin]")) link.hidden = !user?.admin;
    route();
    if (!enabled || user) connect();
  }

  get("login-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector("button");
    submit.disabled = true;
    try {
      user = (await api("/api/session", "POST", formData(form))).user;
      form.reset();
      feedback("login-error");
      open();
    } catch (error) {
      feedback("login-error", error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  get("logout").addEventListener("click", async () => {
    await api("/api/session", "DELETE");
    location.replace("/");
  });

  function route() {
    const [path, subview] = location.hash.slice(1).split("/");
    const allowed = user ? ["live", "history", "alerts", ...(user.admin ? ["admin"] : [])] : ["live"];
    view = allowed.includes(path) ? path : "live";
    tab = ["users", "devices", "access", "rules"].includes(subview) ? subview : "users";
    get("view-title").textContent = { live: "Live telemetry", history: "Past telemetry", alerts: "Alerts", admin: "Administration" }[view];
    get("window-control").hidden = view !== "live";
    get("toolbar-actions").hidden = view === "admin" && !["access", "rules"].includes(tab);
    get("jump-commands").hidden = view !== "live" || !canCommand;
    for (const name of ["live", "history", "alerts", "admin"]) {
      get("view-" + name).hidden = name !== view;
      document.querySelector('[data-view="' + name + '"]').setAttribute("aria-current", name === view ? "page" : "false");
    }
    for (const name of ["users", "devices", "access", "rules"]) {
      get("admin-" + name).hidden = name !== tab;
      document.querySelector('[data-admin-tab="' + name + '"]').setAttribute("aria-current", name === tab ? "page" : "false");
    }
    refreshView();
  }

  async function refreshView() {
    const version = ++serial;
    const id = device?.id;
    const path = id ? devicePath(id) : "";
    const current = () => version === serial;
    try {
      if (view === "alerts") {
        if (!id) return list("alert-rows", [], "Select a device to see its alerts.");
        list("alert-rows", [], "Loading alerts…");
        const result = await api("/api/alerts?device=" + encodeURIComponent(id));
        if (!current()) return;
        const merged = new Map(result.alerts.map(alert => [alert.id, alert]));
        for (const alert of alerts.get(id)?.values() ?? []) merged.set(alert.id, alert);
        alerts.set(id, merged);
        renderAlerts();
      }
      if (view !== "admin") return;
      if (tab === "users") {
        const result = await api("/api/users");
        if (current()) list("user-rows", result.users.map(entry => ({
          title: entry.username, detail: entry.admin ? "Administrator" : "Standard user",
        })), "No accounts.");
      } else if (tab === "devices") {
        list("registered-rows", devices.map(entry => ({
          title: entry.name || entry.id, detail: entry.id,
          actions: [button("Remove", async () => {
            if (!await confirmAction("Remove " + (entry.name || entry.id) + "?", "This removes its readings, alert rules, and access grants.", "Remove device")) return;
            try {
              await api(devicePath(entry.id), "DELETE");
              await refresh();
              feedback("remove-status", "Device removed.");
            } catch (error) { feedback("remove-status", error.message, true); }
          }, "danger")],
        })), "No registered devices.");
      } else if (tab === "access") {
        get("access-form").querySelector("button").disabled = !id;
        list("access-rows", [], id ? "Loading access…" : "Select a device to manage access.");
        if (!id) return;
        const [members, result] = await Promise.all([api("/api/users"), api(path + "/access")]);
        if (!current()) return;
        const picker = get("access-form").elements.username;
        const previous = picker.value;
        picker.replaceChildren(...members.users.filter(entry => !entry.admin).map(entry => new Option(entry.username, entry.username)));
        if ([...picker.options].some(option => option.value === previous)) picker.value = previous;
        get("access-form").querySelector("button").disabled = !picker.options.length;
        list("access-rows", result.access.map(entry => ({
          title: entry.username, detail: roles[entry.role], actions: [button("Revoke", async () => {
            if (!await confirmAction("Revoke access?", entry.username + " will lose access to this device.", "Revoke access")) return;
            try {
              await api(path + "/access/" + encodeURIComponent(entry.username), "DELETE");
              feedback("access-status", "Access revoked.");
              refreshView();
            } catch (error) { feedback("access-status", error.message, true); }
          })],
        })), "No access grants for this device.");
      } else if (tab === "rules") {
        get("rule-form").querySelector("button").disabled = !id || !get("rule-form").elements.field.options.length;
        list("rule-rows", [], id ? "Loading rules…" : "Select a device to manage alert rules.");
        if (!id) return;
        const result = await api(path + "/rules");
        if (!current()) return;
        list("rule-rows", result.rules.map(rule => ({
          title: (schema?.telemetry[rule.field]?.label ?? rule.field) + " " + rule.op + " " + formatValue(rule.threshold),
          detail: rule.enabled ? "Enabled" : "Disabled",
          actions: [
            button("Edit", () => editRule(rule)),
            button("Delete", async () => {
              if (!await confirmAction("Delete alert rule?", "Existing alerts stay in the log.", "Delete rule")) return;
              try {
                await api(path + "/rules/" + rule.id, "DELETE");
                if (editingRule === rule.id) editRule();
                feedback("rule-status", "Rule deleted.");
                refreshView();
              } catch (error) { feedback("rule-status", error.message, true); }
            }, "danger"),
          ],
        })), "No alert rules for this device.");
      }
    } catch (error) {
      if (!current()) return;
      const target = view === "alerts" ? "alert-rows" : { users: "user-rows", access: "access-rows", rules: "rule-rows", devices: "registered-rows" }[tab];
      if (target) list(target, [], error.message);
    }
  }

  function editRule(rule) {
    const form = get("rule-form");
    editingRule = rule?.id;
    form.reset();
    get("rule-title").textContent = rule ? "Edit alert rule" : "Create alert rule";
    get("cancel-rule").hidden = !rule;
    if (rule) {
      form.elements.field.value = rule.field;
      form.elements.op.value = rule.op;
      form.elements.threshold.value = rule.threshold;
      form.elements.enabled.checked = Boolean(rule.enabled);
      form.elements.field.focus();
    }
  }

  function renderAlerts() {
    const entries = [...(alerts.get(device?.id)?.values() ?? [])].sort((a, b) => b.timestamp - a.timestamp);
    list("alert-rows", entries.slice(0, 100).map(entry => {
      const field = schema?.telemetry[entry.field];
      return {
        title: (field?.label ?? entry.field) + " " + entry.op + " " + formatValue(entry.threshold),
        detail: "Reading: " + formatValue(entry.value) + " " + (field?.unit ?? "") + " · " + localTime.format(entry.timestamp * 1000),
      };
    }), "No alerts for this device.");
  }

  function clearHistory() {
    historyRequest++;
    historyObservers.forEach(observer => observer.disconnect());
    historyObservers = [];
    get("history-results").replaceChildren();
    feedback("history-status");
  }

  function commandFields() {
    const name = get("command-picker").value;
    const args = schema?.commands?.[name]?.args ?? {};
    const target = get("command-args");
    target.replaceChildren();
    for (const [key, field] of Object.entries(args)) {
      const label = node("label", (field.label ?? key) + (field.unit ? " (" + field.unit + ")" : ""));
      const input = document.createElement("input");
      input.name = key;
      if (isNumeric(field)) {
        input.type = "number";
        input.step = field.type === "integer" ? "1" : "any";
        if (field.min != null) input.min = field.min;
        if (field.max != null) input.max = field.max;
        input.required = true;
      } else if (field.type === "boolean") {
        input.type = "checkbox";
        label.className = "inline-check";
      }
      label.append(input);
      target.append(label);
    }
  }

  function context(nextDevice, nextSchema, nextDevices) {
    if (!enabled) return;
    const inventoryChanged = nextDevices.map(entry => entry.id + ":" + entry.name).join("|") !== devices.map(entry => entry.id + ":" + entry.name).join("|");
    const contextChanged = nextDevice?.id !== device?.id || nextSchema !== schema;
    devices = nextDevices;
    device = nextDevice;
    schema = nextSchema;
    canCommand = Boolean(device && device.role && device.role !== "viewer" && Object.keys(schema?.commands ?? {}).length);
    get("commands").hidden = !canCommand;
    get("jump-commands").hidden = view !== "live" || !canCommand;
    get("command-send").disabled = !device?.online || sending || Boolean(commandResult?.pending);
    if (!contextChanged) {
      if (inventoryChanged && view === "admin" && tab === "devices") refreshView();
      return;
    }
    commandResult = undefined;
    feedback("command-result");
    get("command-picker").replaceChildren(...Object.entries(schema?.commands ?? {}).map(([key, entry]) => new Option(entry.label ?? key, key)));
    commandFields();
    const fields = get("history-fields");
    fields.replaceChildren(...Object.entries(schema?.telemetry ?? {}).map(([key, field], index) => {
      const label = node("label", field.label ?? key, "choice");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "field";
      input.value = key;
      input.checked = index === 0;
      label.prepend(input);
      return label;
    }));
    get("query-history").disabled = !fields.children.length;
    clearHistory();
    get("rule-form").elements.field.replaceChildren(...Object.entries(schema?.telemetry ?? {}).filter(([, field]) => isNumeric(field))
      .map(([key, field]) => new Option(field.label ?? key, key)));
    editRule();
    refreshView();
  }

  function finishCommand(ack) {
    if (commandResult?.id !== ack.id || commandResult?.device !== ack.device_id) return;
    commandResult.pending = false;
    feedback("command-result", (ack.ok ? "Acknowledged" : ack.error || "Rejected") + " · " + ack.id, !ack.ok);
  }

  function message(payload) {
    if (payload.type === "alert" && payload.alert) {
      const id = payload.device_id;
      if (!alerts.has(id)) alerts.set(id, new Map());
      const deviceAlerts = alerts.get(id);
      deviceAlerts.set(payload.alert.id, payload.alert);
      if (deviceAlerts.size > 100) deviceAlerts.delete(deviceAlerts.keys().next().value);
      if (view === "alerts" && device?.id === id) renderAlerts();
    } else if (payload.type === "ack") {
      recentAcks.set(payload.id, payload);
      if (recentAcks.size > 64) recentAcks.delete(recentAcks.keys().next().value);
      finishCommand(payload);
    } else if (["access_changed", "device_removed"].includes(payload.type)) {
      alerts.clear();
      refresh();
    }
  }

  function bindForm(id, status, action) {
    const form = get(id);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const submit = form.querySelector('button:not([type="button"])');
      submit.disabled = true;
      feedback(status);
      try { await action(form); }
      catch (error) { feedback(status, error.message, true); }
      finally { submit.disabled = false; }
    });
  }

  bindForm("user-form", "user-status", async form => {
    const result = await api("/api/users", "POST", formData(form));
    form.reset();
    feedback("user-status", result.username + " was created.");
    refreshView();
  });
  get("schema-file").addEventListener("change", async event => {
    const file = event.target.files[0];
    if (file) get("device-form").elements.schema.value = await file.text();
  });
  bindForm("device-form", "register-status", async form => {
    let data;
    try { data = JSON.parse(form.elements.schema.value); }
    catch { throw new Error("Enter a valid JSON schema."); }
    const result = await api("/api/devices", "POST", data);
    form.reset();
    await refresh();
    feedback("register-status", result.id + " was registered.");
  });
  bindForm("access-form", "access-status", async form => {
    await api(devicePath(device.id) + "/access", "PUT", formData(form));
    feedback("access-status", "Access saved.");
    refreshView();
  });
  bindForm("rule-form", "rule-status", async form => {
    const data = formData(form);
    data.threshold = form.elements.threshold.valueAsNumber;
    data.enabled = form.elements.enabled.checked;
    const previous = editingRule;
    const path = devicePath(device.id) + "/rules" + (previous ? "/" + previous : "");
    await api(path, previous ? "PUT" : "POST", data);
    editRule();
    feedback("rule-status", previous ? "Rule updated." : "Rule created.");
    refreshView();
  });
  get("cancel-rule").addEventListener("click", () => editRule());
  get("refresh-alerts").addEventListener("click", refreshView);
  get("command-picker").addEventListener("change", commandFields);
  get("jump-commands").addEventListener("click", () => get("command-picker").focus());
  get("command-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (sending || commandResult?.pending || !device?.online || !device.role || device.role === "viewer") return;
    const id = device.id;
    const name = get("command-picker").value;
    const args = Object.fromEntries([...get("command-args").querySelectorAll("input")].map(input => [
      input.name, input.type === "number" ? input.valueAsNumber : input.type === "checkbox" ? input.checked : input.value,
    ]));
    sending = true;
    get("command-send").disabled = true;
    feedback("command-result", "Sending…");
    try {
      const result = await api(devicePath(id) + "/commands", "POST", { name, args });
      if (device?.id !== id) return;
      const pending = { id: result.id, device: id, pending: true };
      commandResult = pending;
      const ack = recentAcks.get(result.id);
      if (ack) finishCommand(ack);
      else {
        feedback("command-result", "Waiting for device · " + result.id);
        setTimeout(() => {
          if (commandResult === pending && pending.pending) {
            pending.pending = false;
            feedback("command-result", "No acknowledgement received · " + result.id, true);
          }
        }, 8000);
      }
    } catch (error) {
      if (device?.id === id) feedback("command-result", error.message, true);
    } finally {
      sending = false;
    }
  });

  const now = Date.now();
  get("history-start").value = localInput(now - 60000);
  get("history-end").value = localInput(now);
  get("query-history").disabled = true;
  bindForm("history-form", "history-status", async form => {
    const fields = new FormData(form).getAll("field");
    if (!fields.length) throw new Error("Choose at least one field.");
    if (!device || !schema) throw new Error("Select a device with a schema.");
    const start = new Date(get("history-start").value).getTime();
    const end = new Date(get("history-end").value).getTime();
    if (!(start < end) || end - start > 14 * 86400000) throw new Error("Choose a time range of up to 14 days.");
    clearHistory();
    const request = historyRequest;
    const selectedSchema = schema;
    const query = new URLSearchParams({ start: start / 1000, end: end / 1000 });
    for (const field of fields) query.append("fields", field);
    const result = await api(devicePath(device.id) + "/telemetry?" + query);
    if (request !== historyRequest) return;
    if (!result.samples.length) return feedback("history-status", "No readings in this time range.");
    for (const key of fields) {
      const field = selectedSchema.telemetry[key];
      const name = field.label ?? key;
      const panel = node("section", "", "panel form-panel");
      const heading = node("h2", name + (field.unit ? " · " + field.unit : ""));
      panel.append(heading);
      get("history-results").append(panel);
      if (!isNumeric(field)) {
        const values = node("ul", "", "records");
        for (const sample of result.samples.slice(-25)) {
          values.append(node("li", clock.format(sample.timestamp * 1000) + " · " + String(sample.data[key] ?? "—")));
        }
        panel.append(values);
        continue;
      }
      const chart = node("div", "", "chart history-chart");
      const canvas = node("canvas");
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", name + " over the selected period");
      const tooltip = node("output", "", "tooltip");
      tooltip.hidden = true;
      chart.append(canvas, tooltip);
      panel.append(chart);
      const points = result.samples.filter(sample => Number.isFinite(sample.data[key])).map(sample => ({
        time: sample.timestamp * 1000, value: sample.data[key],
      }));
      if (!points.length) chart.replaceChildren(node("p", "No numeric readings in this window.", "placeholder"));
      else {
        const draw = createTrace(canvas, tooltip, chart);
        const update = () => draw(points, start, end, field.unit ?? "", Math.max(1000, (end - start) / 200), true);
        const observer = new ResizeObserver(update);
        observer.observe(chart);
        historyObservers.push(observer);
        for (const type of ["pointermove", "pointerleave", "pointercancel"]) canvas.addEventListener(type, update);
      }
    }
  });

  window.addEventListener("hashchange", route);
  return { enabled, open, context, message, checkSession: () => api("/api/session").then(result => Boolean(result.user)) };
}
