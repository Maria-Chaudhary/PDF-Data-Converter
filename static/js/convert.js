/* DocuExtract converter page: upload queue, preview tabs, editable invoice, exports */
(function () {
    "use strict";

    const { $, esc, fmtSize, plural, toast } = DX;
    const PAGE = window.PAGE;
    const MAX_BYTES = PAGE.maxFileMb * 1024 * 1024;
    const CONCURRENCY = 2;
    const ROW_PREVIEW_LIMIT = 200;
    const JSON_PREVIEW_LIMIT = 150000;

    const FORMATS = {
        xlsx: { label: "Excel (.xlsx)", short: "Excel" },
        csv: { label: "CSV", short: "CSV" },
        json: { label: "JSON", short: "JSON" },
        invoice_json: { label: "Invoice JSON", short: "Invoice JSON" },
        invoice_xlsx: { label: "Invoice Excel", short: "Invoice Excel" },
    };
    const MODES = {
        excel: { formats: ["xlsx"], tab: "tables" },
        csv: { formats: ["csv"], tab: "tables" },
        json: { formats: ["json"], tab: "json" },
        invoice: { formats: ["invoice_json", "invoice_xlsx"], tab: "invoice" },
        batch: { formats: ["xlsx", "csv", "json", "invoice_xlsx", "invoice_json"], tab: "tables", select: true },
    };
    const cfg = MODES[PAGE.mode];

    const INVOICE_FIELDS = [
        ["invoice_number", "Invoice number", "text", "e.g. INV-1042"],
        ["invoice_date", "Invoice date", "text", "e.g. 21/11/2026"],
        ["due_date", "Due date", "text", "e.g. 05/12/2026"],
        ["currency", "Currency", "text", "e.g. USD"],
        ["subtotal", "Subtotal", "num", "0.00"],
        ["discount", "Discount", "num", "0.00"],
        ["shipping", "Shipping", "num", "0.00"],
        ["tax_rate", "Tax rate (%)", "num", "0"],
        ["tax", "Tax / VAT / GST", "num", "0.00"],
        ["total", "Total", "num", "0.00"],
        ["amount_due", "Amount due", "num", "0.00"],
        ["email", "Email", "text", "name@company.com"],
        ["phone", "Phone", "text", "+1 555 0100"],
    ];
    const CHECKED_FIELDS = new Set(["invoice_number", "invoice_date", "subtotal", "tax", "total"]);

    /* ---------- state ---------- */
    let files = [];
    let activeId = null;
    let tab = cfg.tab;
    let sheetIndex = 0;
    let nextId = 1;
    let running = 0;
    let batchToastShown = true;
    let selectedFormat = cfg.formats[0];

    const el = {
        drop: $("#drop"), input: $("#file"), dropTitle: $("#dropTitle"), queue: $("#queue"),
        overall: $("#overall"), overallBar: $("#overallBar"), overallLabel: $("#overallLabel"), overallPct: $("#overallPct"),
        chips: $("#resChips"), alerts: $("#resAlerts"), tabs: $("#tabs"), body: $("#resBody"), actions: $("#actions"),
    };

    DX.dropzone(el.drop, el.input, addFiles);

    const active = () => files.find(f => f.id === activeId) || null;
    const done = () => files.filter(f => f.status === "done");
    const busy = f => ["checking", "queued", "uploading", "processing"].includes(f.status);

    /* ---------- adding files ---------- */
    function fail(entry, message, code) {
        entry.status = "error";
        entry.error = message;
        entry.progress = 0;
        DX.history.add({ name: entry.name, tool: "Failed", pages: entry.pages, size: entry.size, status: "failed", note: message });
    }

    function addFiles(list) {
        const room = PAGE.maxFiles - files.length;
        if (list.length > room) {
            toast(`You can upload up to ${PAGE.maxFiles} files at once. Extra files were skipped.`, "error");
            list = list.slice(0, Math.max(room, 0));
        }

        let skipped = 0;
        list.forEach(file => {
            if (files.some(f => f.name === file.name && f.size === file.size)) { skipped++; return; }

            const entry = {
                id: nextId++, file, name: file.name, size: file.size, pages: null,
                status: "checking", progress: 0.04, stage: "Checking file…", error: null,
                result: null, original: null, checkSeq: 0,
            };

            if (!/\.pdf$/i.test(file.name)) fail(entry, "Only PDF files are supported.");
            else if (file.size === 0) fail(entry, "This file is empty (0 bytes).");
            else if (file.size > MAX_BYTES) fail(entry, `This file is ${fmtSize(file.size)}, over the ${PAGE.maxFileMb} MB limit.`);

            files.push(entry);
            if (entry.status === "checking") inspect(entry);
        });

        if (skipped) toast(`${plural(skipped, "file")} already added.`, "info");
        if (!active() && files.length) activeId = (files.find(f => f.status !== "error") || files[0]).id;

        batchToastShown = false;
        renderAll();
    }

    async function inspect(entry) {
        try {
            const fd = new FormData();
            fd.append("pdf", entry.file);
            const info = await DX.json("/info", { body: fd });
            entry.pages = info.pages;
            entry.status = "queued";
            entry.stage = "Waiting…";
            entry.progress = 0.1;
        } catch (err) {
            fail(entry, err.message);
            toast(`${entry.name}: ${err.message}`, "error", 6500);
        }
        renderQueue();
        renderOverall();
        if (entry.id === activeId) renderResults();
        pump();
    }

    /* ---------- processing queue ---------- */
    function pump() {
        while (running < CONCURRENCY) {
            const next = files.find(f => f.status === "queued");
            if (!next) break;
            process(next);
        }
        maybeFinish();
    }

    async function process(entry) {
        running++;
        entry.status = "uploading";
        entry.stage = "Uploading…";
        renderQueue();
        if (entry.id === activeId) renderResults();

        const fd = new FormData();
        fd.append("pdf", entry.file);

        try {
            const result = await DX.json("/preview", {
                body: fd,
                onUpload: p => {
                    entry.progress = 0.1 + p * 0.4;
                    entry.stage = `Uploading ${Math.round(p * 100)}%`;
                    scheduleQueue();
                },
                onUploadDone: () => {
                    entry.status = "processing";
                    entry.progress = 0.6;
                    entry.stage = "Reading text and tables…";
                    renderQueue();
                    if (entry.id === activeId) renderResults();
                },
            });

            entry.result = result;
            entry.original = JSON.parse(JSON.stringify(result.invoice || {}));
            entry.status = "done";
            entry.progress = 1;
            entry.stage = "";

            if (files.length === 1) {
                toast(`${entry.name} is ready: ${plural(result.tables.length, "table")} found.`, "success");
            }
        } catch (err) {
            fail(entry, err.message);
            if (files.length === 1) toast(err.message, "error", 6500);
        }

        running--;
        renderQueue();
        renderOverall();
        if (entry.id === activeId || !active()) renderResults();
        else renderActions();
        pump();
    }

    function maybeFinish() {
        if (batchToastShown || files.length < 2 || files.some(busy)) return;
        batchToastShown = true;
        const ok = done().length, bad = files.filter(f => f.status === "error").length;
        toast(
            `Processed ${plural(ok, "file")}${bad ? `, ${bad} failed` : ""}. ` +
            (ok ? "Review the results, then download." : ""),
            bad && !ok ? "error" : "success"
        );
    }

    /* ---------- rendering: queue ---------- */
    let queueFrame = 0;
    function scheduleQueue() {
        if (queueFrame) return;
        queueFrame = requestAnimationFrame(() => { queueFrame = 0; renderQueue(); renderOverall(); });
    }

    function badgeFor(f) {
        switch (f.status) {
            case "checking": return '<span class="badge busy">Checking</span>';
            case "queued": return '<span class="badge busy">Queued</span>';
            case "uploading": return '<span class="badge busy">Uploading</span>';
            case "processing": return '<span class="badge busy">Processing</span>';
            case "error": return '<span class="badge bad">Failed</span>';
            default: {
                const n = (f.result.warnings || []).filter(w => w.level !== "info").length +
                    (isInvoiceView(f) ? invoiceIssues(f) : 0);
                return n ? `<span class="badge warn">Ready · ${plural(n, "warning")}</span>` : '<span class="badge good">Ready</span>';
            }
        }
    }

    const isInvoiceView = f => PAGE.mode === "invoice" || (f.result && f.result.is_invoice);
    const invoiceIssues = f => (f.result.invoice_warnings || []).filter(w => w.level !== "info").length;

    function renderQueue() {
        $("#dropTitle").textContent = files.length ? "Add more PDFs" : "Drag & drop PDFs here";
        el.drop.classList.toggle("compact", files.length > 0);

        el.queue.innerHTML = files.map(f => {
            const meta = [
                `<span>${fmtSize(f.size)}</span>`,
                f.pages ? `<span>${plural(f.pages, "page")}</span>` : "",
                f.result && f.result.kind === "scanned" ? "<span>Scanned · OCR</span>" : "",
                busy(f) && f.stage ? `<span>${esc(f.stage)}</span>` : "",
            ].join("");

            const bar = busy(f)
                ? `<div class="qprog"><div class="progress ${f.status === "processing" ? "indeterminate" : ""}"><i style="width:${Math.round(f.progress * 100)}%"></i></div></div>`
                : "";

            return `
            <li class="qitem ${f.id === activeId ? "active" : ""} ${f.status}" data-id="${f.id}" tabindex="0" role="button" aria-label="Show ${esc(f.name)}">
                <div class="qicon">${DX.svg(f.status === "error" ? "alert" : f.status === "done" ? "check" : "file")}</div>
                <div>
                    <div class="qname">${esc(f.name)}</div>
                    <div class="qmeta">${meta}</div>
                    ${f.error ? `<div class="qerr">${esc(f.error)}</div>` : ""}
                </div>
                <div class="qright">${badgeFor(f)}
                    <button class="icon-btn" data-remove="${f.id}" aria-label="Remove ${esc(f.name)}" title="Remove">${DX.svg("x", 16)}</button>
                </div>
                ${bar}
            </li>`;
        }).join("");
    }

    el.queue.addEventListener("click", event => {
        const remove = event.target.closest("[data-remove]");
        if (remove) {
            event.stopPropagation();
            files = files.filter(f => f.id !== Number(remove.dataset.remove));
            if (!active()) activeId = files.length ? files[0].id : null;
            renderAll();
            return;
        }
        const item = event.target.closest(".qitem");
        if (item) setActive(Number(item.dataset.id));
    });
    el.queue.addEventListener("keydown", event => {
        const item = event.target.closest(".qitem");
        if (item && (event.key === "Enter" || event.key === " ") && event.target === item) {
            event.preventDefault();
            setActive(Number(item.dataset.id));
        }
    });

    function setActive(id) {
        activeId = id;
        sheetIndex = 0;
        renderQueue();
        renderResults();
    }

    function renderOverall() {
        const pending = files.filter(busy);
        el.overall.hidden = !pending.length;
        if (!pending.length) return;

        const total = files.filter(f => f.status !== "error" || f.pages).length || files.length;
        const finished = files.filter(f => f.status === "done" || f.status === "error").length;
        const pct = Math.round((files.reduce((sum, f) => sum + (f.status === "error" ? 1 : f.progress), 0) / files.length) * 100);

        el.overallLabel.textContent = files.length === 1
            ? (files[0].stage || "Processing…")
            : `Processing ${Math.min(finished + 1, files.length)} of ${files.length} files…`;
        el.overallPct.textContent = pct + "%";
        el.overallBar.setAttribute("aria-valuenow", pct);
        el.overallBar.querySelector("i").style.width = pct + "%";
        void total;
    }

    /* ---------- rendering: results ---------- */
    function renderAll() {
        renderQueue();
        renderOverall();
        renderResults();
        pump();
    }

    function emptyState(icon, title, text, extra = "") {
        return `<div class="empty"><div class="empty-icon">${DX.svg(icon, 26)}</div><h3>${esc(title)}</h3><p>${text}</p>${extra}</div>`;
    }

    function renderResults() {
        const f = active();
        el.chips.innerHTML = "";
        el.alerts.hidden = true;
        el.tabs.hidden = true;

        if (!f) {
            el.body.innerHTML = emptyState("upload", "No PDF yet",
                "Upload a PDF above to preview extracted tables, text and invoice fields here.");
            renderActions();
            return;
        }

        if (f.status === "error") {
            el.body.innerHTML = emptyState("alert", "This file couldn't be processed", esc(f.error || "Unknown error."),
                `<p class="small" style="margin-top:10px">Remove it from the list and try another PDF.</p>`);
            renderActions();
            return;
        }

        if (f.status !== "done") {
            el.body.innerHTML = `
                <p class="muted small" style="margin-bottom:10px"><b>${esc(f.name)}</b>: ${esc(f.stage || "Preparing…")}</p>
                <div class="skeleton" aria-busy="true">${"<i></i>".repeat(9)}</div>`;
            renderActions();
            return;
        }

        const r = f.result;
        const kindBadge = {
            text: '<span class="badge info">Text PDF</span>',
            scanned: '<span class="badge warn">Scanned · OCR</span>',
            mixed: '<span class="badge warn">Mixed · partly OCR</span>',
            empty: '<span class="badge bad">No text found</span>',
        }[r.kind] || "";
        el.chips.innerHTML = `<span class="badge">${plural(r.pages, "page")}</span>
            <span class="badge">${plural(r.tables.length, "table")}</span>${kindBadge}`;

        renderAlerts(f);
        renderTabs(f);
        renderTab(f);
        renderActions();
    }

    function renderAlerts(f) {
        const r = f.result;
        const html = [];

        if (r.ocr_used) {
            const conf = r.pages_detail.filter(p => p.method === "ocr" && p.confidence != null).map(p => p.confidence);
            const avg = conf.length ? Math.round(conf.reduce((a, b) => a + b, 0) / conf.length) : null;
            html.push(alert("info", "scan", `<b>Scanned PDF detected.</b> Text was read with OCR on ${plural(r.ocr_pages.length, "page")}` +
                (avg != null ? ` (about ${avg}% confidence)` : "") + ". Always double-check numbers."));
        }

        const warnings = (r.warnings || []).filter(w => !(w.code === "no_tables" && r.tables.length === 0 && PAGE.mode === "invoice"));
        warnings.slice(0, 5).forEach(w =>
            html.push(alert(w.level === "error" ? "bad" : w.level === "warning" ? "warn" : "info",
                w.level === "info" ? "info" : "alert", esc(w.message))));
        if (warnings.length > 5) html.push(alert("info", "info", `${warnings.length - 5} more notice(s) not shown.`));

        if (!html.length && r.kind !== "empty") {
            html.push(alert("good", "check", `<b>Extraction complete.</b> ${plural(r.tables.length, "table")} found across ${plural(r.pages, "page")}.`));
        }

        el.alerts.innerHTML = html.join("");
        el.alerts.hidden = !html.length;
    }

    function alert(kind, icon, html) {
        return `<div class="alert ${kind}">${DX.svg(icon, 18)}<div>${html}</div></div>`;
    }

    function renderTabs(f) {
        const issues = invoiceIssues(f);
        const tabs = [
            ["tables", `Tables <span class="badge">${f.result.tables.length}</span>`],
            ["invoice", `Invoice ${issues ? `<span class="badge warn">${issues}</span>` : ""}`],
            ["text", "Text"],
            ["json", "JSON"],
        ];
        el.tabs.innerHTML = tabs.map(([key, label]) =>
            `<button class="tab ${key === tab ? "on" : ""}" role="tab" aria-selected="${key === tab}" data-tab="${key}">${label}</button>`).join("");
        el.tabs.hidden = false;
    }

    el.tabs.addEventListener("click", event => {
        const button = event.target.closest("[data-tab]");
        if (!button) return;
        tab = button.dataset.tab;
        const f = active();
        if (f && f.status === "done") { renderTabs(f); renderTab(f); }
    });

    function renderTab(f) {
        ({ tables: renderTables, invoice: renderInvoice, text: renderText, json: renderJSON }[tab] || renderTables)(f);
    }

    /* ----- tables tab ----- */
    const NUMERIC = /^[-+(]?[$€£]?\s?[\d,]+(\.\d+)?\)?%?$/;

    function renderTables(f) {
        const tables = f.result.tables;
        if (!tables.length) {
            const hasText = f.result.pages_detail.some(p => p.text.trim());
            el.body.innerHTML = emptyState("table", "No tables found",
                hasText
                    ? "This PDF has text but no table structure we could detect. You can still copy or export the text."
                    : "There was no readable text in this PDF.",
                hasText ? `<button class="btn secondary sm" style="margin-top:12px" data-goto="text">View extracted text</button>` : "");
            return;
        }

        sheetIndex = Math.min(sheetIndex, tables.length - 1);
        const t = tables[sheetIndex];
        const shown = t.rows.slice(0, ROW_PREVIEW_LIMIT);

        el.body.innerHTML = `
            <div class="tools-row">
                <div class="muted small"><b>${esc(t.name)}</b> · page ${t.page} · ${plural(t.rows.length, "row")} × ${plural(t.header.length, "column")}</div>
                <div><button class="btn secondary sm" id="copyTable">Copy table</button></div>
            </div>
            <div class="sheetwrap"><table class="data">
                <thead><tr><th class="rownum">#</th>${t.header.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>
                <tbody>${shown.map((row, i) => `<tr><td class="rownum">${i + 1}</td>${row.map(c =>
                    `<td class="${NUMERIC.test(c) ? "num" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody>
            </table></div>
            ${t.rows.length > shown.length ? `<p class="muted small" style="margin-top:8px">Showing the first ${shown.length} of ${t.rows.length} rows. Downloads include every row.</p>` : ""}
            <div class="sheets" role="tablist" aria-label="Tables">${tables.map((x, i) =>
                `<button class="sheet-tab ${i === sheetIndex ? "on" : ""}" data-sheet="${i}">${esc(x.name)}<small>${x.rows.length}</small></button>`).join("")}</div>`;

        $("#copyTable").addEventListener("click", async () => {
            const tsv = [t.header, ...t.rows].map(r => r.join("\t")).join("\n");
            toast(await DX.copy(tsv) ? "Table copied. Paste it into Excel or Sheets." : "Couldn't copy automatically.", "success");
        });
    }

    el.body.addEventListener("click", event => {
        const sheet = event.target.closest("[data-sheet]");
        if (sheet) { sheetIndex = Number(sheet.dataset.sheet); const f = active(); if (f) renderTables(f); return; }
        const go = event.target.closest("[data-goto]");
        if (go) { tab = go.dataset.goto; const f = active(); if (f) { renderTabs(f); renderTab(f); } }
    });

    /* ----- invoice tab ----- */
    const initialValue = (key, value) => {
        if (value == null || value === "") return "";
        if (typeof value === "number") return key === "tax_rate" ? String(+value.toFixed(2)) : value.toFixed(2);
        return String(value);
    };

    function renderInvoice(f) {
        const r = f.result;
        const inv = r.invoice || {};
        const notInvoice = !r.is_invoice
            ? alert("warn", "alert", "<b>This doesn't look like an invoice.</b> The fields below may be empty or wrong. You can still enter values by hand.")
            : "";

        el.body.innerHTML = `
            ${notInvoice}
            <div id="invWarnings" style="margin-bottom:14px"></div>

            <div class="section-title"><span>Invoice fields <span class="muted small">· click any field to edit</span></span>
                <span><button class="btn secondary sm" id="invReset">Reset to detected</button>
                      <button class="btn secondary sm" id="invCopy">Copy JSON</button></span></div>
            <div class="form-grid">
                ${INVOICE_FIELDS.map(([key, label, type, hint]) => {
                    const v = initialValue(key, inv[key]);
                    return `<div class="field" data-field="${key}">
                        <label for="inv_${key}"><span>${esc(label)}</span><span class="tag"></span></label>
                        <input id="inv_${key}" data-key="${key}" value="${esc(v)}" placeholder="${esc(hint)}"
                               ${type === "num" ? 'inputmode="decimal"' : ""} autocomplete="off">
                    </div>`;
                }).join("")}
            </div>

            ${r.line_items && r.line_items.length ? `
            <div class="section-title">Line items <span class="muted small">${r.line_items.length} detected</span></div>
            <div class="sheetwrap"><table class="data">
                <thead><tr><th>Description</th><th>Qty</th><th>Unit price</th><th>Amount</th></tr></thead>
                <tbody>${r.line_items.map(i => `<tr><td>${esc(i.description)}</td>
                    <td class="num">${i.quantity ?? ""}</td><td class="num">${i.unit_price != null ? i.unit_price.toFixed(2) : ""}</td>
                    <td class="num">${i.amount.toFixed(2)}</td></tr>`).join("")}</tbody>
            </table></div>` : ""}

            <p class="muted small" style="margin-top:14px">Fields are detected with text patterns, not AI. Values you change here are used in your downloads.</p>`;

        refreshFieldStates(f);
        renderInvoiceWarnings(f);
    }

    function refreshFieldStates(f) {
        const orig = f.original || {};
        document.querySelectorAll("[data-field]").forEach(box => {
            const key = box.dataset.field;
            const value = box.querySelector("input").value.trim();
            const edited = value !== initialValue(key, orig[key]);
            const missing = value === "" && CHECKED_FIELDS.has(key);
            box.classList.toggle("edited", edited);
            box.classList.toggle("missing", missing);
            box.querySelector(".tag").textContent = edited ? "edited" : missing ? "missing" : "";
        });
    }

    function renderInvoiceWarnings(f) {
        const box = $("#invWarnings");
        if (!box) return;
        const list = f.result.invoice_warnings || [];
        const problems = list.filter(w => w.level !== "info");
        const infos = list.filter(w => w.level === "info");

        box.innerHTML = !list.length
            ? alert("good", "check", "<b>Looks consistent.</b> Subtotal, tax and total add up and the key fields were found.")
            : [...problems, ...infos].map(w =>
                alert(w.level === "error" ? "bad" : w.level === "warning" ? "warn" : "info",
                    w.level === "info" ? "info" : "alert", esc(w.message))).join("");
        renderTabs(f);
    }

    let invoiceTimer = 0;
    el.body.addEventListener("input", event => {
        const input = event.target.closest("[data-key]");
        const f = active();
        if (!input || !f || !f.result) return;

        f.result.invoice[input.dataset.key] = input.value;
        refreshFieldStates(f);

        clearTimeout(invoiceTimer);
        invoiceTimer = setTimeout(() => recheckInvoice(f), 350);
    });

    async function recheckInvoice(f) {
        const seq = ++f.checkSeq;
        try {
            const out = await DX.json("/invoice-check", {
                json: { invoice: f.result.invoice, line_items: f.result.line_items || [] },
            });
            if (seq !== f.checkSeq) return;          // a newer edit is already being checked
            f.result.invoice_warnings = out.warnings;
            f.result.invoice_missing = out.missing;
            f.result.invoice_norm = out.invoice;
            if (f.id === activeId && tab === "invoice") renderInvoiceWarnings(f);
            renderQueue();
        } catch (_) { /* validation is advisory; ignore transient errors */ }
    }

    el.body.addEventListener("click", async event => {
        const f = active();
        if (!f || !f.result) return;

        if (event.target.closest("#invReset")) {
            f.result.invoice = JSON.parse(JSON.stringify(f.original));
            renderInvoice(f);
            recheckInvoice(f);
            toast("Restored the detected values.", "info");
        } else if (event.target.closest("#invCopy")) {
            const ok = await DX.copy(JSON.stringify(f.result.invoice_norm || f.result.invoice, null, 2));
            toast(ok ? "Invoice JSON copied." : "Couldn't copy automatically.", ok ? "success" : "error");
        }
    });

    /* ----- text tab ----- */
    function plainText(f) {
        const pages = f.result.pages_detail.filter(p => p.text.trim());
        return pages.length === 1 && f.result.pages === 1
            ? pages[0].text
            : pages.map(p => `--- Page ${p.page} ---\n${p.text}`).join("\n\n");
    }

    function renderText(f) {
        const pages = f.result.pages_detail.filter(p => p.text.trim());
        if (!pages.length) {
            el.body.innerHTML = emptyState("scan", "No text found",
                f.result.ocr_available
                    ? "OCR couldn't find readable text in this PDF."
                    : "This looks like a scanned PDF and OCR (Tesseract) isn't installed on the server, so no text could be read.");
            return;
        }

        el.body.innerHTML = `
            <div class="tools-row">
                <div class="muted small">${plural(pages.length, "page")} with text${f.result.ocr_used ? " · includes OCR text" : ""}</div>
                <div><button class="btn secondary sm" id="copyText">Copy text</button>
                     <button class="btn secondary sm" id="saveText">Download .txt</button></div>
            </div>
            <pre class="text-view">${pages.map(p =>
                `<span class="page-sep">--- Page ${p.page}${p.method === "ocr" ? ` · OCR${p.confidence != null ? ` ${Math.round(p.confidence)}%` : ""}` : ""} ---</span>\n${esc(p.text)}`
            ).join("\n\n")}</pre>`;

        $("#copyText").addEventListener("click", () => copyText(f));
        $("#saveText").addEventListener("click", () => saveText(f));
    }

    async function copyText(f) {
        const text = plainText(f);
        if (!text.trim()) { toast("There is no text to copy.", "error"); return; }
        toast(await DX.copy(text) ? "Text copied to clipboard." : "Couldn't copy automatically.", "success");
    }

    function saveText(f) {
        const text = plainText(f);
        if (!text.trim()) { toast("There is no text to download.", "error"); return; }
        DX.save(new Blob([text], { type: "text/plain;charset=utf-8" }), f.name.replace(/\.pdf$/i, "") + ".txt");
        toast("Text file downloaded.", "success");
    }

    /* ----- json tab (mirrors the server's JSON export) ----- */
    function jsonFor(f) {
        const r = f.result;
        return {
            document: f.name.replace(/\.pdf$/i, ""),
            page_count: r.pages,
            document_kind: r.kind,
            total_tables: r.tables.length,
            ocr_used: r.ocr_used,
            ocr_pages: r.ocr_pages,
            warnings: (r.warnings || []).map(w => w.message),
            tables: r.tables.map(t => ({
                page: t.page, table_index: t.index, headers: t.header,
                rows: t.rows.map(row => Object.fromEntries(t.header.map((h, i) => [h, row[i] ?? ""]))),
            })),
            invoice_data: r.invoice_norm || r.invoice,
            line_items: r.line_items || [],
            page_text: Object.fromEntries(r.pages_detail.map(p => [p.page, p.text])),
        };
    }

    function renderJSON(f) {
        const text = JSON.stringify(jsonFor(f), null, 2);
        const truncated = text.length > JSON_PREVIEW_LIMIT;
        el.body.innerHTML = `
            <div class="tools-row">
                <div class="muted small">Structured preview of the JSON export</div>
                <div><button class="btn secondary sm" id="copyJson">Copy JSON</button></div>
            </div>
            <pre class="json-view">${esc(truncated ? text.slice(0, JSON_PREVIEW_LIMIT) + "\n… preview truncated" : text)}</pre>
            ${truncated ? '<p class="muted small" style="margin-top:8px">Preview truncated. The download contains everything.</p>' : ""}`;
        $("#copyJson").addEventListener("click", async () =>
            toast(await DX.copy(text) ? "JSON copied to clipboard." : "Couldn't copy automatically.", "success"));
    }

    /* ---------- actions / downloads ---------- */
    function renderActions() {
        const f = active();
        const ready = f && f.status === "done";
        const doneCount = done().length;

        if (!files.length) { el.actions.hidden = true; return; }
        el.actions.hidden = false;

        const picker = cfg.select
            ? `<select id="fmtSel" class="btn secondary" aria-label="Export format" style="padding:10px 12px">
                ${cfg.formats.map(k => `<option value="${k}" ${k === selectedFormat ? "selected" : ""}>${FORMATS[k].label}</option>`).join("")}
               </select>` : "";

        const formats = cfg.select ? [selectedFormat] : cfg.formats;
        const singleBtns = formats.map((k, i) =>
            `<button class="btn ${i ? "secondary" : ""}" data-dl="${k}" ${ready ? "" : "disabled"}>
                ${DX.svg("download", 16)} Download ${FORMATS[k].label}</button>`).join("");

        const allBtns = doneCount > 1 ? formats.map(k =>
            `<button class="btn secondary" data-dl-all="${k}">${DX.svg("download", 16)} All ${doneCount} files · ${FORMATS[k].short}${
                k.startsWith("invoice") ? "" : " (ZIP)"}</button>`).join("") : "";

        el.actions.innerHTML = `${picker}${singleBtns}${allBtns}
            <span style="flex:1"></span>
            <button class="btn ghost" id="copyAll" ${ready ? "" : "disabled"}>Copy text</button>
            <button class="btn ghost" id="startOver">Start over</button>`;
    }

    el.actions.addEventListener("change", event => {
        if (event.target.id === "fmtSel") { selectedFormat = event.target.value; renderActions(); }
    });

    el.actions.addEventListener("click", async event => {
        const one = event.target.closest("[data-dl]");
        const all = event.target.closest("[data-dl-all]");

        if (one) { const f = active(); if (f && f.status === "done") await download(one.dataset.dl, [f], one); }
        else if (all) await download(all.dataset.dlAll, done(), all);
        else if (event.target.closest("#copyAll")) { const f = active(); if (f && f.status === "done") copyText(f); }
        else if (event.target.closest("#startOver")) {
            files = []; activeId = null; sheetIndex = 0; tab = cfg.tab; renderAll();
        }
    });

    async function download(format, entries, button) {
        if (!entries.length) return;
        button.classList.add("loading");
        button.disabled = true;

        try {
            const out = await DX.request("/export", { json: { format, files: entries.map(e => e.result) } });
            const name = out.filename || "download";
            DX.save(out.blob, name);
            toast(`Downloaded ${name}`, "success");

            entries.forEach(e => DX.history.add({
                name: e.name, tool: FORMATS[format].short, pages: e.pages, size: e.size,
                status: (e.result.warnings || []).some(w => w.level !== "info") ? "warning" : "success",
                ocr: !!e.result.ocr_used, format,
            }));
        } catch (err) {
            toast(err.message, "error", 6500);
        } finally {
            button.classList.remove("loading");
            button.disabled = false;
        }
    }

    renderAll();
})();