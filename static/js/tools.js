/* DocuExtract PDF tools: merge and split */
(function () {
    "use strict";

    const { $, esc, fmtSize, plural, toast } = DX;
    const PAGE = window.PAGE;
    const MAX_BYTES = PAGE.maxFileMb * 1024 * 1024;

    const el = {
        drop: $("#drop"), input: $("#file"), dropTitle: $("#dropTitle"),
        overall: $("#overall"), bar: $("#overallBar"), label: $("#overallLabel"), pct: $("#overallPct"),
        resultCard: $("#resultCard"), result: $("#resultBody"),
    };

    /* ---------- shared bits ---------- */
    function setProgress(fraction, label) {
        el.overall.hidden = fraction == null;
        if (fraction == null) return;
        const pct = Math.round(fraction * 100);
        el.bar.classList.toggle("indeterminate", fraction >= 1);
        el.bar.querySelector("i").style.width = pct + "%";
        el.bar.setAttribute("aria-valuenow", pct);
        el.pct.textContent = fraction >= 1 ? "" : pct + "%";
        if (label) el.label.textContent = label;
    }

    function precheck(file) {
        if (!/\.pdf$/i.test(file.name)) return "Only PDF files are supported.";
        if (file.size === 0) return "This file is empty (0 bytes).";
        if (file.size > MAX_BYTES) return `This file is ${fmtSize(file.size)}, over the ${PAGE.maxFileMb} MB limit.`;
        return null;
    }

    async function pageInfo(file) {
        const fd = new FormData();
        fd.append("pdf", file);
        return DX.json("/info", { body: fd });
    }

    function showSuccess(title, detail, blob, name) {
        let url = URL.createObjectURL(blob);
        el.resultCard.hidden = false;
        el.result.innerHTML = `
            <div class="check">✓</div>
            <h2 style="font-size:19px">${esc(title)}</h2>
            <p class="muted" style="margin:6px 0 16px">${esc(detail)}</p>
            <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
                <a class="btn" href="${url}" download="${esc(name)}">${DX.svg("download", 16)} Download ${esc(name)}</a>
                <button class="btn secondary" id="again">Start over</button>
            </div>`;
        $("#again").addEventListener("click", () => { URL.revokeObjectURL(url); reset(); });
        el.resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    let reset = () => location.reload();

    /* =====================================================================
       MERGE
       ===================================================================== */
    function initMerge() {
        let items = [];
        let nextId = 1;
        const list = $("#list"), summary = $("#summary"), run = $("#run"), clear = $("#clear"), empty = $("#listEmpty");

        DX.dropzone(el.drop, el.input, add);

        function add(selected) {
            const room = PAGE.maxFiles - items.length;
            if (selected.length > room) {
                toast(`You can merge up to ${PAGE.maxFiles} PDFs at once.`, "error");
                selected = selected.slice(0, Math.max(room, 0));
            }
            selected.forEach(file => {
                const item = { id: nextId++, file, name: file.name, size: file.size, pages: null, error: precheck(file), status: "checking" };
                if (item.error) item.status = "error";
                items.push(item);
                if (!item.error) {
                    pageInfo(file)
                        .then(info => { item.pages = info.pages; item.status = "ready"; })
                        .catch(err => { item.error = err.message; item.status = "error"; })
                        .finally(render);
                }
            });
            el.resultCard.hidden = true;
            render();
        }

        const valid = () => items.filter(i => i.status === "ready");

        function render() {
            el.dropTitle.textContent = items.length ? "Add more PDFs" : "Drag & drop PDFs here";
            el.drop.classList.toggle("compact", items.length > 0);

            empty.innerHTML = items.length ? "" : `<div class="empty">
                <div class="empty-icon">${DX.svg("file", 26)}</div><h3>No PDFs added yet</h3>
                <p>Add two or more PDFs and they will be merged in the order shown here.</p></div>`;

            list.innerHTML = items.map((f, i) => `
                <li class="qitem ${f.status}" data-id="${f.id}" style="cursor:default">
                    <div class="qicon">${f.status === "ready" ? `<b>${i + 1}</b>` : DX.svg(f.status === "error" ? "alert" : "file")}</div>
                    <div>
                        <div class="qname">${esc(f.name)}</div>
                        <div class="qmeta"><span>${fmtSize(f.size)}</span>${f.pages ? `<span>${plural(f.pages, "page")}</span>` : ""}
                            ${f.status === "checking" ? "<span>Checking…</span>" : ""}</div>
                        ${f.error ? `<div class="qerr">${esc(f.error)}</div>` : ""}
                    </div>
                    <div class="qright">
                        <div class="order-btns">
                            <button data-up="${f.id}" aria-label="Move ${esc(f.name)} up" ${i === 0 ? "disabled" : ""}>▲</button>
                            <button data-down="${f.id}" aria-label="Move ${esc(f.name)} down" ${i === items.length - 1 ? "disabled" : ""}>▼</button>
                        </div>
                        <button class="icon-btn" data-remove="${f.id}" aria-label="Remove ${esc(f.name)}">${DX.svg("x", 16)}</button>
                    </div>
                </li>`).join("");

            const ok = valid();
            const pages = ok.reduce((n, f) => n + f.pages, 0);
            const bad = items.filter(f => f.status === "error").length;
            summary.textContent = !items.length ? "No files yet"
                : `${plural(ok.length, "file")} ready · ${plural(pages, "page")} total` + (bad ? ` · ${bad} with errors will be skipped` : "");
            run.disabled = ok.length < 2 || items.some(f => f.status === "checking");
            clear.disabled = !items.length;
        }

        list.addEventListener("click", event => {
            const up = event.target.closest("[data-up]"), down = event.target.closest("[data-down]"), rm = event.target.closest("[data-remove]");
            const move = (id, delta) => {
                const i = items.findIndex(f => f.id === Number(id));
                const j = i + delta;
                if (i < 0 || j < 0 || j >= items.length) return;
                [items[i], items[j]] = [items[j], items[i]];
            };
            if (up) move(up.dataset.up, -1);
            else if (down) move(down.dataset.down, 1);
            else if (rm) items = items.filter(f => f.id !== Number(rm.dataset.remove));
            else return;
            render();
        });

        clear.addEventListener("click", () => { items = []; el.resultCard.hidden = true; render(); });

        run.addEventListener("click", async () => {
            const ok = valid();
            if (ok.length < 2) return;

            run.classList.add("loading");
            run.disabled = true;
            el.resultCard.hidden = true;
            setProgress(0.02, "Uploading files…");

            const fd = new FormData();
            ok.forEach(f => fd.append("pdf", f.file, f.name));

            try {
                const out = await DX.request("/merge-pdf", {
                    body: fd,
                    onUpload: p => setProgress(0.05 + p * 0.8, `Uploading ${Math.round(p * 100)}%`),
                    onUploadDone: () => setProgress(1, "Merging…"),
                });
                const pages = Number(out.header("X-Pages")) || ok.reduce((n, f) => n + f.pages, 0);
                const name = out.filename || "merged.pdf";
                DX.save(out.blob, name);
                DX.history.add({ name, tool: `Merge · ${plural(ok.length, "file")}`, pages, size: out.blob.size, status: "success" });
                toast(`Merged ${plural(ok.length, "PDF")} into ${name}`, "success");
                showSuccess("PDFs merged", `${plural(ok.length, "file")} combined into one PDF with ${plural(pages, "page")} (${fmtSize(out.blob.size)}).`, out.blob, name);
            } catch (err) {
                toast(err.message, "error", 7000);
                DX.history.add({ name: "merged.pdf", tool: "Merge", status: "failed", note: err.message });
                if (err.filename) {
                    const bad = items.find(f => f.name === err.filename);
                    if (bad) { bad.status = "error"; bad.error = err.message.replace(err.filename + ": ", ""); }
                }
            } finally {
                setProgress(null);
                run.classList.remove("loading");
                render();
            }
        });

        reset = () => { items = []; el.resultCard.hidden = true; render(); };
        render();
    }

    /* =====================================================================
       SPLIT
       ===================================================================== */
    function parseRanges(spec, total) {
        spec = spec.trim();
        if (!spec) throw new Error("Enter the pages to use, for example 1-3, 5, 8-10.");
        const groups = [];
        spec.split(/[,\s;]+/).filter(Boolean).forEach(part => {
            const m = /^(\d+)(?:-(\d*))?$/.exec(part);
            if (!m) throw new Error(`"${part}" is not a valid page or range. Use e.g. 1-3, 5, 8-10.`);
            const start = Number(m[1]);
            const end = m[2] === undefined ? start : m[2] === "" ? total : Number(m[2]);
            if (start < 1 || end < 1 || start > total || end > total)
                throw new Error(`Page ${start < 1 || start > total ? start : end} is out of range. This PDF has ${plural(total, "page")}.`);
            if (start > end) throw new Error(`"${part}" is backwards. Use ${end}-${start} instead.`);
            groups.push([start, end]);
        });
        return groups;
    }

    function initSplit() {
        let current = null;     // {file, name, size, pages, error, status}
        let mode = "each";
        const body = $("#splitBody"), foot = $("#splitFoot"), summary = $("#splitSummary"), run = $("#run"), info = $("#fileInfo");

        DX.dropzone(el.drop, el.input, selected => load(selected[0]));

        async function load(file) {
            if (!file) return;
            el.resultCard.hidden = true;
            current = { file, name: file.name, size: file.size, pages: null, error: precheck(file), status: "checking" };
            if (current.error) current.status = "error";
            render();
            if (current.error) return;

            try {
                const meta = await pageInfo(file);
                current.pages = meta.pages;
                current.status = "ready";
            } catch (err) {
                current.error = err.message;
                current.status = "error";
            }
            render();
        }

        const label = ([s, e]) => (s === e ? `${s}` : `${s}-${e}`);

        function plan() {
            if (mode === "each") return { ok: true, text: `Will create ${plural(current.pages, "single-page PDF")} in a ZIP.` };
            const input = $("#ranges");
            const spec = input ? input.value : "";
            if (!spec.trim()) return { ok: false, text: "Enter the pages to use." };
            try {
                const groups = parseRanges(spec, current.pages);
                if (mode === "extract") {
                    const n = groups.reduce((sum, [s, e]) => sum + (e - s + 1), 0);
                    return { ok: true, text: `Will create one PDF with ${plural(n, "page")}.` };
                }
                return { ok: true, text: groups.length === 1
                    ? `Will create one PDF (pages ${label(groups[0])}).`
                    : `Will create ${groups.length} PDFs in a ZIP: ${groups.map(label).join(", ")}.` };
            } catch (err) {
                return { ok: false, text: err.message, error: true };
            }
        }

        function render() {
            el.dropTitle.textContent = current ? "Choose a different PDF" : "Drag & drop a PDF here";
            el.drop.classList.toggle("compact", !!current);

            info.innerHTML = current ? `
                <li class="qitem ${current.status}" style="cursor:default">
                    <div class="qicon">${DX.svg(current.status === "error" ? "alert" : current.status === "ready" ? "check" : "file")}</div>
                    <div><div class="qname">${esc(current.name)}</div>
                        <div class="qmeta"><span>${fmtSize(current.size)}</span>${current.pages ? `<span>${plural(current.pages, "page")}</span>` : ""}
                        ${current.status === "checking" ? "<span>Checking…</span>" : ""}</div>
                        ${current.error ? `<div class="qerr">${esc(current.error)}</div>` : ""}</div>
                    <div class="qright"><button class="icon-btn" id="rm" aria-label="Remove file">${DX.svg("x", 16)}</button></div>
                </li>` : "";
            const rm = $("#rm");
            if (rm) rm.addEventListener("click", () => { current = null; render(); });

            if (!current || current.status !== "ready") {
                foot.hidden = true;
                body.innerHTML = `<div class="empty"><div class="empty-icon">${DX.svg("file", 26)}</div>
                    <h3>${current && current.status === "checking" ? "Checking your PDF…" : "Upload a PDF to continue"}</h3>
                    <p>${current && current.error ? "Fix the problem above or choose another PDF." : "Once your PDF is loaded you can choose how to split it."}</p></div>`;
                return;
            }

            const keep = $("#ranges") ? $("#ranges").value : "";
            body.innerHTML = `
                <div class="radio-cards" role="radiogroup" aria-label="Split mode">
                    ${[["each", "Every page", "One PDF per page, delivered as a ZIP."],
                       ["ranges", "By page ranges", "One PDF for each range, e.g. 1-3, 4-6."],
                       ["extract", "Extract pages", "Pick pages and get them in a single PDF."]].map(([key, title, text]) => `
                    <label class="radio-card"><input type="radio" name="mode" value="${key}" ${mode === key ? "checked" : ""}><b>${title}</b><span>${text}</span></label>`).join("")}
                </div>
                <div class="field" id="rangeField" style="margin-top:16px;max-width:420px" ${mode === "each" ? "hidden" : ""}>
                    <label for="ranges"><span>Pages (this PDF has ${plural(current.pages, "page")})</span></label>
                    <input id="ranges" value="${esc(keep)}" placeholder="e.g. 1-3, 5, 8-" autocomplete="off">
                    <p class="muted small" style="margin-top:5px">Use commas between pages or ranges. "8-" means page 8 to the end.</p>
                </div>`;
            foot.hidden = false;
            update();
        }

        function update() {
            const p = plan();
            summary.textContent = p.text;
            summary.style.color = p.error ? "var(--danger)" : "";
            run.disabled = !p.ok;
        }

        body.addEventListener("change", event => {
            if (event.target.name === "mode") {
                mode = event.target.value;
                $("#rangeField").hidden = mode === "each";
                update();
            }
        });
        body.addEventListener("input", event => { if (event.target.id === "ranges") update(); });

        run.addEventListener("click", async () => {
            if (!current || current.status !== "ready") return;
            run.classList.add("loading");
            run.disabled = true;
            el.resultCard.hidden = true;
            setProgress(0.02, "Uploading…");

            const fd = new FormData();
            fd.append("pdf", current.file, current.name);
            fd.append("mode", mode);
            fd.append("ranges", $("#ranges") ? $("#ranges").value : "");

            try {
                const out = await DX.request("/split-pdf", {
                    body: fd,
                    onUpload: p => setProgress(0.05 + p * 0.8, `Uploading ${Math.round(p * 100)}%`),
                    onUploadDone: () => setProgress(1, "Splitting…"),
                });
                const parts = Number(out.header("X-Parts")) || 1;
                const name = out.filename || "split.zip";
                DX.save(out.blob, name);
                DX.history.add({ name: current.name, tool: `Split · ${plural(parts, "file")}`, pages: current.pages, size: current.size, status: "success" });
                toast(`Created ${plural(parts, "file")}: ${name}`, "success");
                showSuccess("PDF split", `Created ${plural(parts, "PDF")} from ${current.name} (${fmtSize(out.blob.size)}).`, out.blob, name);
            } catch (err) {
                toast(err.message, "error", 7000);
                DX.history.add({ name: current.name, tool: "Split", status: "failed", note: err.message });
            } finally {
                setProgress(null);
                run.classList.remove("loading");
                update();
            }
        });

        reset = () => { current = null; el.resultCard.hidden = true; render(); };
        render();
    }

    if (PAGE.mode === "merge") initMerge();
    else if (PAGE.mode === "split") initSplit();
})();